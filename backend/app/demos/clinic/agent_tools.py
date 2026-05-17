"""
Clinic Live Agent — function-call tools + data snapshot.

The clinic data layer lives in the Clinic SPA (localStorage) — the
SPA's Dashboard pushes a snapshot to `POST /api/demo/clinic/data/snapshot`
on mount + after every mutation, and the backend writes it to
`data/demos/clinic/snapshot.json`. Tool calls then read/mutate that
snapshot file directly.

Tools exposed to Gemini Live:
  - lookup_patient_by_phone(phone)
  - lookup_patient_by_id_number(id_number)
  - lookup_patient_by_file_number(file_number)
  - list_free_slots(date, clinic_id?)
  - create_patient(name, name_ar?, phone, id_number, date_of_birth,
                   gender, city?)
  - create_appointment(patient_id, clinic_id, date, time,
                       duration_min?, reason?)
  - end_call(reason)

When a tool MUTATES (create_*), it also broadcasts a `tool_mutation`
event on the service's pub/sub bus so the Dashboard (and the SPA's
localStorage) can mirror the change immediately.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from google.genai import types

logger = logging.getLogger("clinic_agent_tools")

# Snapshot location — matches live_agent.py's _DATA_DIR.
_DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "demos" / "clinic"
_SNAPSHOT_PATH = _DATA_DIR / "snapshot.json"

# Booking buffer — don't offer today-slots within this many minutes of now.
BOOKING_BUFFER_MIN = 15
SLOT_MIN = 30  # matches the SPA's SLOT_MINUTES


# ============================================================================
# Snapshot read/write
# ============================================================================

def _empty_snapshot() -> dict:
    return {
        "patients":      [],
        "appointments":  [],
        "clinics":       [],
        "providers":     [],
        "slot_overrides": [],
        "updated_at":    None,
    }


def load_snapshot() -> dict:
    if not _SNAPSHOT_PATH.exists():
        return _empty_snapshot()
    try:
        return json.loads(_SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("snapshot.json corrupt")
        return _empty_snapshot()


def save_snapshot(snap: dict) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    snap["updated_at"] = datetime.utcnow().isoformat() + "Z"
    tmp = _SNAPSHOT_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_SNAPSHOT_PATH)


# ============================================================================
# Helpers
# ============================================================================

_DIGITS = re.compile(r"\D+")

def _normalize_phone(s: str) -> str:
    """Strip everything but digits. '+966 50 234 5678' → '966502345678'."""
    return _DIGITS.sub("", s or "")


def _phones_equal(a: str, b: str) -> bool:
    """Match phones loosely — last 9 digits is enough to handle ±country code."""
    na, nb = _normalize_phone(a), _normalize_phone(b)
    if not na or not nb:
        return False
    if na == nb: return True
    # Saudi country code 966 plus 9-digit national → match on last 9
    if len(na) >= 9 and len(nb) >= 9 and na[-9:] == nb[-9:]:
        return True
    return False


def _next_id(existing: list[dict], prefix: str, width: int = 4) -> str:
    max_n = 0
    pat = re.compile(rf"^{prefix}-(\d+)$")
    for x in existing:
        m = pat.match(str(x.get("id") or ""))
        if m:
            max_n = max(max_n, int(m.group(1)))
    return f"{prefix}-{str(max_n + 1).zfill(width)}"


def _next_file_number(patients: list[dict]) -> str:
    """File # is letter A/B/C + 6 digits, first digit 1-9."""
    used = {p.get("file_number") for p in patients}
    letters = ["A", "B", "C"]
    li = (len(used) // 800_000) % 3
    for _ in range(10000):
        # deterministic-ish: bump a counter, wrap letters
        n = (len(used) % 800_000) + 1
        rest = str(n).zfill(5)
        candidate = f"{letters[li]}{1 + (n % 9)}{rest}"
        if candidate not in used:
            return candidate
        li = (li + 1) % 3
        used.add(candidate)  # force a different pick next loop
    # fallback
    return f"A100000"


def _weekday_index(date_str: str) -> int:
    y, m, d = (int(x) for x in date_str.split("-"))
    # Match the SPA's weekdayOf: 0 = Sunday … 6 = Saturday
    return datetime(y, m - 1 + 1, d).weekday() if False else _sunday_indexed(y, m, d)


def _sunday_indexed(y: int, m: int, d: int) -> int:
    """Python's Monday=0; the SPA's weekdayOf is Sunday=0. Convert."""
    py = datetime(y, m, d).weekday()  # Mon=0..Sun=6
    return (py + 1) % 7  # → Sun=0..Sat=6


def _default_working_hours_for_weekday(idx: int) -> dict:
    """Fallback when a clinic has no `working_hours` in the snapshot — same
    Saudi-clinic-week default the SPA seeds with."""
    common = {"open": True,  "open_time": "09:00", "close_time": "17:00",
              "break_enabled": True, "break_start": "13:00", "break_end": "14:00"}
    if idx == 5:  # Friday
        return {"open": False, "open_time": "09:00", "close_time": "17:00",
                "break_enabled": False, "break_start": "13:00", "break_end": "14:00"}
    if idx == 6:  # Saturday
        return {"open": True,  "open_time": "09:00", "close_time": "13:00",
                "break_enabled": False, "break_start": "12:00", "break_end": "13:00"}
    return common


def _time_to_min(t: str) -> int:
    h, m = (int(x) for x in t.split(":"))
    return h * 60 + m


def _min_to_time(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def _slots_for_day(hours: dict) -> list[str]:
    if not hours.get("open"):
        return []
    start = _time_to_min(hours.get("open_time", "09:00"))
    end   = _time_to_min(hours.get("close_time", "17:00"))
    out = []
    for m in range(start, end - SLOT_MIN + 1, SLOT_MIN):
        out.append(_min_to_time(m))
    return out


def _is_break(slot: str, hours: dict) -> bool:
    if not hours.get("break_enabled"):
        return False
    s = _time_to_min(slot)
    return _time_to_min(hours["break_start"]) <= s < _time_to_min(hours["break_end"])


def _booked_slots(appointments: list[dict], date: str, clinic_id: str) -> set[str]:
    out: set[str] = set()
    for a in appointments:
        if a.get("status") in ("cancelled", "no_show"):
            continue
        if a.get("department_id") != clinic_id:
            continue
        sched = a.get("scheduled_at", "")
        if sched[:10] != date:
            continue
        start_min = _time_to_min(sched[11:16])
        duration = int(a.get("duration_min") or SLOT_MIN)
        end_min = start_min + duration
        first = (start_min // SLOT_MIN) * SLOT_MIN
        for m in range(first, end_min, SLOT_MIN):
            out.add(_min_to_time(m))
    return out


def _blocked_slots(overrides: list[dict], date: str, clinic_id: str) -> set[str]:
    out: set[str] = set()
    for o in overrides:
        if o.get("department_id") == clinic_id and o.get("date") == date:
            for s in o.get("blocked_slots", []) or []:
                out.add(s)
    return out


# ============================================================================
# Tool declarations for Gemini Live
# ============================================================================

def build_tools() -> list[types.Tool]:
    """Single Tool with every function declaration we expose."""
    decls: list[types.FunctionDeclaration] = [
        types.FunctionDeclaration(
            name="lookup_patient_by_phone",
            description="Look up a patient by mobile phone number. Returns "
                        "patient details if a unique match is found, otherwise null. "
                        "Phone matching ignores formatting and accepts Saudi numbers "
                        "with or without country code (+966 / 966 / 0).",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={"phone": types.Schema(type=types.Type.STRING)},
                required=["phone"],
            ),
        ),
        types.FunctionDeclaration(
            name="lookup_patient_by_id_number",
            description="Look up a patient by national / Iqama ID number (10 digits, "
                        "starts with 1 for Saudi nationals or 2 for residents).",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={"id_number": types.Schema(type=types.Type.STRING)},
                required=["id_number"],
            ),
        ),
        types.FunctionDeclaration(
            name="lookup_patient_by_file_number",
            description="Look up a patient by clinic file number (format: letter "
                        "A/B/C followed by 6 digits, e.g. 'A123456').",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={"file_number": types.Schema(type=types.Type.STRING)},
                required=["file_number"],
            ),
        ),
        types.FunctionDeclaration(
            name="list_free_slots",
            description="List available appointment slot start times for one "
                        "clinic on one date. Already filters past times and slots "
                        "within 15 minutes of the current time. Returns a list of "
                        "'HH:MM' strings.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "date":       types.Schema(type=types.Type.STRING,
                                               description="YYYY-MM-DD"),
                    "clinic_id":  types.Schema(type=types.Type.STRING,
                                               description="Department ID like DEP-001. "
                                                           "If omitted, all clinics are returned."),
                },
                required=["date"],
            ),
        ),
        types.FunctionDeclaration(
            name="create_patient",
            description="Create a new patient file. Returns the assigned patient_id "
                        "and file_number. Use AFTER collecting all required fields.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "name":          types.Schema(type=types.Type.STRING),
                    "name_ar":       types.Schema(type=types.Type.STRING),
                    "phone":         types.Schema(type=types.Type.STRING),
                    "id_number":     types.Schema(type=types.Type.STRING),
                    "date_of_birth": types.Schema(type=types.Type.STRING,
                                                  description="YYYY-MM-DD"),
                    "gender":        types.Schema(type=types.Type.STRING,
                                                  description="'male' or 'female'"),
                    "city":          types.Schema(type=types.Type.STRING),
                    "city_ar":       types.Schema(type=types.Type.STRING),
                },
                required=["name", "phone", "id_number", "date_of_birth", "gender"],
            ),
        ),
        types.FunctionDeclaration(
            name="create_appointment",
            description="Book an appointment. Use AFTER the caller confirms a slot. "
                        "Returns the appointment_id and the confirmed date/time.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "patient_id":   types.Schema(type=types.Type.STRING),
                    "clinic_id":    types.Schema(type=types.Type.STRING),
                    "date":         types.Schema(type=types.Type.STRING,
                                                 description="YYYY-MM-DD"),
                    "time":         types.Schema(type=types.Type.STRING,
                                                 description="HH:MM"),
                    "duration_min": types.Schema(type=types.Type.INTEGER),
                    "notes":        types.Schema(type=types.Type.STRING),
                },
                required=["patient_id", "clinic_id", "date", "time"],
            ),
        ),
        types.FunctionDeclaration(
            name="end_call",
            description="Hang up the call. Use after the caller says goodbye and "
                        "you've spoken your closing line.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={"reason": types.Schema(type=types.Type.STRING)},
                required=["reason"],
            ),
        ),
    ]
    return [types.Tool(function_declarations=decls)]


