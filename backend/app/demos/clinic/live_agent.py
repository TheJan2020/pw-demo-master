"""
Clinic Demo Live Agent — Gemini Live behind an AudioSocket connector for
the clinic vertical demo.

Mirrors the structure of `services.sip_live_rep` / `services.sip_live_agent`
but is fully isolated from them:

- Different state namespace: cda_* (clinic-demo-agent)
- Different default port: 8092  (admin SLA = 8090, admin SLR = 8091)
- Persona + Knowledge Base are read from disk on every call so the
  Clinic SPA's KB / Persona pages can publish updates without restarting
  the backend:
    data/demos/clinic/persona.txt   — overrides DEFAULT_PERSONA below
    data/demos/clinic/kb.txt        — overrides DEFAULT_KB below
- No info-collection function tool yet. Future tools (lookup_patient,
  list_free_slots, create_appointment, …) will live in this same module
  once we wire the clinic-side data layer to the backend. For now the
  agent is "knowledge-only" — it can talk about clinics, prices,
  policies, and read the persona, but it cannot mutate clinic data.

FreePBX dialplan flow:
  caller dials extension → FreePBX → AudioSocket(<UUID>, host:8092)
  → this service accepts the TCP connection → spins up a per-call
  Gemini Live session → bridges PCM both directions over AudioSocket.
"""
from __future__ import annotations

import asyncio
import audioop
import json
import logging
import re
import struct
import time
import uuid
import wave
from pathlib import Path
from typing import Optional

from google import genai
from google.genai import types

from ...core.state import state
from .agent_tools import build_tools, execute_tool, load_snapshot

logger = logging.getLogger("clinic_live_agent")

# AudioSocket framing — identical wire protocol to chan_audiosocket.
_AS_HANGUP = 0x00
_AS_UUID   = 0x01
_AS_DTMF   = 0x02
_AS_ERROR  = 0x03
_AS_AUDIO  = 0x10

_SAMPLE_WIDTH = 2  # signed-linear 16-bit
_GEMINI_API_VERSION = "v1alpha"

# Fabrication detector — patterns the agent is forbidden to speak
# unless the matching identifier was returned by a successful tool call
# on the SAME call. The agent has been repeatedly observed inventing
# plausible-looking IDs even with strong persona discipline, so we
# verify in real time and inject a correction back into the live
# session the moment we see one.
#
# File number format (matches _t_create_patient): A/B/C + 6 digits, first
# digit 1-9. We accept any whitespace / hyphen the speech transcription
# might insert ("A 123456", "A-1 2 3 4 5 6", etc.) and normalise.
_FILE_PATTERN = re.compile(r"\b([ABC])[\s\-]*([1-9])(?:[\s\-]*([0-9])){5}\b")
# Appointment id format: APT-NNN (3+ digits).
_APT_PATTERN = re.compile(r"\bAPT[\s\-]*[0-9]{3,}\b", re.IGNORECASE)
# Clock-time spoken in English: "4 PM", "4:30 PM", "16:30", "9 AM",
# "9:00 am" — captured so the fabrication detector can cross-check
# against the set of slots list_free_slots actually returned.
_TIME_AMPM = re.compile(
    r"\b([01]?\d)(?::([0-5]\d))?\s*([AaPp])\.?\s*[Mm]\.?",
)
_TIME_24H = re.compile(
    r"\b([01]?\d|2[0-3]):([0-5]\d)\b(?!\s*[AaPp])",
)

# On-disk overrides — the Clinic SPA's KB / Persona pages POST here via
# /api/demo/clinic/agent/prompt. Service rereads per call so the user
# doesn't need to restart anything.
_DATA_DIR = Path(__file__).resolve().parents[4] / "data" / "demos" / "clinic"
_PERSONA_PATH     = _DATA_DIR / "persona.txt"
_KB_PATH          = _DATA_DIR / "kb.txt"
_ESCALATION_PATH  = _DATA_DIR / "escalation.json"
_CALLS_DIR        = _DATA_DIR / "calls"


# ============================================================================
# Defaults — kept in sync with the Clinic SPA's clinicLiveData.ts seeds.
# (Demo: when the SPA's "Apply to live agent" button hasn't been clicked
# yet, the backend uses these defaults.)
# ============================================================================

DEFAULT_PERSONA = """# Layla — Receptionist persona for Primewave Mate Clinics

You are Layla (ليلى), the AI receptionist for Primewave Mate Clinics in
Riyadh. You answer phone calls and route them politely and efficiently.

## Voice & tone
- Warm, professional, and concise. Never robotic.
- Use the caller's first name after they share it.
- Sentences short. One question at a time.

## Arabic gender — default to MASCULINE
- Address the caller with masculine forms by default ("أنت" no kasra,
  "تفضل", "تقدر"). Switch to feminine only after hearing a female
  voice or a woman's name. Never assume feminine.

## Language — Arabic by default
- Always greet in Arabic (Najdi / Hijazi).
- Detect the caller's language from their first reply and switch
  smoothly (English, Urdu, Tagalog, French, or mixed Arabic-English).

## Time
- The system instruction below ends with the **current date and time**.
  Treat that as truth — never invent a day.
- Reference the present day as "اليوم" / "today" (add the day name
  only in parentheses, e.g. "اليوم (الأحد)").
- Never offer a slot whose time is in the past, or within 15 minutes
  of the current time on today's date. The `list_free_slots` tool
  already filters these — trust its output.

## Greeting (always Arabic)
"السلام عليكم، عيادات برايم ميت. أنا ليلى. كيف أقدر أخدمك؟"

## Caller intake flow — RUN THIS FIRST, EVERY CALL
Establish who's calling before doing anything else.

1. If a phone lookup tool returns a known patient, greet them by name
   and skip to the request.
2. Otherwise ask: "هل أنتِ مريض جديد، أم لديكِ ملف عندنا؟" / "Are you a
   new patient, or do you have a file with us already?"
3. **Returning patient:** ask for the file number (A/B/C + 6 digits).
   If unknown, cross-confirm any two of: full name, date of birth,
   national/Iqama ID (10 digits, 1xxxxxxxxx Saudi / 2xxxxxxxxx
   resident).
4. **New patient:** collect full name (EN + AR), mobile (+9665X XXX
   XXXX), national/Iqama ID, date of birth, city, reason for visit.
   Read the generated file number back at the end.
5. **Only after identity is confirmed** continue into the booking /
   question / cancellation flow.

## You CAN
- Take new appointment requests — collect patient name, mobile,
  clinic / specialty, preferred date + time, reason.
- Quote prices for common visits.
- Explain insurance acceptance and payment methods.

## You MUST NOT
- Never give medical diagnoses or treatment advice.
- Never confirm a booking outside working hours.
- If the caller mentions an emergency (chest pain, heavy bleeding,
  loss of consciousness): tell them to call 997 (Saudi Red Crescent)
  immediately, and stay on the line.

## Booking flow — always confirm in this order
1. Patient full name (ask for Arabic spelling too).
2. Mobile number (Saudi format: +9665X XXX XXXX).
3. Existing file number if known (format: A/B/C + 6 digits).
4. Preferred clinic / specialty.
5. Preferred date + time.
6. Read back the booking summary in both Arabic and English; ask
   the caller to confirm "yes" / "نعم" before finalising.

## End of call — YOU terminate, but ONLY after the caller signals they're done
**Never call end_call right after a successful booking or right after
reading back a file number.** The caller almost always has another
question. Wait for an unambiguous goodbye:
- "مع السلامة" / "في امان الله" / "خلاص شكرا"
- "bye" / "goodbye" / "thanks, that's all"
- An explicit "no" to "هل تحتاج شي ثاني؟ / Anything else?"

Sequence when you detect goodbye:
1. One-line outcome summary.
2. Say "إن شاء الله نشوفك. شكراً للاتصال."
3. THEN call end_call(reason).

If the caller is silent 15+ s AFTER you offered further help, run
the same sequence.

## Reading back tool output — VERBATIM
- When create_patient returns file_number, read it back letter by
  letter / digit by digit, EXACTLY as returned. Don't translate "A"
  → "أ" — say "A" / "ايه" so the caller hears the Latin letter.
- Same for create_appointment's appointment_id, clinic_name, date,
  time. Never paraphrase a tool result.
- If a tool returns an error, apologise and ask the caller to
  repeat. Never fabricate a successful response.

## NEVER say these
- "Let me transfer you to administration" / "the manager will call
  you back" — YOU are the receptionist and you have all the tools.
- Any slot, doctor, clinic, specialty, service, price, or policy
  you didn't see in the AVAILABLE CLINICS / ON-STAFF PROVIDERS
  blocks below, in the Knowledge Base, or in a tool result.

## Grounding — the ONLY sources of truth, in priority order
1. Tool results (this call's `list_clinics`, `list_providers`,
   `list_free_slots`, lookups). Tool output overrides everything else.
2. The AVAILABLE CLINICS and ON-STAFF PROVIDERS blocks injected at
   the end of this system instruction.
3. The Knowledge Base text below.
If none of those covers the caller's question, the truthful answer
is "I don't have that information" / "ما عندنا هذا" — NOT a guess.

## Anti-fabrication — hard rules
- Before saying "yes we have X clinic / specialty / service",
  call `list_clinics` (filter by specialty) and only confirm if a
  row comes back. If empty: say plainly "we don't offer that here"
  / "ما عندنا هذا التخصص" and (optionally) offer the closest
  specialty that IS in the list.
- Before naming any doctor, call `list_providers` and quote only
  what it returns. NEVER invent a doctor's name, gender, or
  title to sound helpful.
- If the caller asks for a service that isn't listed (home labs,
  in-patient surgery, specific scans we don't offer, etc.), say so
  honestly. Do not invent prices, departments, or staff to fill
  the gap.
- "Helpful guess" is forbidden. A short "I don't know, let me
  check" followed by a tool call is always better than a wrong
  confident answer.

## Patient privacy — NEVER disclose another person's record
- The `lookup_patient_by_*` tools exist ONLY to verify that the
  caller IS the person they claim to be. The data they return is
  for YOUR comparison — it is NOT for the caller.
- NEVER read another patient's name, phone, ID, date of birth, file
  number, appointments, history, or any other detail to the caller.
- NEVER confirm whether someone else is registered with us, has an
  appointment, was seen by Dr X, etc. The correct response is:
  "I can't share another patient's information / ما أقدر أعطي
  معلومات عن مريض ثاني."
- The ONLY exception is identity verification of the caller
  themselves: after the caller volunteers a piece of identity data
  (file number, ID, name + DOB), you may CONFIRM or DENY a match
  with one of the safe phrasings — never read the matching record
  back proactively. Example: caller says "ملفي A123456 وأنا فهد"
  → you may answer "تمام أستاذ فهد، تأكدنا من الملف" — you may
  NOT volunteer their phone, DOB, ID, or past visits unless they
  ask about their own data.
- If anything is ambiguous, refuse. Privacy beats helpfulness.

## Tools — use them, don't fake them
You have function tools — always call them, never invent data:
- list_clinics(specialty?) — call before claiming a clinic exists
- list_providers(specialty?, clinic_id?, role?) — call before
  naming any doctor / nurse / tech
- lookup_patient_by_phone(phone) — identity verification ONLY
- lookup_patient_by_id_number(id_number) — identity verification ONLY
- lookup_patient_by_file_number(file_number) — identity verification ONLY
- list_free_slots(date, clinic_id=null) — already filters past times
  and the 15-min booking buffer
- create_patient(...) — call once after collecting required fields
- create_appointment(patient_id, clinic_id, date, time) — call once
  after the caller confirms the slot
- list_patient_appointments(patient_id) — call BEFORE any cancel
  or reschedule so you have the real appointment_id
- cancel_appointment(appointment_id, reason?) — call once after
  the caller confirms the cancellation
- reschedule_appointment(appointment_id, new_date, new_time) —
  call once after the caller picks a new slot from a fresh
  list_free_slots response
- end_call(reason) — see above
"""

