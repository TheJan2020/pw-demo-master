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
import struct
import time
import uuid
import wave
from pathlib import Path
from typing import Optional

from google import genai
from google.genai import types

from ...core.state import state
from .agent_tools import build_tools, execute_tool

logger = logging.getLogger("clinic_live_agent")

# AudioSocket framing — identical wire protocol to chan_audiosocket.
_AS_HANGUP = 0x00
_AS_UUID   = 0x01
_AS_DTMF   = 0x02
_AS_ERROR  = 0x03
_AS_AUDIO  = 0x10

_SAMPLE_WIDTH = 2  # signed-linear 16-bit
_GEMINI_API_VERSION = "v1alpha"

# On-disk overrides — the Clinic SPA's KB / Persona pages POST here via
# /api/demo/clinic/agent/prompt. Service rereads per call so the user
# doesn't need to restart anything.
_DATA_DIR = Path(__file__).resolve().parents[4] / "data" / "demos" / "clinic"
_PERSONA_PATH = _DATA_DIR / "persona.txt"
_KB_PATH      = _DATA_DIR / "kb.txt"
_CALLS_DIR    = _DATA_DIR / "calls"


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
- Any slot, doctor, price, or policy you didn't see in the
  Knowledge Base or receive from a tool result.

## Tools — use them, don't fake them
You have function tools — always call them, never invent data:
- lookup_patient_by_phone(phone)
- lookup_patient_by_id_number(id_number)
- lookup_patient_by_file_number(file_number)
- list_free_slots(date, clinic_id=null) — already filters past times
  and the 15-min booking buffer
- create_patient(...) — call once after collecting required fields
- create_appointment(patient_id, clinic_id, date, time) — call once
  after the caller confirms the slot
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


def _build_system_instruction() -> str:
    # Inject the current date + time so the agent never has to invent a
    # weekday or wonder whether 11:00 "today" has already passed. This
    # block is regenerated on every inbound call.
    now = time.localtime()
    weekday_en = ["Sunday", "Monday", "Tuesday", "Wednesday",
                  "Thursday", "Friday", "Saturday"][(now.tm_wday + 1) % 7]
    weekday_ar = ["الأحد", "الإثنين", "الثلاثاء", "الأربعاء",
                  "الخميس", "الجمعة", "السبت"][(now.tm_wday + 1) % 7]
    current = (
        "\n\n## CURRENT TIME (authoritative — do not invent a different day)\n"
        f"- Today: {time.strftime('%Y-%m-%d', now)} ({weekday_en} / {weekday_ar})\n"
        f"- Right now: {time.strftime('%H:%M', now)} ({time.tzname[0]})\n"
        "- When referring to today say 'اليوم' / 'today' — never the\n"
        "  weekday name on its own.\n"
        "- The `list_free_slots` tool already filters past times and any\n"
        "  slot within the 15-minute booking buffer. Quote ONLY what it\n"
        "  returns."
    )
    return f"{load_persona().strip()}\n\n{load_kb().strip()}{current}"


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
        # We store raw 8 kHz signed-linear from both directions so the WAVs
        # round-trip without resampling losses.
        self._caller_pcm8k: list[bytes] = []
        self._agent_pcm8k:  list[bytes] = []
        self.turns: list[dict] = []   # [{role, text, ts}]
        # Optional caller phone — populated if the dialplan ever passes
        # CALLERID via an out-of-band channel (TODO; see DEMOSITEMAP).
        self.caller_phone: Optional[str] = None

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
                    # Half-duplex gate only when interruption is OFF (mirrors
                    # the fix landed for sip_live_rep — see its comments).
                    if not state.cda_interruption_enabled and time.time() < self.echo_until:
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
            self.stop_evt.set()
        except Exception:
            logger.exception("clinic call %s: read loop crashed", self.call_id)
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
                    # the caller heard it.
                    self._agent_pcm8k.append(buf[:n_complete])
                    await self._send_audio(buf[:n_complete])
                self._out_leftover = buf[n_complete:]
        except Exception as e:
            logger.warning("clinic call %s: write loop ended: %s", self.call_id, e)

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
            realtime_input_config=types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(
                    disabled=not bool(state.cda_interruption_enabled),
                    start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_HIGH,
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

                async def receive():
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

                feeder = asyncio.create_task(feed())
                receiver = asyncio.create_task(receive())
                done, pending = await asyncio.wait(
                    {feeder, receiver, asyncio.create_task(self.stop_evt.wait())},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for t in pending:
                    t.cancel()

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
            }
            for c in self._calls.values()
        ]

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
    ts = time.strftime("%Y%m%dT%H%M%S", time.localtime(started_at))
    dir_id = f"{ts}_{session.call_id}"
    call_dir = _CALLS_DIR / dir_id

    try:
        _write_wav(call_dir / "caller.wav", session._caller_pcm8k)
    except Exception:
        logger.exception("write caller.wav failed")
    try:
        _write_wav(call_dir / "agent.wav", session._agent_pcm8k)
    except Exception:
        logger.exception("write agent.wav failed")

    meta = {
        "id":            dir_id,
        "call_id":       session.call_id,
        "started_at":    started_at,
        "ended_at":      ended_at,
        "duration_s":    int(ended_at - started_at),
        "peer":          session.peer,
        "uuid":          session.uuid,
        "caller_phone":  session.caller_phone,
        "turns":         list(session.turns),
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
            "has_caller_wav": (call_dir / "caller.wav").exists(),
            "has_agent_wav":  (call_dir / "agent.wav").exists(),
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
    """Resolve the WAV path for one side ('caller' or 'agent'). Returns
    None if the file doesn't exist — caller should 404."""
    if side not in ("caller", "agent"):
        return None
    p = _CALLS_DIR / call_id / f"{side}.wav"
    return p if p.exists() else None


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