# ============================================================================
# Tool implementations — invoked from CallSession.receive() on tool_call
# ============================================================================

def execute_tool(name: str, args: dict, ctx: dict) -> dict:
    """Dispatch a Gemini function call. `ctx` is the call's context dict;
    we use it to set `end_requested = True` for end_call, and to expose
    a `broadcast(event)` callable for tool_mutation events.
    """
    try:
        if name == "lookup_patient_by_phone":
            return _t_lookup_phone(args.get("phone") or "")
        if name == "lookup_patient_by_id_number":
            return _t_lookup_id(args.get("id_number") or "")
        if name == "lookup_patient_by_file_number":
            return _t_lookup_file(args.get("file_number") or "")
        if name == "list_free_slots":
            return _t_list_free_slots(args.get("date") or "", args.get("clinic_id"))
        if name == "create_patient":
            return _t_create_patient(args, ctx)
        if name == "create_appointment":
            return _t_create_appointment(args, ctx)
        if name == "end_call":
            return _t_end_call(args.get("reason") or "", ctx)
        return {"error": f"unknown tool: {name}"}
    except Exception as e:
        logger.exception("tool %s failed", name)
        return {"error": f"{type(e).__name__}: {e}"}


def _patient_for_agent(p: dict) -> dict:
    """Trim the patient record to fields the agent should actually use —
    keeps responses compact and avoids leaking internals."""
    return {
        "patient_id":     p.get("id"),
        "file_number":    p.get("file_number"),
        "name":           p.get("name"),
        "name_ar":        p.get("name_ar"),
        "id_number":      p.get("id_number"),
        "phone":          p.get("phone"),
        "date_of_birth":  p.get("date_of_birth"),
        "gender":         p.get("gender"),
        "city":           p.get("city"),
    }