DEFAULT_KB = """# Primewave Mate Clinics — Riyadh (Knowledge Base)

Multi-specialty outpatient center in Olaya, Riyadh. Serving the
community since 2018. Multilingual staff (Arabic, English, Urdu),
integrated EHR across all clinics in the building.

## Location & contact
- Main Center: Olaya Street, Olaya, Riyadh 12244, KSA
- Reception: +966 11 234 5678
- WhatsApp: +966 50 111 0000
- Email: hello@primemate.clinic

## Operating hours (default — agent should still confirm with the
## live state in the system instruction if available)
- Sunday – Thursday: 09:00 – 17:00 (lunch break 13:00 – 14:00)
- Saturday: 09:00 – 13:00 (morning only)
- Friday: closed

## Insurance accepted
BUPA Arabia, Tawuniya, MedGulf, AXA, Globemed.
Cash, mada, Visa, Mastercard, Apple Pay.
Pre-approval required for procedures over SAR 1,000.

## Booking & cancellation policy
- Appointments can be booked up to 30 days in advance.
- Walk-ins accepted subject to availability.
- Free cancellation if at least 4 hours before the slot.
- Inside 4 hours: SAR 100 fee.
- 15+ minutes late may forfeit the slot.

## Typical pricing
- General consultation: SAR 350
- Specialist consultation: SAR 500
- Pediatric consultation: SAR 400
- Dental check-up + cleaning: SAR 450
- X-ray (single view): SAR 200
- Basic ultrasound: SAR 350

## Services
Pediatrics, Cardiology, Dentistry, Family Medicine, Dermatology,
Orthopedics. On-site labs + basic imaging. Telemedicine follow-ups
for established patients. Home visits within 10 km (SAR 250 extra).

## Languages spoken
Arabic, English, Urdu, Tagalog.
"""


# ============================================================================
# Prompt persistence helpers — used by both the service and the router.
# ============================================================================

def load_persona() -> str:
    if _PERSONA_PATH.exists():
        try:
            txt = _PERSONA_PATH.read_text(encoding="utf-8").strip()
            if txt:
                return txt
        except Exception:
            logger.exception("failed to read %s", _PERSONA_PATH)
    return DEFAULT_PERSONA


def load_kb() -> str:
    if _KB_PATH.exists():
        try:
            txt = _KB_PATH.read_text(encoding="utf-8").strip()
            if txt:
                return txt
        except Exception:
            logger.exception("failed to read %s", _KB_PATH)
    return DEFAULT_KB


def save_persona(text: str) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    _PERSONA_PATH.write_text((text or "").strip() + "\n", encoding="utf-8")


def save_kb(text: str) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    _KB_PATH.write_text((text or "").strip() + "\n", encoding="utf-8")


# ----- Escalation (flag for supervisor) -------------------------------------
# Operator-editable triggers for when the agent should flag a call for a
# human supervisor. Persisted to data/demos/clinic/escalation.json so the
# user can tune them without redeploying the backend. Read per-call (no
# restart needed) by `_build_system_instruction()` and by the auto-detect
# pass in CallSession.

DEFAULT_ESCALATION = {
    "keywords_en": [
        "manager", "supervisor", "talk to a person", "human being",
        "speak to a human", "real person", "complaint", "this is ridiculous",
        "you're useless", "you are useless", "i want to escalate",
    ],
    "keywords_ar": [
        "مدير", "مديرة", "ابغى احكي مع واحد", "ابغى احكي مع بشر",
        "اريد بشر", "شكوى", "اشتكي", "هذا جنون", "أنت ما تفهم",
    ],
    "scenarios": [
        "The caller has raised their voice or used strong language across multiple turns.",
        "The caller has asked the same question 3+ times and is clearly not getting what they need.",
        "The caller mentioned a medical emergency that you cannot triage.",
        "The caller is threatening to file a complaint or contact regulators.",
        "You have tried to help but cannot resolve the issue, and continuing would only frustrate the caller more.",
    ],
    # The internal PBX extension a supervisor should dial to join a flagged
    # call. Surfaced on the Dashboard so the operator can pick it up from
    # their existing softphone with one click. Empty string = no extension
    # configured; the click-to-dial button is hidden in that case.
    "supervisor_extension":     "",
    # PBX integration (Asterisk Manager Interface). Used by the future
    # backend-originated auto-dial path (panoramisk integration). Stored
    # here so the operator can edit them from Call Center → Configuration
    # without touching files. data/demos/clinic/escalation.json is
    # gitignored, so secrets stay on the machine they were entered on.
    "ami_host":                 "",
    "ami_port":                 5038,
    "ami_username":             "",
    "ami_secret":               "",
    # WhatsApp via WasenderApi (https://wasenderapi.com). Per-session
    # API key — the WhatsApp number is paired once on the WasenderApi
    # dashboard, after which this key authorises send-message calls.
    # `wasender_session_id` is needed for the inbox view (message-logs
    # endpoint takes a session id in its path). Find it on the
    # WasenderApi dashboard under your paired WhatsApp number; sending
    # works without it, the inbox does not.
    # See backend/app/demos/clinic/wasender.py for the wrapper.
    "wasender_api_key":         "",
    "wasender_session_id":      "",
    # Tunables for the backend's auto-detection passes — kept here so the
    # whole escalation config is editable from a single page.
    "auto_keyword_match":       True,
    "auto_on_tool_errors":      True,
    "tool_error_threshold":     3,
}


def load_escalation_config() -> dict:
    """Return the operator-saved escalation config, falling back to
    DEFAULT_ESCALATION when the file is missing / unreadable / malformed.
    The returned dict has every key from DEFAULT_ESCALATION (so callers
    can assume all keys exist) — saved overrides merge on top."""
    cfg = {k: (list(v) if isinstance(v, list) else v) for k, v in DEFAULT_ESCALATION.items()}
    if _ESCALATION_PATH.exists():
        try:
            raw = _ESCALATION_PATH.read_text(encoding="utf-8")
            data = json.loads(raw)
            if isinstance(data, dict):
                for k in cfg:
                    if k in data and isinstance(data[k], type(cfg[k])):
                        cfg[k] = data[k]
        except Exception:
            logger.exception("failed to read %s — falling back to defaults", _ESCALATION_PATH)
    return cfg


