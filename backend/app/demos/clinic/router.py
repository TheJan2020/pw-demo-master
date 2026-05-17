"""Clinic demo backend — login, current-user, logout, and the Live Agent
control plane (config + persona/KB publish + status). The AudioSocket
service itself lives in demos.clinic.live_agent."""
from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel
import asyncio

from ...core.state import state
from . import config
from .live_agent import (
    clinic_live_agent_service,
    load_kb, load_persona, save_kb, save_persona,
    load_escalation_config, save_escalation_config,
    list_saved_calls, load_saved_call, call_audio_path, delete_saved_call,
)
from .ami import AMIService, AMICredentials
from .wasender import build_client as build_wasender_client
from .agent_tools import load_snapshot, save_snapshot
from ..auth import (
    clear_session,
    issue_session,
    require_session,
)

logger = logging.getLogger("demo_clinic")
router = APIRouter()

_SLUG = config.SLUG


# ============================================================================
# Login / session
# ============================================================================

class LoginIn(BaseModel):
    username: str
    password: str


@router.post("/login")
async def login(body: LoginIn, response: Response) -> dict:
    if body.username == config.DEMO_USERNAME and body.password == config.DEMO_PASSWORD:
        issue_session(response, _SLUG, body.username)
        return {"ok": True, "user": {"username": body.username,
                                     "display_name": config.DISPLAY_NAME}}
    raise HTTPException(401, "Invalid credentials")


@router.get("/me")
async def me(request: Request) -> dict:
    sess = require_session(request, _SLUG)
    return {"username": sess["username"], "display_name": config.DISPLAY_NAME}


@router.post("/logout")
async def logout(request: Request, response: Response) -> dict:
    clear_session(request, response, _SLUG)
    return {"ok": True}


# ============================================================================
# Live Agent — config + prompt publish + status + activity WS
# ============================================================================

class AgentConfigIn(BaseModel):
    enabled:              Optional[bool] = None
    bind_host:            Optional[str] = None
    bind_port:            Optional[int] = None
    voice:                Optional[str] = None
    greeting:             Optional[str] = None
    max_call_s:           Optional[int] = None
    interruption_enabled: Optional[bool] = None


class AgentConfigOut(BaseModel):
    enabled:              bool
    bind_host:            str
    bind_port:            int
    voice:                str
    greeting:             str
    max_call_s:           int
    interruption_enabled: bool


def _current_agent_config() -> AgentConfigOut:
    return AgentConfigOut(
        enabled=bool(state.cda_enabled),
        bind_host=state.cda_bind_host or "0.0.0.0",
        bind_port=int(state.cda_bind_port or 8092),
        voice=state.cda_voice or "Aoede",
        greeting=state.cda_greeting or "",
        max_call_s=int(state.cda_max_call_s or 0),
        interruption_enabled=bool(state.cda_interruption_enabled),
    )


@router.get("/agent/config", response_model=AgentConfigOut)
async def agent_get_config() -> AgentConfigOut:
    return _current_agent_config()


@router.post("/agent/config", response_model=AgentConfigOut)
async def agent_set_config(payload: AgentConfigIn) -> AgentConfigOut:
    if payload.enabled              is not None: state.cda_enabled = bool(payload.enabled)
    if payload.bind_host            is not None: state.cda_bind_host = (payload.bind_host or "0.0.0.0").strip() or "0.0.0.0"
    if payload.bind_port            is not None: state.cda_bind_port = max(1, min(65535, int(payload.bind_port)))
    if payload.voice                is not None: state.cda_voice = (payload.voice or "Aoede").strip() or "Aoede"
    if payload.greeting             is not None: state.cda_greeting = payload.greeting or ""
    if payload.max_call_s           is not None: state.cda_max_call_s = max(0, int(payload.max_call_s))
    if payload.interruption_enabled is not None: state.cda_interruption_enabled = bool(payload.interruption_enabled)
    state.save()
    clinic_live_agent_service.apply_config()
    return _current_agent_config()