def _t_lookup_phone(phone: str) -> dict:
    snap = load_snapshot()
    for p in snap.get("patients", []):
        if _phones_equal(p.get("phone", ""), phone):
            return {"found": True, "patient": _patient_for_agent(p)}
    return {"found": False, "patient": None}


def _t_lookup_id(id_number: str) -> dict:
    target = _DIGITS.sub("", id_number or "")
    snap = load_snapshot()
    for p in snap.get("patients", []):
        if _DIGITS.sub("", str(p.get("id_number") or "")) == target:
            return {"found": True, "patient": _patient_for_agent(p)}
    return {"found": False, "patient": None}


def _t_lookup_file(file_number: str) -> dict:
    target = (file_number or "").strip().upper()
    snap = load_snapshot()
    for p in snap.get("patients", []):
        if (p.get("file_number") or "").upper() == target:
            return {"found": True, "patient": _patient_for_agent(p)}
    return {"found": False, "patient": None}


def _t_list_free_slots(date: str, clinic_id: Optional[str]) -> dict:
    if not date or len(date) != 10:
        return {"error": "date must be YYYY-MM-DD"}
    snap = load_snapshot()
    clinics = snap.get("clinics", [])
    appts = snap.get("appointments", [])
    overrides = snap.get("slot_overrides", [])

    now = datetime.now()
    today_ymd = now.strftime("%Y-%m-%d")
    is_today = (date == today_ymd)
    earliest = now + timedelta(minutes=BOOKING_BUFFER_MIN)

    # Past date → no slots, ever.
    if date < today_ymd:
        return {"date": date, "clinics": [], "note": "Date is in the past."}

    wd = _sunday_indexed(*(int(x) for x in date.split("-")))
    target_clinics = [c for c in clinics
                      if (clinic_id is None or c.get("id") == clinic_id)]

    out_clinics: list[dict] = []
    for c in target_clinics:
        hours = (c.get("working_hours") or
                 [None]*7)
        if isinstance(hours, list) and len(hours) == 7:
            day = hours[wd] or _default_working_hours_for_weekday(wd)
        else:
            day = _default_working_hours_for_weekday(wd)
        all_slots = _slots_for_day(day)
        if not all_slots:
            out_clinics.append({
                "clinic_id":    c.get("id"),
                "clinic_name":  c.get("name"),
                "free_slots":   [],
                "note":         "Clinic closed on this day.",
            })
            continue
        booked = _booked_slots(appts, date, c.get("id"))
        blocked = _blocked_slots(overrides, date, c.get("id"))
        free: list[str] = []
        for s in all_slots:
            if _is_break(s, day): continue
            if s in booked or s in blocked: continue
            if is_today:
                slot_dt = datetime(*(int(x) for x in date.split("-")),
                                   _time_to_min(s) // 60, _time_to_min(s) % 60)
                if slot_dt < earliest:
                    continue
            free.append(s)
        out_clinics.append({
            "clinic_id":    c.get("id"),
            "clinic_name":  c.get("name"),
            "specialty":    c.get("specialty"),
            "free_slots":   free,
        })
    return {
        "date":   date,
        "is_today": is_today,
        "now":    now.strftime("%H:%M"),
        "buffer_minutes": BOOKING_BUFFER_MIN if is_today else 0,
        "clinics": out_clinics,
    }


_FILE_PATTERN = re.compile(r"^[A-C][1-9]\d{5}$")
_ID_PATTERN   = re.compile(r"^[12]\d{9}$")


def _t_create_patient(args: dict, ctx: dict) -> dict:
    snap = load_snapshot()
    patients = snap.get("patients", [])

    name = (args.get("name") or "").strip()
    phone = (args.get("phone") or "").strip()
    id_number = re.sub(r"\D", "", args.get("id_number") or "")
    dob = (args.get("date_of_birth") or "").strip()
    gender = (args.get("gender") or "").strip().lower()

    if not name or not phone or not dob or gender not in ("male", "female"):
        return {"error": "Missing required field (name, phone, date_of_birth, gender)"}
    if not _ID_PATTERN.match(id_number):
        return {"error": "id_number must be 10 digits starting with 1 (Saudi) or 2 (resident)"}

    new_id = _next_id(patients, "PAT")
    file_number = _next_file_number(patients)
    today = datetime.now().strftime("%Y-%m-%d")
    record = {
        "id":             new_id,
        "file_number":    file_number,
        "id_number":      id_number,
        "name":           name,
        "name_ar":        (args.get("name_ar") or "").strip(),
        "gender":         gender,
        "date_of_birth":  dob,
        "phone":          phone,
        "email":          "",
        "city":           (args.get("city") or "").strip(),
        "city_ar":        (args.get("city_ar") or "").strip(),
        "registration_date":   today,
        "registration_source": "live_agent",
        "notes":          "Created during live agent call.",
    }
    patients.append(record)
    snap["patients"] = patients
    save_snapshot(snap)

    broadcast = ctx.get("broadcast")
    if callable(broadcast):
        broadcast({
            "type":    "tool_mutation",
            "call_id": ctx.get("call_id"),
            "kind":    "patient_created",
            "patient": record,
        })

    return {
        "ok":           True,
        "patient_id":   new_id,
        "file_number":  file_number,
        "name":         name,
    }


def _t_create_appointment(args: dict, ctx: dict) -> dict:
    snap = load_snapshot()
    patients = snap.get("patients", [])
    clinics = snap.get("clinics", [])
    appts = snap.get("appointments", [])
    overrides = snap.get("slot_overrides", [])

    patient_id = args.get("patient_id")
    clinic_id = args.get("clinic_id")
    date = args.get("date")
    time_str = args.get("time")
    duration = int(args.get("duration_min") or SLOT_MIN)
    notes = (args.get("notes") or "").strip()

    if not (patient_id and clinic_id and date and time_str):
        return {"error": "patient_id, clinic_id, date, time are required"}

    patient = next((p for p in patients if p.get("id") == patient_id), None)
    if patient is None:
        return {"error": f"patient {patient_id} not found"}
    clinic = next((c for c in clinics if c.get("id") == clinic_id), None)
    if clinic is None:
        return {"error": f"clinic {clinic_id} not found"}

    # Re-verify the slot is actually free + future + outside the buffer.
    now = datetime.now()
    today_ymd = now.strftime("%Y-%m-%d")
    if date < today_ymd:
        return {"error": "cannot book an appointment in the past"}
    slot_dt = datetime(*(int(x) for x in date.split("-")),
                       _time_to_min(time_str) // 60, _time_to_min(time_str) % 60)
    if date == today_ymd and slot_dt < now + timedelta(minutes=BOOKING_BUFFER_MIN):
        return {"error": f"slot is within the {BOOKING_BUFFER_MIN}-minute booking buffer"}

    wd = _sunday_indexed(*(int(x) for x in date.split("-")))
    hours_list = clinic.get("working_hours")
    if isinstance(hours_list, list) and len(hours_list) == 7:
        day = hours_list[wd] or _default_working_hours_for_weekday(wd)
    else:
        day = _default_working_hours_for_weekday(wd)
    if not day.get("open"):
        return {"error": "clinic is closed on this day"}
    if _is_break(time_str, day):
        return {"error": "slot falls inside the clinic's break window"}

    booked = _booked_slots(appts, date, clinic_id)
    blocked = _blocked_slots(overrides, date, clinic_id)
    if time_str in booked: return {"error": "slot is already booked"}
    if time_str in blocked: return {"error": "slot is blocked by the clinic"}

    new_id = _next_id(appts, "APT")
    scheduled = f"{date}T{time_str}:00.000"
    record = {
        "id":              new_id,
        "patient_id":      patient.get("id"),
        "patient_name":    patient.get("name"),
        "patient_name_ar": patient.get("name_ar"),
        "patient_phone":   patient.get("phone"),
        "department_id":   clinic_id,
        "provider_id":     None,
        "scheduled_at":    scheduled,
        "duration_min":    duration,
        "status":          "scheduled",
        "notes":           notes or "Created by Live Agent",
    }
    appts.append(record)
    snap["appointments"] = appts
    save_snapshot(snap)

    broadcast = ctx.get("broadcast")
    if callable(broadcast):
        broadcast({
            "type":        "tool_mutation",
            "call_id":     ctx.get("call_id"),
            "kind":        "appointment_created",
            "appointment": record,
        })

    return {
        "ok":             True,
        "appointment_id": new_id,
        "date":           date,
        "time":           time_str,
        "duration_min":   duration,
        "clinic_name":    clinic.get("name"),
        "patient_name":   patient.get("name"),
    }


def _t_end_call(reason: str, ctx: dict) -> dict:
    ctx["end_requested"] = True
    logger.info("clinic call %s: end_call requested — reason: %s",
                ctx.get("call_id"), reason or "(none)")
    return {"ok": True, "reason": reason}