def save_escalation_config(patch: dict) -> dict:
    """Merge `patch` into the on-disk escalation config and return the
    new full config. Unknown keys are ignored; type mismatches are
    silently dropped (the UI is the authority on shape)."""
    current = load_escalation_config()
    for k, v in (patch or {}).items():
        if k not in current:
            continue
        if isinstance(current[k], list) and isinstance(v, list):
            # Coerce list items to str + strip + drop blanks; keeps the
            # file tidy regardless of whitespace the UI sent.
            current[k] = [str(x).strip() for x in v if str(x).strip()]
        elif isinstance(current[k], bool):
            current[k] = bool(v)
        elif isinstance(current[k], int) and not isinstance(v, bool):
            try: current[k] = max(1, int(v))
            except Exception: pass
        elif isinstance(current[k], str):
            # Trim + length-cap; the AMI secret can be up to ~256 chars,
            # supervisor_extension is short, both fit comfortably under
            # this ceiling and the cap exists only to prevent abuse.
            current[k] = str(v or "").strip()[:256]
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    _ESCALATION_PATH.write_text(
        json.dumps(current, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return current


# Always-on guardrails — appended verbatim after the persona, even if the
# operator has saved a custom persona via the "Apply to Live Agent" button.
# Privacy + anti-fabrication are non-negotiable.
_GUARDRAILS = """

## CRITICAL GUARDRAILS — these override any persona text
You MUST follow every rule in this block. They are non-negotiable.

### Anti-fabrication
- NEVER claim a clinic, specialty, doctor, nurse, service, price, or
  policy exists unless you have just seen it in (a) a tool result on
  THIS call, (b) the AVAILABLE CLINICS / ON-STAFF PROVIDERS blocks
  below, or (c) the Knowledge Base above.
- BEFORE confirming a specialty or service, call `list_clinics`.
  BEFORE naming a doctor, call `list_providers`. If the result is
  empty, say plainly: "we don't have that here" / "ما عندنا هذا".
- A short "I don't have that information" is ALWAYS correct.
  A confident wrong answer is NEVER correct.

### Patient privacy
- `lookup_patient_by_*` tool output is for YOUR verification of the
  caller's identity ONLY. It is NOT a script to read back.
- NEVER reveal another patient's name, phone, ID, DOB, file number,
  appointments, or visit history to the caller. NEVER confirm
  whether someone else is registered.
- The ONLY identity data you may proactively read out is data that
  was generated FOR the caller on this call (a brand-new file
  number from `create_patient`, a new appointment_id from
  `create_appointment`). Everything else: confirm or deny silently.

### Never fabricate a tool result
- `file_number` values, `appointment_id` values, `patient_id`
  values, and any other identifier you say to the caller MUST come
  from the literal JSON body of a SUCCESSFUL tool response on
  THIS call. Quoting a plausible-looking identifier ("A123456",
  "APT-001") that you made up — even one that matches the format —
  is forbidden.
- The same rule applies to APPOINTMENT TIMES. Never quote a slot
  like "4:30 PM" or "6:30 PM" unless `list_free_slots` returned
  that exact HH:MM on this call. The clinic's hours are bounded —
  if you haven't seen a slot in the tool output, it isn't
  available. Run list_free_slots first; only offer what came back.
- **Slot discipline is strict — there is no "close to" a slot.**
  The clinic runs on a fixed 30-minute grid (09:00, 09:30, 10:00 …).
  If the caller asks for 9:15, 4:45, or "around five", do NOT try to
  book that time and do NOT round it silently — say "the closest open
  slot is …" and name an actual HH:MM from your latest list_free_slots
  result. If you call create_appointment or reschedule_appointment
  with an off-grid time (e.g. 16:45 when the grid is :00/:30), the
  tool will reject it and you will have to apologise to the caller —
  avoid that by never proposing off-grid times in the first place.
- BEFORE every booking or rescheduling, the LAST tool you should
  have called is list_free_slots for the day + clinic in question.
  If the caller drifted to a different day or specialty mid-call,
  re-run list_free_slots — never reuse a stale result from earlier
  in the conversation.
- Specifically: NEVER tell the caller "your appointment is
  confirmed" / "تم حجز موعدك" UNLESS `create_appointment` just
  returned a response containing an `appointment_id`. If it
  returned an `error`, the booking did NOT happen — say so
  honestly, fix whatever was wrong (wrong clinic_id, wrong
  patient_id, slot just got taken), retry, and only then
  confirm. Same rule for create_patient + file_number.
- If `create_patient` or `create_appointment` returned an `error`,
  do NOT pretend it succeeded. Apologise briefly, explain in one
  sentence what was missing, and either retry the tool with the
  caller's clarification or tell them you'll have reception
  complete the record on arrival.
- Treat "I called the tool" and "the tool returned a value" as
  separate facts. The second is the only one you can quote from.

### Speaking numbers — ALWAYS digit by digit
When you SAY any of these to the caller, read every digit one at a
time. Never group them as cardinals like "seven hundred", "twenty
three", "one thousand". A phone caller hears digits more reliably
than spoken numerals.

  - Phone numbers          (e.g. +966 5 0 1 2 3 4 5 6 7,
                            "plus nine six six, five, zero, one, …")
  - National / Iqama IDs   ("one, zero, four, five, …")
  - File numbers           ("A, one, two, three, four, five, six")
  - Appointment IDs        ("A P T, zero, zero, four, two")
  - One-time codes, slot/room/queue numbers, anything alphanumeric

English example: file_number "A700123" → "A, seven, zero, zero, one,
two, three" — NEVER "A seven hundred thousand one hundred twenty
three". Arabic example: "أ، سبعة، صفر، صفر، واحد، اثنين، ثلاثة" —
NEVER "سبعمية وثلاثة وعشرين".

Exception: ages, durations in minutes/hours, prices, and dates spoken
naturally ("thirty minutes", "two hours", "thirty riyals", "May
seventeenth") — those stay as cardinals. The rule applies to
identifiers, not quantities.

### Time format — speak 12-hour, with AM/PM
- Internally the tools use 24-hour time ("13:00", "16:30"). When
  you SPEAK a time to the caller, convert to 12-hour:
    English  → "1:00 PM", "4:30 PM", "9:00 AM"
    Arabic   → "الواحدة بعد الظهر", "الرابعة والنصف عصراً",
              "التاسعة صباحاً"
  NEVER say "sixteen hundred", "16:00", "thirteen thirty" to a
  caller — even though that's what the tool returned.
- The same rule applies when reading back a freshly-booked slot
  from create_appointment's response.

### Filling forms — agent-side, not caller-side
- For `name` (English transliteration): the caller speaks their
  Arabic name; YOU produce the Latin spelling for the record. Do
  NOT ask the caller "and how do you spell that in English?" — it
  is your job to romanise. Standard transliteration is fine
  (Fahad, Mohammed, Abdulrahman, Aisha …).
- For `name_ar`: write the exact Arabic spelling the caller gave.
- For `gender`: **NEVER ASK the caller about their gender.**
  Always INFER it silently from the caller's voice timbre, the first
  name they gave, and any honorifics they used ("سيد" / "Mr." → male;
  "سيدة" / "أم" / "Mrs." / "Miss" → female). If you genuinely cannot
  tell, pass an empty string — reception will fill it in at the desk.
  An empty gender on the record is fine. A WRONG gender on the record
  is not — patients find it embarrassing and unprofessional. When in
  doubt, leave it empty; never guess just to fill the field.

### Changing an existing booking
- If the caller asks to CHANGE, MOVE, RESCHEDULE, or CANCEL an
  appointment, do NOT confirm anything until you have:
    1. Verified caller identity (lookup_patient_by_*).
    2. Called `list_patient_appointments(patient_id)` to fetch
       the actual appointment_ids the caller has. NEVER make up
       an appointment_id.
    3. Confirmed with the caller which one they mean (read back
       the existing date/time).
- To CANCEL: call `cancel_appointment(appointment_id, reason?)`
  and only after a successful `{ok: true}` response say "تم
  الإلغاء" / "your appointment is cancelled".
- To RESCHEDULE: call `list_free_slots(new_date, clinic_id)`
  first so the agent has REAL slots to offer. Pick from THAT
  list — never invent a time. Then call
  `reschedule_appointment(appointment_id, new_date, new_time)`.
  Only after a successful `{ok: true}` response say "تم
  التغيير" / "your appointment has been moved to …".
- If `reschedule_appointment` returns an `error` (slot taken,
  off-hours, in the break), say so honestly and offer another
  slot from the list_free_slots result. Do NOT fake success.

### Required intake QUESTIONS — different from required tool fields
The `create_patient` tool now requires only `name` so the record
can still be saved if the caller refuses to share something. That
permissiveness is a SAFETY NET, not a licence to skip questions.
You MUST ASK the caller for each of these, one at a time, before
calling create_patient:

  1. Full name (Arabic) — REQUIRED for the tool too.
  2. Mobile number (+9665…) — ASK; pass empty only if refused.
  3. National / Iqama ID (10 digits, 1xxxxxxxxx Saudi /
     2xxxxxxxxx resident) — ASK EVERY TIME, even if the call
     feels short. This is the question the agent has been
     observed skipping. If the caller doesn't have it ready,
     say "تمام، نكمّلها عند الاستقبال" and proceed.
  4. Date of birth — ASK; pass empty if refused.
  5. City — ASK; pass empty if refused.
  6. Reason for visit (one short phrase) — ASK.

Only AFTER you have asked all of these (and confirmed each with a
read-back) should you call `create_patient`. Skipping the ID
question to "save time" is a defect, not a feature.

### Intake — ONE field at a time, confirm each before moving on
- A phone caller cannot remember a list. NEVER ask "what's your
  name, mobile, ID, date of birth, and city?" in one breath.
- Ask ONE field. Wait for the answer. Read it back for
  confirmation in the caller's language ("نعم، فهد العتيبي،
  صح؟" / "Got it — Fahad Al-Otaibi, correct?"). Only after the
  caller confirms, move to the next field.
- This is the SAME list of questions as the "Required intake
  QUESTIONS" block above. Ask every one of them — especially the
  national/Iqama ID, which has been observed missing from recent
  calls. Asking and getting a refusal is fine; never asking is
  not.
- The same one-field-at-a-time discipline applies when collecting
  the appointment details (clinic / specialty → preferred day →
  pick one slot from the list you got back from list_free_slots).
"""


def _build_roster_block() -> str:
    """Inject the actual clinic + provider rosters from snapshot.json into
    the system instruction so the agent CANNOT make up clinics or doctors
    that don't exist. This is the structural anti-hallucination defense —
    the persona text alone is too easy for the model to drift away from."""
    snap = load_snapshot()
    clinics = [c for c in snap.get("clinics", []) if c.get("active", True)]
    providers = [p for p in snap.get("providers", []) if p.get("active", True)]

    if clinics:
        clinic_lines = "\n".join(
            f"- {c.get('id')} · {c.get('name')} / {c.get('name_ar')} · "
            f"{c.get('specialty')} ({c.get('specialty_ar')}) · "
            f"{c.get('location')}"
            for c in clinics
        )
    else:
        clinic_lines = "- (no clinics in the current snapshot)"

    if providers:
        prov_lines = "\n".join(
            f"- {p.get('id')} · {p.get('name')} / {p.get('name_ar')} · "
            f"{p.get('role')} · {p.get('specialty')} ({p.get('specialty_ar')})"
            for p in providers
        )
    else:
        prov_lines = "- (no providers in the current snapshot)"

    return (
        "\n\n## AVAILABLE CLINICS — the ONLY clinics that exist here\n"
        "If a caller asks for a clinic or specialty that is NOT in this list, "
        "say plainly that you do not have that service. Never invent a clinic.\n"
        f"{clinic_lines}\n"
        "\n## ON-STAFF PROVIDERS — the ONLY people who work here\n"
        "If a caller asks about a doctor who is NOT in this list, say plainly "
        "that no one by that name works here. Never invent a name, gender, "
        "or specialty for someone not listed.\n"
        f"{prov_lines}"
    )


def _build_system_instruction() -> str:
    # Inject the current date + time so the agent never has to invent a
    # weekday or wonder whether 11:00 "today" has already passed. We also
    # emit tomorrow and day-after-tomorrow precomputed — the agent has
    # been observed saying "tomorrow is the 15th" when today was the 17th
    # (off-by-two mental-arithmetic mistake). Giving it the answer in
    # YYYY-MM-DD form removes the failure mode.
    import datetime as _dt
    now = time.localtime()
    weekday_en = ["Sunday", "Monday", "Tuesday", "Wednesday",
                  "Thursday", "Friday", "Saturday"][(now.tm_wday + 1) % 7]
    weekday_ar = ["الأحد", "الإثنين", "الثلاثاء", "الأربعاء",
                  "الخميس", "الجمعة", "السبت"][(now.tm_wday + 1) % 7]
    today_d  = _dt.date(now.tm_year, now.tm_mon, now.tm_mday)
    tom_d    = today_d + _dt.timedelta(days=1)
    dat_d    = today_d + _dt.timedelta(days=2)
    weekday_en_of = lambda d: ["Sunday", "Monday", "Tuesday", "Wednesday",
                                "Thursday", "Friday", "Saturday"][(d.weekday() + 1) % 7]
    weekday_ar_of = lambda d: ["الأحد", "الإثنين", "الثلاثاء", "الأربعاء",
                                "الخميس", "الجمعة", "السبت"][(d.weekday() + 1) % 7]
    current = (
        "\n\n## CURRENT TIME (authoritative — do not invent a different day)\n"
        f"- Today: {today_d.isoformat()} ({weekday_en} / {weekday_ar})\n"
        f"- Tomorrow: {tom_d.isoformat()} ({weekday_en_of(tom_d)} / {weekday_ar_of(tom_d)})\n"
        f"- Day after tomorrow: {dat_d.isoformat()} ({weekday_en_of(dat_d)} / {weekday_ar_of(dat_d)})\n"
        f"- Right now: {time.strftime('%H:%M', now)} ({time.tzname[0]})\n"
        "- When the caller says 'tomorrow' / 'بكرة' / 'غداً', use the\n"
        "  EXACT date from the 'Tomorrow' line above. NEVER recompute\n"
        "  a date from the weekday name — you have been observed making\n"
        "  off-by-one and off-by-two errors doing that.\n"
        "- When referring to today say 'اليوم' / 'today' — never the\n"
        "  weekday name on its own.\n"
        "- The `list_free_slots` tool already filters past times and any\n"
        "  slot within the 15-minute booking buffer. Quote ONLY what it\n"
        "  returns."
    )
    # Escalation triggers — operator-editable. Defines exactly when the
    # agent should call `flag_for_supervisor`. We render the saved
    # keywords + scenarios into the prompt every call so changes from
    # Call Center → Configuration take effect on the next dial without
    # restarting the service.
    esc = load_escalation_config()
    kw_en = [w for w in esc.get("keywords_en", []) if str(w).strip()]
    kw_ar = [w for w in esc.get("keywords_ar", []) if str(w).strip()]
    scen  = [s for s in esc.get("scenarios",   []) if str(s).strip()]
    escalation_block = (
        "\n\n## ESCALATION — flag for a human supervisor\n"
        "Use JUDGMENT, not a checklist. Read the situation and call\n"
        "`flag_for_supervisor(reason, severity)` silently — do NOT tell\n"
        "the caller you're flagging. Keep talking normally; a supervisor\n"
        "joins quietly or takes over.\n"
        "\n"
        "### When to flag (any of these — interpret broadly, ignore exact wording)\n"
        "1. The caller sounds **angry, frustrated, upset, sarcastic, or\n"
        "   raises their voice** — even subtly. Trust your read of the tone.\n"
        "2. The caller wants to speak to a **human, person, manager,\n"
        "   supervisor, or anyone other than an AI**. Any language, any\n"
        "   phrasing — the EXACT WORDS DO NOT MATTER. 'I want a manager',\n"
        "   'أبغى أحكي مع المدير', 'is there a real person?', 'human please',\n"
        "   'أحكي مع بشر', 'put me through to someone' — all the same request.\n"
        "3. The caller is **repeating the same request and not getting\n"
        "   what they need**, or you've said the same thing 3+ times.\n"
        "4. The caller mentions a **medical emergency you cannot triage**.\n"
        "5. The caller **threatens to file a complaint** or contact regulators.\n"
        "6. You **feel stuck** — multiple tool errors, the situation is\n"
        "   beyond what your tools can resolve, or continuing would only\n"
        "   make things worse.\n"
    )
    if kw_en or kw_ar or scen:
        escalation_block += (
            "\n### Operator-provided hints (illustrative, NOT a closed list)\n"
            "These are examples of what to watch for, written by the operations\n"
            "team. Use them as hints — rely on the SITUATION, not exact matches.\n"
        )
        if kw_en:
            escalation_block += "- Example English phrasings: " + ", ".join(f'"{w}"' for w in kw_en) + "\n"
        if kw_ar:
            escalation_block += "- Example Arabic phrasings: " + ", ".join(f'"{w}"' for w in kw_ar) + "\n"
        if scen:
            escalation_block += "- Scenarios flagged by operations:\n"
            for s in scen:
                escalation_block += f"  · {s}\n"
    escalation_block += (
        "\n### How to call it\n"
        "- `reason` = one short sentence the supervisor will read on the\n"
        "  Dashboard. Be specific: 'Caller asked for manager twice (angry)'.\n"
        "- `severity` = 'high' for anger, complaints, emergencies, threats\n"
        "  to escalate. 'normal' otherwise.\n"
        "- **Re-flag every time a trigger occurs again.** If a supervisor\n"
        "  acknowledged your earlier flag and the caller is again asking\n"
        "  for the manager or remains angry, FLAG AGAIN. Multiple flags on\n"
        "  the same call signal escalating urgency and are NEVER spam.\n"
        "  Treat each occurrence as fresh — never reason 'I already\n"
        "  flagged this'.\n"
    )

    return (
        f"{load_persona().strip()}"
        f"{_GUARDRAILS}\n\n"
        f"{load_kb().strip()}"
        f"{_build_roster_block()}"
        f"{current}"
        f"{escalation_block}"
    )


# ============================================================================
# CallSession — one TCP connection from Asterisk = one call = one Gemini session
# ============================================================================

class CallSession:
    def __init__(
        self, call_id: str, peer: str,
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
        svc: "ClinicLiveAgentService",
    ) -> None:
        self.call_id = call_id
        self.peer = peer
        self.reader = reader
        self.writer = writer
        self.svc = svc
        self.uuid: Optional[str] = None
        self.started_at = time.time()
        # Caller -> Gemini (16 kHz mono PCM after upsample)
        self.audio_in: asyncio.Queue = asyncio.Queue(maxsize=200)
        # Gemini -> Caller (24 kHz mono PCM, downsampled in the write loop)
        self.audio_out: asyncio.Queue = asyncio.Queue(maxsize=200)
        self.stop_evt = asyncio.Event()
        self._upstate = None
        self._downstate = None
        self._out_leftover: bytes = b""
        self._next_send_at: Optional[float] = None
        self.echo_until: float = 0.0
        self.heard_text = ""
        self.spoken_text = ""
        # Persistent per-call recording state — flushed to disk in
        # ClinicLiveAgentService._handle's finally block via _save_recording.
        # Caller frames arrive continuously over AudioSocket (one every 20 ms),
        # so concatenating them yields a perfect wall-clock timeline of what
        # the caller sent. Agent chunks are intermittent (Gemini only emits
        # while it's actually speaking) so we tag each chunk with the
        # seconds-since-call-start offset at which it left the wire, so the
        # mixer can overlay it at the right position.
        self._caller_pcm8k: list[bytes] = []
        self._agent_pcm8k:  list[tuple[float, bytes]] = []
        self.turns: list[dict] = []   # [{role, text, ts}]
        # ---- Fabrication detector state ---------------------------------
        # Whitelist of identifiers actually returned by successful tool
        # calls on THIS call. Anything the agent SPEAKS that matches an
        # identifier pattern but isn't in here is a fabrication, and we
        # send a correction to the model immediately.
        self._issued_file_numbers:    set[str] = set()
        self._issued_appointment_ids: set[str] = set()
        self._issued_patient_ids:     set[str] = set()
        # Times (HH:MM, 24-hour) that list_free_slots actually returned
        # at some point on this call. The detector cross-references any
        # clock-time the agent SPEAKS against this set — catches the
        # "agent offered 6:30 PM when the clinic closes at 5" failure.
        self._issued_slot_times:      set[str] = set()
        # Identifiers we've already nagged the model about — prevents
        # us from spamming corrections every chunk while the agent
        # repeats the same fabricated value mid-sentence.
        self._corrected_ids:          set[str] = set()
        self._corrected_times:        set[str] = set()
        # Optional caller phone — populated if the dialplan ever passes
        # CALLERID via an out-of-band channel (TODO; see DEMOSITEMAP).
        self.caller_phone: Optional[str] = None
        # Supervisor flag — non-None when the agent (or auto-detect)
        # has raised this call for a human to take over. Snapshots
        # include it so a Dashboard that connects after the flag was
        # raised still sees the red row. Cleared by ack_flag().
        self.active_flag: Optional[dict] = None

    # ----- supervisor flag plumbing ------------------------------------
    def set_flag(self, flag: dict) -> None:
        """Mark this call as needing supervisor attention. Broadcasts
        a `supervisor_flag` event AND persists on the session so that
        Dashboards that connect later (via snapshot) see the flag too.
        Re-flagging overwrites — operator sees the latest reason."""
        payload = {
            "reason":   str(flag.get("reason") or "").strip() or "(no reason given)",
            "severity": (flag.get("severity") or "normal").strip().lower(),
            "source":   flag.get("source") or "agent",
            "ts":       time.time(),
        }
        if payload["severity"] not in ("low", "normal", "high"):
            payload["severity"] = "normal"
        self.active_flag = payload
        self.svc._broadcast({
            "type":    "supervisor_flag",
            "call_id": self.call_id,
            "flag":    payload,
        })

    def ack_flag(self) -> bool:
        """Operator-side acknowledgement. Returns True if there was a
        flag to clear, False otherwise."""
        if self.active_flag is None:
            return False
        self.active_flag = None
        self.svc._broadcast({
            "type":    "supervisor_flag_ack",
            "call_id": self.call_id,
        })
        return True

    async def _check_fabrications(self, session) -> None:
        """Scan the agent's accumulated transcribed speech for
        identifier patterns (file_number, appointment_id) and, for any
        match NOT in our per-call whitelist of tool-issued IDs, inject
        a correction back into the Gemini Live session AND broadcast a
        warning so the dashboard surfaces the silent failure."""
        fabricated: list[tuple[str, str]] = []  # [(kind, normalised_id), ...]

        for m in _FILE_PATTERN.finditer(self.spoken_text):
            # Recompose the id without the whitespace/hyphens the
            # transcription may have inserted between digits.
            raw = m.group(0)
            normalised = re.sub(r"[\s\-]", "", raw).upper()
            if len(normalised) != 7:
                continue
            if normalised in self._issued_file_numbers: continue
            if normalised in self._corrected_ids:       continue
            self._corrected_ids.add(normalised)
            fabricated.append(("file_number", normalised))

        for m in _APT_PATTERN.finditer(self.spoken_text):
            raw = m.group(0)
            normalised = re.sub(r"[\s\-]", "-", raw).upper()
            # Normalise to APT-NNN form.
            digits = re.sub(r"\D", "", normalised)
            if not digits: continue
            canonical = f"APT-{digits}"
            if canonical in self._issued_appointment_ids: continue
            if canonical in self._corrected_ids:          continue
            self._corrected_ids.add(canonical)
            fabricated.append(("appointment_id", canonical))

        # Clock times the agent SPOKE — we only check these once we have
        # at least one set of slots from list_free_slots / appointment
        # lookups to compare against. Without that whitelist we can't
        # tell legit recall from invention (mentioning the current time,
        # for example, should not trigger a warning).
        if self._issued_slot_times:
            # Each spoken time match becomes a SET of plausible
            # interpretations. A bare "4:30" with no AM/PM marker is
            # ambiguous — the agent very likely meant 16:30 (clinics
            # operate afternoons) but the transcription dropped the
            # "PM". So we accept the match if ANY interpretation
            # matches the whitelist. Previously the strict-24h read
            # produced a false positive that told the agent to apologise
            # for a booking that actually succeeded.
            spoken_candidates: list[set[str]] = []
            for m in _TIME_AMPM.finditer(self.spoken_text):
                h = int(m.group(1))
                mins = int(m.group(2) or 0)
                ampm = m.group(3).lower()
                if ampm == "p" and h < 12: h += 12
                if ampm == "a" and h == 12: h = 0
                if h > 23: continue
                # AM/PM explicit → single interpretation.
                spoken_candidates.append({f"{h:02d}:{mins:02d}"})
            for m in _TIME_24H.finditer(self.spoken_text):
                h = int(m.group(1)); mins = int(m.group(2))
                options = {f"{h:02d}:{mins:02d}"}
                if h < 12:
                    options.add(f"{h + 12:02d}:{mins:02d}")
                spoken_candidates.append(options)

            def _within_15(a: str, b: str) -> bool:
                ah, am = int(a[:2]), int(a[3:])
                bh, bm = int(b[:2]), int(b[3:])
                return abs((ah * 60 + am) - (bh * 60 + bm)) <= 15

            for options in spoken_candidates:
                accepted = False
                for t in options:
                    if t in self._issued_slot_times:
                        accepted = True
                        break
                    if any(_within_15(t, real) for real in self._issued_slot_times):
                        accepted = True
                        break
                if accepted:
                    continue
                # Pick the primary (sorted) interpretation for the warning.
                primary = sorted(options)[0]
                if primary in self._corrected_times: continue
                self._corrected_times.add(primary)
                fabricated.append(("slot_time", primary))

        if not fabricated:
            return

        for kind, ident in fabricated:
            logger.warning(
                "clinic call %s: fabrication detected — agent spoke %s '%s' "
                "that was never returned by a tool on this call",
                self.call_id, kind, ident,
            )
            self.svc._broadcast({
                "type":     "fabrication",
                "call_id":  self.call_id,
                "kind":     kind,
                "value":    ident,
            })

        # Build a single concise correction prompt — sending many in
        # quick succession just confuses the model.
        bullets = "\n".join(
            f"- You said {kind} '{ident}' — no tool returned that value."
            for kind, ident in fabricated
        )
        correction = (
            "(system override) STOP. You just spoke an identifier you "
            "did NOT receive from any tool on this call:\n"
            f"{bullets}\n"
            "That is fabrication. The caller's record was NOT actually "
            "created. Right now you must either:\n"
            "  (a) call the correct tool (create_patient / "
            "create_appointment) with the data you've collected so far, "
            "OR\n"
            "  (b) apologise to the caller in their language, tell them "
            "the system did not save the record, and ask reception to "
            "complete it on arrival.\n"
            "Do NOT repeat the fabricated value. Do NOT pretend the "
            "previous statement was correct."
        )
        try:
            await session.send_client_content(
                turns=types.Content(role="user", parts=[types.Part(text=correction)]),
                turn_complete=True,
            )
        except Exception:
            logger.exception("clinic call %s: failed to send fabrication correction",
                             self.call_id)

    def _append_turn(self, role: str, text: str) -> None:
        # Extend the last turn if the speaker hasn't switched, else start a
        # new one — keeps the transcript readable and the file small.
        if self.turns and self.turns[-1]["role"] == role:
            self.turns[-1]["text"] += text
        else:
            self.turns.append({"role": role, "text": text, "ts": time.time()})

    # ---- wire protocol -----------------------------------------------------
    @staticmethod
    async def _read_frame(reader: asyncio.StreamReader) -> tuple[int, bytes]:
        header = await reader.readexactly(3)
        msg_type = header[0]
        length = struct.unpack(">H", header[1:3])[0]
        payload = await reader.readexactly(length) if length else b""
        return msg_type, payload

    async def _send_audio(self, pcm8k: bytes) -> None:
        FRAME = 320  # 20 ms @ 8 kHz, 16-bit mono
        n_frames = len(pcm8k) // FRAME
        if n_frames == 0:
            return
        self.echo_until = max(
            self.echo_until, time.time() + n_frames * 0.020 + 0.35,
        )
        now = time.monotonic()
        if self._next_send_at is None or self._next_send_at < now - 0.05:
            self._next_send_at = now
        for i in range(0, len(pcm8k), FRAME):
            chunk = pcm8k[i:i + FRAME]
            self.writer.write(bytes([_AS_AUDIO]) + struct.pack(">H", len(chunk)) + chunk)
            await self.writer.drain()
            self._next_send_at += 0.020
            delay = self._next_send_at - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            else:
                await asyncio.sleep(0)

    async def _hangup(self) -> None:
        try:
            self.writer.write(bytes([_AS_HANGUP, 0, 0]))
            await self.writer.drain()
        except Exception:
            pass

    async def _delayed_stop(self, delay_s: float) -> None:
        """Set stop_evt after a short delay — used by the end_call tool so
        the agent's spoken goodbye actually leaves the wire before we
        tear down the AudioSocket."""
        try:
            await asyncio.sleep(delay_s)
        finally:
            self.stop_evt.set()

    # ---- pumps -------------------------------------------------------------
    async def _read_loop(self) -> None:
        try:
            while not self.stop_evt.is_set():
                msg_type, payload = await self._read_frame(self.reader)
                if msg_type == _AS_HANGUP:
                    logger.info("clinic call %s: peer hangup", self.call_id)
                    self.stop_evt.set()
                    return
                if msg_type == _AS_UUID:
                    self.uuid = payload.hex()
                    continue
                if msg_type == _AS_DTMF:
                    digit = payload.decode("ascii", "replace") if payload else ""
                    logger.info("clinic call %s: DTMF %s", self.call_id, digit)
                    continue
                if msg_type == _AS_ERROR:
                    logger.warning("clinic call %s: peer error: %r", self.call_id, payload)
                    continue
                if msg_type == _AS_AUDIO and payload:
                    # Capture the raw 8 kHz caller frame before any
                    # resampling — recording stays lossless.
                    self._caller_pcm8k.append(payload)
                    # Half-duplex echo gate — always active. Caller audio is
                    # dropped for ~350ms past the end of the agent's last
                    # outgoing frame, regardless of interruption mode. The
                    # gate window is short enough that real barge-in still
                    # works (the caller's *next* syllable lands as soon as
                    # the agent stops talking), but blocks the agent's own
                    # voice from echoing back through speakerphone/weak
                    # echo-cancellation paths and (a) triggering Gemini's
                    # VAD into self-interrupting mid-sentence (caused 10s
                    # voice freezes) and (b) feeding garbage into
                    # input_transcription (caused weird/garbled words).
                    if time.time() < self.echo_until:
                        continue
                    pcm16k, self._upstate = audioop.ratecv(
                        payload, _SAMPLE_WIDTH, 1, 8000, 16000, self._upstate,
                    )
                    try:
                        self.audio_in.put_nowait(pcm16k)
                    except asyncio.QueueFull:
                        try: self.audio_in.get_nowait()
                        except Exception: pass
                        try: self.audio_in.put_nowait(pcm16k)
                        except Exception: pass
        except (asyncio.IncompleteReadError, ConnectionResetError):
            pass
        except Exception:
            logger.exception("clinic call %s: read loop crashed", self.call_id)
        finally:
            # Always signal — same reason as _write_loop's finally.
            self.stop_evt.set()

    async def _write_loop(self) -> None:
        FRAME = 320
        try:
            while not self.stop_evt.is_set():
                try:
                    pcm24k = await asyncio.wait_for(self.audio_out.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue
                pcm8k, self._downstate = audioop.ratecv(
                    pcm24k, _SAMPLE_WIDTH, 1, 24000, 8000, self._downstate,
                )
                if not pcm8k:
                    continue
                buf = self._out_leftover + pcm8k
                n_complete = (len(buf) // FRAME) * FRAME
                if n_complete:
                    # Capture what we actually sent to the caller, in the
                    # same 8 kHz wire format — recording is the call as
                    # the caller heard it. Stamp with seconds-since-call-start
                    # so the mixer can place it at the right offset on the
                    # caller timeline.
                    offset_s = time.time() - self.started_at
                    chunk = buf[:n_complete]
                    self._agent_pcm8k.append((offset_s, chunk))
                    await self._send_audio(chunk)
                self._out_leftover = buf[n_complete:]
        except Exception as e:
            logger.warning("clinic call %s: write loop ended: %s", self.call_id, e)
        finally:
            # The transport may have died before the read loop noticed
            # (e.g. Asterisk closed TCP without sending an AudioSocket
            # HANGUP frame, or wrote() raised on a half-closed socket).
            # If we don't signal stop_evt, run() stays parked on
            # `await self.stop_evt.wait()` and the whole call session
            # never finalises — Gemini eventually closes the WS idle,
            # and we accumulate zombie sessions.
            self.stop_evt.set()

    async def _gemini_loop(self) -> None:
        if not state.gemini_api_key:
            logger.error("clinic call %s: Gemini API key not set", self.call_id)
            return
        model = state.gemini_model
        client = genai.Client(
            api_key=state.gemini_api_key,
            http_options={"api_version": _GEMINI_API_VERSION},
        )

        # Per-call context that tool implementations close over. Lets a
        # tool set `end_requested = True` to terminate the call, or call
        # `broadcast(event)` to push something to subscribers.
        tool_ctx: dict = {
            "call_id":        self.call_id,
            "broadcast":      self.svc._broadcast,
            "end_requested":  False,
            # Exposed so `flag_for_supervisor` can mutate the session
            # state + broadcast in one shot (see CallSession.set_flag).
            "set_flag":       self.set_flag,
        }

        cfg = types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            system_instruction=types.Content(
                parts=[types.Part(text=_build_system_instruction())],
            ),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=state.cda_voice or "Aoede",
                    ),
                ),
            ),
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            # Barge-in: LOW start-of-speech sensitivity so faint echo /
            # breathing / line noise can't be mis-classified as speech and
            # cause the agent to self-interrupt (the 10-second voice freeze
            # symptom). Real caller speech still triggers reliably; the
            # always-on echo gate above is belt to LOW's braces.
            realtime_input_config=types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(
                    disabled=not bool(state.cda_interruption_enabled),
                    start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_LOW,
                    end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_HIGH,
                    silence_duration_ms=600,
                    prefix_padding_ms=200,
                ),
            ),
            tools=build_tools(),
        )

        try:
            async with client.aio.live.connect(model=model, config=cfg) as session:
                logger.info("clinic call %s: Gemini Live connected (model=%s)", self.call_id, model)

                if state.cda_greeting:
                    try:
                        await session.send_client_content(
                            turns=types.Content(role="user", parts=[
                                types.Part(text=f"(system) Greet the caller now with: {state.cda_greeting}")
                            ]),
                            turn_complete=True,
                        )
                    except Exception as e:
                        logger.warning("clinic call %s: greeting failed: %s", self.call_id, e)

                async def feed():
                    try:
                        while not self.stop_evt.is_set():
                            try:
                                chunk = await asyncio.wait_for(self.audio_in.get(), timeout=1.0)
                            except asyncio.TimeoutError:
                                continue
                            if not chunk:
                                continue
                            await session.send_realtime_input(
                                audio=types.Blob(data=chunk, mime_type="audio/pcm;rate=16000"),
                            )
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        # Swallow Gemini's "WS already closed" once the
                        # session is winding down; we don't want it to
                        # propagate as an unretrieved task exception.
                        logger.info("clinic call %s: feed loop ended: %r",
                                    self.call_id, e)
                    finally:
                        self.stop_evt.set()

                async def receive():
                    try:
                        while not self.stop_evt.is_set():
                            async for resp in session.receive():
                                data_bytes = getattr(resp, "data", None)
                                if data_bytes:
                                    try: self.audio_out.put_nowait(data_bytes)
                                    except asyncio.QueueFull:
                                        try: self.audio_out.get_nowait()
                                        except Exception: pass
                                        try: self.audio_out.put_nowait(data_bytes)
                                        except Exception: pass
                                sc = getattr(resp, "server_content", None)
                                if sc:
                                    if getattr(sc, "interrupted", False):
                                        drained = 0
                                        while not self.audio_out.empty():
                                            try:
                                                self.audio_out.get_nowait()
                                                drained += 1
                                            except Exception: break
                                        self._out_leftover = b""
                                        self.echo_until = 0.0
                                        if drained:
                                            logger.info("clinic call %s: interrupted (%d frames dropped)", self.call_id, drained)
                                    it = getattr(sc, "input_transcription", None)
                                    if it and getattr(it, "text", None):
                                        self.heard_text += it.text
                                        self._append_turn("caller", it.text)
                                        self.svc._broadcast({
                                            "type": "transcript", "call_id": self.call_id,
                                            "who": "caller", "text": it.text,
                                        })
                                    ot = getattr(sc, "output_transcription", None)
                                    if ot and getattr(ot, "text", None):
                                        self.spoken_text += ot.text
                                        self._append_turn("agent", ot.text)
                                        self.svc._broadcast({
                                            "type": "transcript", "call_id": self.call_id,
                                            "who": "agent", "text": ot.text,
                                        })
                                        # Fabrication check — scan everything
                                        # the agent has said so far against
                                        # the whitelist of IDs returned by
                                        # tools on this call. The model's
                                        # transcription may chunk the ID
                                        # across messages, so we re-scan the
                                        # full spoken_text each time.
                                        await self._check_fabrications(session)
                                # Tool call → execute → return FunctionResponse.
                                tc = getattr(resp, "tool_call", None)
                                if tc:
                                    responses = []
                                    for fc in (tc.function_calls or []):
                                        args = dict(fc.args or {})
                                        logger.info("clinic call %s: tool_call %s(%s)",
                                                    self.call_id, fc.name, args)
                                        self.svc._broadcast({
                                            "type":     "tool_call",
                                            "call_id":  self.call_id,
                                            "name":     fc.name,
                                            "args":     args,
                                        })
                                        # If the lookup succeeded, update the
                                        # Dashboard's caller name + phone.
                                        result = execute_tool(fc.name, args, tool_ctx)
                                        # Always broadcast the outcome so the
                                        # Dashboard can flag tool errors
                                        # (e.g. create_appointment failing with
                                        # "patient not found") instead of the
                                        # user only finding out when the
                                        # appointment doesn't appear.
                                        has_error = isinstance(result, dict) and bool(result.get("error"))
                                        self.svc._broadcast({
                                            "type":     "tool_result",
                                            "call_id":  self.call_id,
                                            "name":     fc.name,
                                            "args":     args,
                                            "ok":       (not has_error),
                                            "error":    (result.get("error") if has_error else None),
                                            "result":   None if has_error else result,
                                        })
                                        # Whitelist any IDs the tool actually issued
                                        # on this call so the fabrication detector
                                        # knows they're real.
                                        if not has_error and isinstance(result, dict):
                                            fn = result.get("file_number")
                                            if fn: self._issued_file_numbers.add(str(fn))
                                            aid = result.get("appointment_id")
                                            if aid: self._issued_appointment_ids.add(str(aid))
                                            pid = result.get("patient_id")
                                            if pid: self._issued_patient_ids.add(str(pid))
                                            # Lookups return the patient under "patient"
                                            sub = result.get("patient")
                                            if isinstance(sub, dict):
                                                if sub.get("file_number"):
                                                    self._issued_file_numbers.add(str(sub["file_number"]))
                                                if sub.get("patient_id"):
                                                    self._issued_patient_ids.add(str(sub["patient_id"]))
                                            # list_free_slots → every free HH:MM
                                            # returned, across every clinic, into
                                            # the slot whitelist.
                                            for c in (result.get("clinics") or []):
                                                for slot in (c.get("free_slots") or []):
                                                    self._issued_slot_times.add(str(slot))
                                            # list_patient_appointments → existing
                                            # appointment times are legit too.
                                            for a in (result.get("appointments") or []):
                                                t = a.get("time")
                                                if t: self._issued_slot_times.add(str(t))
                                            # Single-appointment results.
                                            t = result.get("time")
                                            if t: self._issued_slot_times.add(str(t))
                                        if fc.name.startswith("lookup_patient") and isinstance(result, dict) and result.get("found"):
                                            p = result.get("patient") or {}
                                            self.caller_phone = p.get("phone") or self.caller_phone
                                            self.svc._broadcast({
                                                "type":    "caller_identified",
                                                "call_id": self.call_id,
                                                "name":    p.get("name") or p.get("name_ar"),
                                                "phone":   p.get("phone"),
                                            })
                                        responses.append(types.FunctionResponse(
                                            id=fc.id, name=fc.name,
                                            response={"result": result},
                                        ))
                                    if responses:
                                        try:
                                            await session.send_tool_response(function_responses=responses)
                                        except Exception:
                                            logger.exception("send_tool_response failed")
                                    # If a tool requested hangup, drop out cleanly
                                    # after the agent's closing line finishes.
                                    if tool_ctx.get("end_requested"):
                                        # Give the agent ~3s to finish its
                                        # spoken goodbye before we close the
                                        # AudioSocket.
                                        asyncio.create_task(self._delayed_stop(3.0))
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        # Gemini's WS closes with ConnectionClosedOK at the
                        # end of a normal call — don't escalate, just log
                        # and signal the rest of the pipeline to shut down.
                        logger.info("clinic call %s: receive loop ended: %r",
                                    self.call_id, e)
                    finally:
                        self.stop_evt.set()

                feeder = asyncio.create_task(feed())
                receiver = asyncio.create_task(receive())
                stopper = asyncio.create_task(self.stop_evt.wait())
                done, pending = await asyncio.wait(
                    {feeder, receiver, stopper},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for t in pending:
                    t.cancel()
                # Drain results from completed tasks so their exceptions
                # don't surface as "Task exception was never retrieved".
                for t in done:
                    try: t.exception()
                    except (asyncio.CancelledError, asyncio.InvalidStateError):
                        pass

        except Exception:
            logger.exception("clinic call %s: Gemini Live failed", self.call_id)

    async def run(self) -> None:
        max_s = max(60, int(state.cda_max_call_s or 900))
        async def deadline():
            await asyncio.sleep(max_s)
            logger.info("clinic call %s: hit max duration %ds", self.call_id, max_s)
            self.stop_evt.set()
        tasks = [
            asyncio.create_task(self._read_loop()),
            asyncio.create_task(self._write_loop()),
            asyncio.create_task(self._gemini_loop()),
            asyncio.create_task(deadline()),
        ]
        try:
            await self.stop_evt.wait()
        finally:
            for t in tasks:
                t.cancel()
            await self._hangup()


# ============================================================================
# Service — TCP listener + per-call dispatch + tiny pub/sub bus
# ============================================================================

class ClinicLiveAgentService:
    def __init__(self) -> None:
        self._server: Optional[asyncio.AbstractServer] = None
        self._task: Optional[asyncio.Task] = None
        self._calls: dict[str, CallSession] = {}
        self._subs: set[asyncio.Queue] = set()
        self.last_error: Optional[str] = None
        self.bound_at: Optional[float] = None

    # ----- subscriber bus -----
    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)

    def _broadcast(self, payload: dict) -> None:
        for q in list(self._subs):
            try: q.put_nowait(payload)
            except asyncio.QueueFull:
                try: q.get_nowait()
                except Exception: pass
                try: q.put_nowait(payload)
                except Exception: pass

    # ----- lifecycle -----
    def status(self) -> dict:
        return {
            "running":    self._server is not None,
            "enabled":    bool(state.cda_enabled),
            "host":       state.cda_bind_host,
            "port":       state.cda_bind_port,
            "active":     len(self._calls),
            "bound_at":   self.bound_at,
            "last_error": self.last_error,
        }

    def active_calls(self) -> list[dict]:
        return [
            {
                "call_id":    c.call_id,
                "peer":       c.peer,
                "uuid":       c.uuid,
                "started_at": c.started_at,
                "duration_s": int(time.time() - c.started_at),
                "heard":      c.heard_text[-400:],
                "spoken":     c.spoken_text[-400:],
                # Replayed on (re)connect so dashboards that came online
                # AFTER a supervisor flag was raised still see the red row.
                "flag":       c.active_flag,
            }
            for c in self._calls.values()
        ]

    def get_call(self, call_id: str) -> Optional[CallSession]:
        """Look up a live CallSession by id — used by the router's
        acknowledge_flag endpoint."""
        return self._calls.get(call_id)

    def apply_config(self) -> None:
        """Idempotent — call after edits to cda_enabled / host / port."""
        if state.cda_enabled and self._server is None:
            self.start()
        elif (not state.cda_enabled) and self._server is not None:
            asyncio.create_task(self.stop())
        elif self._server is not None:
            sock = next(iter(self._server.sockets or []), None)
            if sock:
                cur_host, cur_port = sock.getsockname()[:2]
                if cur_port != int(state.cda_bind_port) or cur_host != state.cda_bind_host:
                    asyncio.create_task(self._restart())

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._run(), name="clinic-live-agent")

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            try: await self._server.wait_closed()
            except Exception: pass
            self._server = None
            self.bound_at = None
        for c in list(self._calls.values()):
            c.stop_evt.set()
        self._calls.clear()
        if self._task:
            self._task.cancel()
            self._task = None

    async def _restart(self) -> None:
        await self.stop()
        await asyncio.sleep(0.1)
        self.start()

    async def _run(self) -> None:
        host = state.cda_bind_host or "0.0.0.0"
        port = int(state.cda_bind_port or 8092)
        try:
            self._server = await asyncio.start_server(self._handle, host, port)
            self.bound_at = time.time()
            self.last_error = None
            logger.info("ClinicLiveAgent listening on %s:%d", host, port)
            async with self._server:
                await self._server.serve_forever()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
            logger.exception("ClinicLiveAgent bind/run failed")

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        peer_label = f"{peer[0]}:{peer[1]}" if peer else "unknown"
        call_id = uuid.uuid4().hex[:10]
        session = CallSession(call_id, peer_label, reader, writer, self)
        self._calls[call_id] = session
        logger.info("ClinicLiveAgent: new call %s from %s", call_id, peer_label)
        self._broadcast({"type": "call_started", "call_id": call_id, "peer": peer_label, "started_at": session.started_at})
        try:
            await session.run()
        except Exception:
            logger.exception("clinic call %s crashed", call_id)
        finally:
            self._calls.pop(call_id, None)
            # Persist the call's recording + transcript to disk so the
            # History page can replay it. Always best-effort — a failing
            # save must never block the cleanup.
            try:
                saved_id = _save_recording(session)
                self._broadcast({"type": "call_ended", "call_id": call_id,
                                 "saved_call_id": saved_id})
                # Kick off the offline transcript pass — runs in the
                # background so the next call (or hangup) isn't blocked
                # by the Gemini upload.
                if saved_id:
                    asyncio.create_task(_enhance_transcript(saved_id))
            except Exception:
                logger.exception("clinic call %s: failed to save recording", call_id)
                self._broadcast({"type": "call_ended", "call_id": call_id})
            try: writer.close()
            except Exception: pass