@router.get("/agent/status")
async def agent_status() -> dict:
    s = clinic_live_agent_service.status()
    return {
        **s,
        "calls":          clinic_live_agent_service.active_calls(),
        "persona_chars":  len(load_persona()),
        "kb_chars":       len(load_kb()),
        "api_key_set":    bool(state.gemini_api_key),
    }


class PromptIn(BaseModel):
    persona: Optional[str] = None
    kb:      Optional[str] = None


@router.get("/agent/prompt")
async def agent_get_prompt() -> dict:
    return {"persona": load_persona(), "kb": load_kb()}


@router.post("/agent/prompt")
async def agent_set_prompt(payload: PromptIn) -> dict:
    """Persist persona / KB to data/demos/clinic/{persona,kb}.txt. Service
    re-reads on every call so the next inbound dial picks up the change
    with no restart needed."""
    if payload.persona is not None: save_persona(payload.persona)
    if payload.kb      is not None: save_kb(payload.kb)
    return {"ok": True, "persona": load_persona(), "kb": load_kb()}


# ----- Supervisor escalation (red-flag) ------------------------------------

@router.get("/agent/escalation")
async def agent_get_escalation() -> dict:
    """Return the operator-editable escalation triggers: keywords (EN/AR),
    free-text scenarios, and auto-detect tunables. Read by the
    Configuration page; also injected into the live persona on every
    new inbound call."""
    return load_escalation_config()


@router.post("/agent/escalation")
async def agent_set_escalation(payload: dict) -> dict:
    """Partial update — merges `payload` into the saved config and
    returns the resulting full config. Unknown keys are ignored; the
    service re-reads from disk on every inbound call so the next dial
    picks up the change with no restart."""
    if not isinstance(payload, dict):
        raise HTTPException(400, "escalation config must be a JSON object")
    return save_escalation_config(payload)


@router.post("/agent/calls/{call_id}/acknowledge_flag")
async def agent_ack_flag(call_id: str) -> dict:
    """Operator clicks the Acknowledge button on a flagged row →
    clears the flag and broadcasts a supervisor_flag_ack event so
    every other dashboard instance drops the red tint in sync."""
    call = clinic_live_agent_service.get_call(call_id)
    if call is None:
        raise HTTPException(404, "call not found or already ended")
    if not call.ack_flag():
        return {"ok": True, "noop": True}
    return {"ok": True}


# ----- AMI-backed supervisor dial-in ----------------------------------------
# Operator clicks the "Ext. 1003" button on a live-call row. We issue an
# AMI Originate so Asterisk rings the supervisor's extension — no softphone
# `tel:` handler, no copy/paste. AMI credentials come from escalation.json
# (editable from Call Center → Configuration → PBX integration).

def _load_ami_credentials() -> AMICredentials:
    cfg = load_escalation_config()
    return AMICredentials(
        host=str(cfg.get("ami_host") or "").strip(),
        port=int(cfg.get("ami_port") or 5038),
        username=str(cfg.get("ami_username") or "").strip(),
        secret=str(cfg.get("ami_secret") or "").strip(),
    )


_ami_service = AMIService(_load_ami_credentials)


@router.post("/agent/calls/{call_id}/dial_supervisor")
async def agent_dial_supervisor(call_id: str, mode: str = "barge") -> dict:
    """Trigger an AMI Originate to ring the configured supervisor
    extension and drop them into the live call via ChanSpy.

    `mode` query param picks the audio policy:
      - listen  : silent monitor
      - whisper : talk to the caller only (AI doesn't hear)
      - barge   : 3-way (default — supervisor talks to caller + AI)

    Reads AMI host / username / secret / port + supervisor_extension
    from escalation.json on every call so edits from the Configuration
    page take effect with no restart."""
    call = clinic_live_agent_service.get_call(call_id)
    if call is None:
        raise HTTPException(404, "call not found or already ended")
    cfg = load_escalation_config()
    extension = str(cfg.get("supervisor_extension") or "").strip()
    result = await _ami_service.dial_supervisor(call_id, extension, spy_mode=mode)
    # 200 with ok=False on AMI failure so the UI can show the message
    # without spawning a network-error toast — body carries the detail.
    return result


