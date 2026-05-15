"""SIP Live Assistant — config + live UI feed."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from ..core.state import state
from ..services.sip_live_agent import sip_live_agent_service as svc

logger = logging.getLogger("sip_live_agent_router")
router = APIRouter()


class SlaConfigIn(BaseModel):
    enabled:           Optional[bool] = None
    bind_host:         Optional[str] = None
    bind_port:         Optional[int] = None
    system_prompt:     Optional[str] = None
    voice:             Optional[str] = None
    greeting:          Optional[str] = None
    enable_ha_tools:   Optional[bool] = None
    only_areas:        Optional[bool] = None
    max_call_s:        Optional[int] = None
    cameras:           Optional[list[str]] = None


class SlaConfigOut(BaseModel):
    enabled:           bool
    bind_host:         str
    bind_port:         int
    system_prompt:     str
    voice:             str
    greeting:          str
    enable_ha_tools:   bool
    only_areas:        bool
    max_call_s:        int
    cameras:           list[str]


def _current() -> SlaConfigOut:
    return SlaConfigOut(
        enabled=bool(state.sla_enabled),
        bind_host=state.sla_bind_host or "0.0.0.0",
        bind_port=int(state.sla_bind_port or 8090),
        system_prompt=state.sla_system_prompt or "",
        voice=state.sla_voice or "Aoede",
        greeting=state.sla_greeting or "",
        enable_ha_tools=bool(state.sla_enable_ha_tools),
        only_areas=bool(state.sla_only_areas),
        max_call_s=int(state.sla_max_call_s or 0),
        cameras=list(state.sla_cameras or []),
    )


@router.get("/config", response_model=SlaConfigOut)
async def get_config() -> SlaConfigOut:
    return _current()


@router.post("/config", response_model=SlaConfigOut)
async def set_config(payload: SlaConfigIn) -> SlaConfigOut:
    if payload.enabled         is not None: state.sla_enabled         = bool(payload.enabled)
    if payload.bind_host       is not None: state.sla_bind_host       = (payload.bind_host or "0.0.0.0").strip() or "0.0.0.0"
    if payload.bind_port       is not None: state.sla_bind_port       = max(1, min(65535, int(payload.bind_port)))
    if payload.system_prompt   is not None: state.sla_system_prompt   = payload.system_prompt
    if payload.voice           is not None: state.sla_voice           = (payload.voice or "Aoede").strip() or "Aoede"
    if payload.greeting        is not None: state.sla_greeting        = payload.greeting or ""
    if payload.enable_ha_tools is not None: state.sla_enable_ha_tools = bool(payload.enable_ha_tools)
    if payload.only_areas      is not None: state.sla_only_areas      = bool(payload.only_areas)
    if payload.max_call_s      is not None: state.sla_max_call_s      = max(0, int(payload.max_call_s))
    if payload.cameras         is not None: state.sla_cameras         = [c for c in payload.cameras if isinstance(c, str) and c.strip()]
    state.save()
    # React to the change (start/stop/rebind) once the event loop is free.
    svc.apply_config()
    return _current()


@router.get("/health")
async def health() -> dict:
    s = svc.status()
    if not s["enabled"]:
        return {"status": "idle", "message": "Disabled"}
    if not state.gemini_api_key:
        return {"status": "err", "message": "Gemini API key not configured"}
    if not s["running"]:
        return {"status": "err", "message": s.get("last_error") or "Not running"}
    return {"status": "ok",
            "message": f"Listening on {s['host']}:{s['port']} · {s['active']} active call(s)"}


@router.get("/status")
async def status() -> dict:
    return {
        **svc.status(),
        "calls": svc.active_calls(),
        "history": svc.history(),
    }


@router.websocket("/ws")
async def live_ws(websocket: WebSocket) -> None:
    """Push status + per-call events to the management page in real time."""
    await websocket.accept()
    try:
        await websocket.send_text(json.dumps({"type": "snapshot",
                                              "status": svc.status(),
                                              "calls": svc.active_calls(),
                                              "history": svc.history()}))
    except Exception:
        return

    q = svc.subscribe()
    try:
        while True:
            payload = await q.get()
            await websocket.send_text(json.dumps(payload))
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        svc.unsubscribe(q)
        try: await websocket.close()
        except Exception: pass