# ============================================================================
# Call persistence — WAV (caller + agent) + JSON transcript
# ============================================================================

def _write_wav(path: Path, frames: list[bytes], rate_hz: int = 8000) -> None:
    """Write a list of signed-linear 16-bit mono PCM byte chunks as a WAV."""
    if not frames:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate_hz)
        w.writeframes(b"".join(frames))


def _write_agent_wav(path: Path,
                     agent_chunks: list[tuple[float, bytes]],
                     total_s: float,
                     rate_hz: int = 8000) -> None:
    """Render the agent-only timeline as a full-call WAV — silence between
    the chunks, audio inside them — so the reader hears the agent talk in
    real call time, not back-to-back."""
    if not agent_chunks:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    bytes_per_sec = rate_hz * 2  # 16-bit mono
    last = agent_chunks[-1]
    span_s = max(total_s, last[0] + (len(last[1]) / bytes_per_sec))
    total_bytes = int(span_s * bytes_per_sec)
    if total_bytes <= 0:
        return
    buf = bytearray(total_bytes)
    for offset_s, chunk in agent_chunks:
        start = int(offset_s * bytes_per_sec) & ~1  # align to sample boundary
        end = start + len(chunk)
        if end > len(buf):
            buf.extend(b"\x00" * (end - len(buf)))
        buf[start:end] = chunk
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate_hz)
        w.writeframes(bytes(buf))