# ----- WhatsApp via WasenderApi --------------------------------------------
# Per-machine API key lives in escalation.json (gitignored). Reads on every
# request so editing in Call Center → Configuration takes effect with no
# restart. See backend/app/demos/clinic/wasender.py for the wrapper.

class WhatsAppSendIn(BaseModel):
    to:   str    # any reasonable phone-number shape — the wrapper normalises
    text: str


@router.get("/whatsapp/status")
async def whatsapp_status() -> dict:
    """Lightweight key-validity ping. The SPA pings this on page load
    so the operator sees 'connected' / 'not configured' / 'error: …'
    without sending a real message. Returns:
      {configured: bool, ok: bool, status: int, error?: str, contact_count?: int}
    """
    api_key = str(load_escalation_config().get("wasender_api_key") or "").strip()
    if not api_key:
        return {"configured": False, "ok": False, "status": 0,
                "error": "WhatsApp API key not configured"}
    client = build_wasender_client(api_key)
    result = await client.ping()
    return {"configured": True, **result}


@router.post("/whatsapp/send")
async def whatsapp_send(payload: WhatsAppSendIn) -> dict:
    """Send a WhatsApp text via WasenderApi. The API key comes from
    escalation.json (set on Call Center → Configuration). Returns
    {ok, message_id?, status, error?, raw}. 200 with ok=False on any
    upstream failure so the UI can display the message in-band."""
    if not (payload.text or "").strip():
        raise HTTPException(400, "text is required")
    if not (payload.to or "").strip():
        raise HTTPException(400, "to is required")
    api_key = str(load_escalation_config().get("wasender_api_key") or "").strip()
    client = build_wasender_client(api_key)
    return await client.send_text(payload.to, payload.text)


# Inbox endpoints — both go through WasenderApi message-logs and group
# the response client-side. /chats lists conversations (one row per
# JID); /messages?jid=… returns the timeline for a single conversation.

def _msg_jid(m: dict) -> str:
    """Pick the chat-key (remoteJid) from a message-log row. WasenderApi
    has used `remoteJid`, `chatJid`, and `jid` interchangeably across
    versions — accept all three."""
    return (
        m.get("remoteJid") or m.get("chatJid") or m.get("jid")
        or m.get("from") or m.get("to") or ""
    )


def _msg_ts(m: dict) -> int:
    """Best-effort epoch-seconds timestamp. Falls back to 0 so unparseable
    rows don't crash the sort."""
    for k in ("messageTimestamp", "timestamp", "ts", "createdAt", "created_at"):
        v = m.get(k)
        if v is None:
            continue
        try:
            n = int(v)
            # Some APIs use milliseconds — heuristic: if it's > year 3000 in
            # seconds, treat as ms.
            if n > 32_000_000_000:
                n //= 1000
            return n
        except Exception:
            # ISO string? Cheap parse without dateutil.
            try:
                from datetime import datetime
                return int(datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp())
            except Exception:
                continue
    return 0


def _msg_text(m: dict) -> str:
    """Pull the displayable text out of a message-log row. WhatsApp
    messages can be in many envelopes — text, image+caption, etc. We
    return whatever string-y body we find, plus a [type] tag for media."""
    # Direct text field on common shapes
    for k in ("text", "body", "message", "content"):
        v = m.get(k)
        if isinstance(v, str) and v.strip():
            return v
    # Nested under `message.text` / `message.conversation` (Baileys-ish)
    msg = m.get("message")
    if isinstance(msg, dict):
        for k in ("conversation", "extendedTextMessage", "text"):
            v = msg.get(k)
            if isinstance(v, str) and v.strip():
                return v
            if isinstance(v, dict):
                txt = v.get("text") or v.get("caption")
                if isinstance(txt, str) and txt.strip():
                    return txt
        # Image / video / document → show a placeholder
        for kind in ("imageMessage", "videoMessage", "audioMessage", "documentMessage", "stickerMessage"):
            if kind in msg:
                caption = (msg[kind] or {}).get("caption") if isinstance(msg[kind], dict) else None
                label = kind.replace("Message", "")
                return f"[{label}]" + (f" {caption}" if caption else "")
    mtype = m.get("messageType") or m.get("type")
    if mtype:
        return f"[{mtype}]"
    return ""