def _write_mixed_wav(path: Path,
                     caller_frames: list[bytes],
                     agent_chunks: list[tuple[float, bytes]],
                     total_s: float,
                     rate_hz: int = 8000) -> None:
    """Overlay the agent timeline on top of the caller timeline at the
    correct offsets, sample-by-sample (audioop.add). Produces a single
    'as the room sounded' WAV — perfect for listening back and for
    feeding a single audio stream to the offline transcript model."""
    bytes_per_sec = rate_hz * 2  # 16-bit mono
    caller_bytes = b"".join(caller_frames)
    span_s = total_s
    if agent_chunks:
        last = agent_chunks[-1]
        span_s = max(span_s, last[0] + (len(last[1]) / bytes_per_sec))
    span_s = max(span_s, len(caller_bytes) / bytes_per_sec)
    total_bytes = int(span_s * bytes_per_sec)
    if total_bytes <= 0:
        return
    path.parent.mkdir(parents=True, exist_ok=True)

    mixed = bytearray(total_bytes)
    # Lay the caller down first.
    n = min(len(caller_bytes), total_bytes)
    mixed[:n] = caller_bytes[:n]
    # Then add the agent chunks on top.
    for offset_s, chunk in agent_chunks:
        start = int(offset_s * bytes_per_sec) & ~1
        end = start + len(chunk)
        if end > len(mixed):
            mixed.extend(b"\x00" * (end - len(mixed)))
        existing = bytes(mixed[start:end])
        if len(existing) < len(chunk):
            existing = existing + b"\x00" * (len(chunk) - len(existing))
        try:
            summed = audioop.add(existing, chunk, 2)
        except audioop.error:
            summed = chunk
        mixed[start:start + len(summed)] = summed
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate_hz)
        w.writeframes(bytes(mixed))