def _msg_from_me(m: dict) -> bool:
    """Heuristics for which side sent the message."""
    if isinstance(m.get("fromMe"), bool):
        return m["fromMe"]
    if isinstance(m.get("from_me"), bool):
        return m["from_me"]
    key = m.get("key")
    if isinstance(key, dict) and isinstance(key.get("fromMe"), bool):
        return key["fromMe"]
    direction = (m.get("direction") or "").lower()
    if direction in ("out", "outgoing", "outbound", "sent"):
        return True
    if direction in ("in", "incoming", "inbound", "received"):
        return False
    return False


def _jid_display_name(jid: str) -> str:
    """Strip WhatsApp's @s.whatsapp.net / @g.us suffix for display."""
    if not jid:
        return "(unknown)"
    if "@" in jid:
        return jid.split("@", 1)[0]
    return jid


@router.get("/whatsapp/chats")
async def whatsapp_chats(limit: int = 300) -> dict:
    """Group the latest `limit` message-logs by remoteJid, return one
    row per conversation sorted by most-recent activity. Used by the
    inbox left pane.

    Returns {ok, chats: [{jid, name, last_text, last_ts, last_from_me,
    msg_count}, ...], error?}.
    """
    cfg = load_escalation_config()
    api_key    = str(cfg.get("wasender_api_key") or "").strip()
    session_id = str(cfg.get("wasender_session_id") or "").strip()
    client = build_wasender_client(api_key)
    result = await client.list_messages(session_id, limit=limit)
    if not result.get("ok"):
        return {"ok": False, "chats": [], "error": result.get("error")}

    grouped: dict[str, dict] = {}
    for m in (result.get("items") or []):
        if not isinstance(m, dict):
            continue
        jid = _msg_jid(m)
        if not jid:
            continue
        ts   = _msg_ts(m)
        text = _msg_text(m)
        rec = grouped.setdefault(jid, {
            "jid":           jid,
            "name":          _jid_display_name(jid),
            "last_text":     "",
            "last_ts":       0,
            "last_from_me":  False,
            "msg_count":     0,
            "is_group":      jid.endswith("@g.us"),
        })
        rec["msg_count"] += 1
        if ts >= rec["last_ts"]:
            rec["last_ts"]      = ts
            rec["last_text"]    = text
            rec["last_from_me"] = _msg_from_me(m)

    chats = sorted(grouped.values(), key=lambda x: x["last_ts"], reverse=True)
    return {"ok": True, "chats": chats, "total_messages": len(result.get("items") or [])}


@router.get("/whatsapp/messages")
async def whatsapp_messages(jid: str, limit: int = 300) -> dict:
    """Return all message-log rows for one conversation, normalised and
    sorted oldest→newest so the SPA can render them as a chat thread."""
    if not jid:
        raise HTTPException(400, "jid is required")
    cfg = load_escalation_config()
    api_key    = str(cfg.get("wasender_api_key") or "").strip()
    session_id = str(cfg.get("wasender_session_id") or "").strip()
    client = build_wasender_client(api_key)
    result = await client.list_messages(session_id, limit=limit)
    if not result.get("ok"):
        return {"ok": False, "messages": [], "error": result.get("error")}

    rows = []
    for m in (result.get("items") or []):
        if not isinstance(m, dict):
            continue
        if _msg_jid(m) != jid:
            continue
        rows.append({
            "id":       m.get("id") or (m.get("key") or {}).get("id"),
            "ts":       _msg_ts(m),
            "from_me":  _msg_from_me(m),
            "text":     _msg_text(m),
            # Raw type tag for icons / styling
            "type":     m.get("messageType") or m.get("type") or "text",
        })
    rows.sort(key=lambda r: r["ts"])
    return {"ok": True, "messages": rows, "count": len(rows)}


# ----- Saved-call History --------------------------------------------------

@router.get("/agent/calls")
async def agent_list_calls(limit: int = 100) -> dict:
    """List recorded calls newest-first. Cheap — just stats every meta.json
    in data/demos/clinic/calls."""
    return {"items": list_saved_calls(max(1, min(500, limit)))}


@router.get("/agent/calls/{call_id}")
async def agent_get_call(call_id: str) -> dict:
    meta = load_saved_call(call_id)
    if meta is None:
        raise HTTPException(404, "call not found")
    return meta


@router.get("/agent/calls/{call_id}/audio/{side}")
async def agent_get_call_audio(call_id: str, side: str):
    """Stream the caller-side or agent-side WAV. `side` ∈ {caller, agent}."""
    p = call_audio_path(call_id, side)
    if p is None:
        raise HTTPException(404, "audio not found")
    return FileResponse(str(p), media_type="audio/wav",
                        filename=f"{call_id}-{side}.wav")


@router.delete("/agent/calls/{call_id}")
async def agent_delete_call(call_id: str) -> dict:
    if not delete_saved_call(call_id):
        raise HTTPException(404, "call not found")
    return {"ok": True}


# ----- Data snapshot (clinic SPA → backend) ------------------------------
# The agent's function tools read from data/demos/clinic/snapshot.json. The
# Clinic SPA's Dashboard pushes the current localStorage state here on
# mount (and after any SPA-side mutation) so the agent always has the live
# patient + appointment data.

@router.get("/data/snapshot")
async def agent_get_snapshot() -> dict:
    return load_snapshot()


@router.post("/data/snapshot")
async def agent_set_snapshot(payload: dict) -> dict:
    """Accepts a full snapshot from the SPA — patients, appointments,
    clinics, providers, slot_overrides. Stored as-is."""
    if not isinstance(payload, dict):
        raise HTTPException(400, "snapshot must be a JSON object")
    # Only persist the keys we expect — keeps the file tidy and avoids
    # accidentally storing UI-only state.
    clean = {
        "patients":       list(payload.get("patients") or []),
        "appointments":   list(payload.get("appointments") or []),
        "clinics":        list(payload.get("clinics") or []),
        "providers":      list(payload.get("providers") or []),
        "slot_overrides": list(payload.get("slot_overrides") or []),
    }
    save_snapshot(clean)
    return {
        "ok":              True,
        "patient_count":   len(clean["patients"]),
        "appt_count":      len(clean["appointments"]),
        "clinic_count":    len(clean["clinics"]),
        "override_count":  len(clean["slot_overrides"]),
    }


@router.websocket("/agent/ws")
async def agent_ws(websocket: WebSocket) -> None:
    """Push transcript / call lifecycle events to the Dashboard."""
    await websocket.accept()
    q = clinic_live_agent_service.subscribe()
    try:
        # Send the current status so the UI hydrates immediately.
        await websocket.send_text(json.dumps({
            "type": "snapshot",
            "status": clinic_live_agent_service.status(),
            "calls":  clinic_live_agent_service.active_calls(),
        }))

        async def _drain_incoming() -> None:
            try:
                while True:
                    await websocket.receive_text()
            except WebSocketDisconnect:
                raise

        drain = asyncio.create_task(_drain_incoming())
        try:
            while True:
                pop = asyncio.create_task(q.get())
                done, _pending = await asyncio.wait(
                    {pop, drain},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if drain in done:
                    pop.cancel()
                    return
                event = pop.result()
                await websocket.send_text(json.dumps(event))
        finally:
            drain.cancel()
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("agent_ws fatal")
    finally:
        clinic_live_agent_service.unsubscribe(q)
        try: await websocket.close()
        except Exception: pass