def _save_recording(session: CallSession) -> Optional[str]:
    """Persist the just-ended call. Returns the storage id used on disk —
    a sortable timestamp + short uid so the History page lists in time order
    even when the underlying call_ids are random hex.

    Layout under data/demos/clinic/calls/<dir>/ :
        meta.json    — { call_id, started_at, ended_at, duration_s,
                         peer, uuid, caller_phone, persona_chars,
                         kb_chars, turns: [{role, text, ts}] }
        caller.wav   — 8 kHz mono, what the caller said
        agent.wav    — 8 kHz mono, what the agent said (post-resample)
    """
    if (
        not session.turns
        and not session._caller_pcm8k
        and not session._agent_pcm8k
    ):
        # Empty call (no audio, no transcript) — usually a probe / failed
        # handshake. Skip to keep the History clean.
        return None

    ended_at = time.time()
    started_at = session.started_at
    duration_s = max(0.0, ended_at - started_at)
    ts = time.strftime("%Y%m%dT%H%M%S", time.localtime(started_at))
    dir_id = f"{ts}_{session.call_id}"
    call_dir = _CALLS_DIR / dir_id

    try:
        _write_wav(call_dir / "caller.wav", session._caller_pcm8k)
    except Exception:
        logger.exception("write caller.wav failed")
    try:
        _write_agent_wav(call_dir / "agent.wav", session._agent_pcm8k, duration_s)
    except Exception:
        logger.exception("write agent.wav failed")
    try:
        _write_mixed_wav(call_dir / "mixed.wav", session._caller_pcm8k,
                         session._agent_pcm8k, duration_s)
    except Exception:
        logger.exception("write mixed.wav failed")

    meta = {
        "id":            dir_id,
        "call_id":       session.call_id,
        "started_at":    started_at,
        "ended_at":      ended_at,
        "duration_s":    int(duration_s),
        "peer":          session.peer,
        "uuid":          session.uuid,
        "caller_phone":  session.caller_phone,
        "turns":         list(session.turns),
        "enhanced_turns": None,           # filled in by background task
        "enhanced_status": "pending",     # pending → running → done | failed
        "persona_chars": len(load_persona()),
        "kb_chars":      len(load_kb()),
        "voice":         state.cda_voice or "Aoede",
    }
    try:
        call_dir.mkdir(parents=True, exist_ok=True)
        (call_dir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        logger.exception("write meta.json failed")

    return dir_id


def list_saved_calls(limit: int = 100) -> list[dict]:
    """Return saved-call summaries (newest first)."""
    if not _CALLS_DIR.exists():
        return []
    rows: list[dict] = []
    for call_dir in _CALLS_DIR.iterdir():
        if not call_dir.is_dir():
            continue
        meta_path = call_dir / "meta.json"
        if not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        rows.append({
            "id":           meta.get("id") or call_dir.name,
            "call_id":      meta.get("call_id"),
            "started_at":   meta.get("started_at"),
            "ended_at":     meta.get("ended_at"),
            "duration_s":   meta.get("duration_s", 0),
            "peer":         meta.get("peer"),
            "caller_phone": meta.get("caller_phone"),
            "turn_count":   len(meta.get("turns") or []),
            "enhanced_status":     meta.get("enhanced_status") or (
                "done" if meta.get("enhanced_turns") else "pending"
            ),
            "enhanced_turn_count": len(meta.get("enhanced_turns") or []),
            "has_caller_wav": (call_dir / "caller.wav").exists(),
            "has_agent_wav":  (call_dir / "agent.wav").exists(),
            "has_mixed_wav":  (call_dir / "mixed.wav").exists(),
        })
    rows.sort(key=lambda r: r.get("started_at") or 0, reverse=True)
    return rows[:limit]


def load_saved_call(call_id: str) -> Optional[dict]:
    """Return the full meta.json for one saved call, or None."""
    call_dir = _CALLS_DIR / call_id
    meta_path = call_dir / "meta.json"
    if not meta_path.exists():
        return None
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def call_audio_path(call_id: str, side: str) -> Optional[Path]:
    """Resolve the WAV path for one side ('caller', 'agent', or 'mixed').
    Returns None if the file doesn't exist — caller should 404."""
    if side not in ("caller", "agent", "mixed"):
        return None
    p = _CALLS_DIR / call_id / f"{side}.wav"
    return p if p.exists() else None


# ============================================================================
# Offline transcript enhancement — Gemini "audio understanding"
# ============================================================================
# Gemini Live's live transcription is approximate and sometimes mis-renders
# the Arabic / English mix. After the call ends we re-transcribe the mixed
# WAV with a non-Live Gemini model (response_schema = list of turns) and
# patch meta.json with `enhanced_turns`. The History page prefers that
# field when it's present and falls back to the live transcript otherwise.

_ENHANCE_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
]


def _patch_meta(call_dir: Path, patch: dict) -> None:
    meta_path = call_dir / "meta.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return
    meta.update(patch)
    try:
        meta_path.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        logger.exception("patch meta.json failed for %s", call_dir.name)


async def _enhance_transcript(call_dir_id: str) -> None:
    """Re-transcribe mixed.wav with Gemini offline and store the result
    on disk as `enhanced_turns`. Best-effort — never raises."""
    call_dir = _CALLS_DIR / call_dir_id
    mixed_path = call_dir / "mixed.wav"
    if not mixed_path.exists():
        _patch_meta(call_dir, {"enhanced_status": "failed",
                               "enhanced_error": "mixed.wav missing"})
        return
    if not state.gemini_api_key:
        _patch_meta(call_dir, {"enhanced_status": "failed",
                               "enhanced_error": "Gemini API key not set"})
        return

    _patch_meta(call_dir, {"enhanced_status": "running"})
    try:
        wav_bytes = mixed_path.read_bytes()
        client = genai.Client(api_key=state.gemini_api_key)
        audio_part = types.Part.from_bytes(
            data=wav_bytes, mime_type="audio/wav",
        )
        prompt = (
            "This is a phone-call recording between a Saudi clinic "
            "receptionist named Layla (الوكيل / agent — usually Arabic, "
            "may switch to English) and a caller (المتصل / caller). "
            "Produce an accurate, faithful transcript as a JSON array of "
            "turns in the order they were spoken. Each turn object has "
            "two keys:\n"
            "  - role: \"agent\" or \"caller\"\n"
            "  - text: what was actually said, preserving the original "
            "language (Arabic stays Arabic, English stays English). Do "
            "NOT translate. Do NOT paraphrase. Do NOT add commentary.\n"
            "Merge consecutive utterances from the same speaker. Skip "
            "silence, breathing, and DTMF tones. If a section is "
            "unintelligible, write [unintelligible] for that turn's text."
        )
        schema = types.Schema(
            type=types.Type.ARRAY,
            items=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "role": types.Schema(
                        type=types.Type.STRING,
                        enum=["agent", "caller"],
                    ),
                    "text": types.Schema(type=types.Type.STRING),
                },
                required=["role", "text"],
            ),
        )
        cfg = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema,
        )

        last_err: Optional[Exception] = None
        text: Optional[str] = None
        for model in _ENHANCE_MODELS:
            try:
                resp = await client.aio.models.generate_content(
                    model=model,
                    contents=[audio_part, prompt],
                    config=cfg,
                )
                text = getattr(resp, "text", None)
                if text:
                    break
            except Exception as e:
                last_err = e
                logger.warning("enhance %s: model %s failed: %s",
                               call_dir_id, model, e)
                continue
        if not text:
            raise last_err or RuntimeError("no model returned text")

        turns = json.loads(text)
        if not isinstance(turns, list):
            raise ValueError("model output is not a JSON array")
        clean: list[dict] = []
        for t in turns:
            if not isinstance(t, dict): continue
            role = str(t.get("role") or "").strip().lower()
            body = str(t.get("text") or "").strip()
            if role not in ("agent", "caller") or not body:
                continue
            clean.append({"role": role, "text": body})

        _patch_meta(call_dir, {
            "enhanced_turns":  clean,
            "enhanced_status": "done",
            "enhanced_error":  None,
        })
        logger.info("enhance %s: stored %d turns", call_dir_id, len(clean))
    except Exception as e:
        logger.exception("enhance %s failed", call_dir_id)
        _patch_meta(call_dir, {
            "enhanced_status": "failed",
            "enhanced_error":  f"{type(e).__name__}: {e}",
        })


def delete_saved_call(call_id: str) -> bool:
    """Wipe one saved call's directory. Returns True if anything was
    removed."""
    call_dir = _CALLS_DIR / call_id
    if not call_dir.exists():
        return False
    for f in call_dir.iterdir():
        try: f.unlink()
        except Exception: pass
    try: call_dir.rmdir()
    except Exception: pass
    return True


clinic_live_agent_service = ClinicLiveAgentService()
