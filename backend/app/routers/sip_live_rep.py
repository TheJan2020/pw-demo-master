"""SIP Live Representative — config, status, persistent history, live WS."""
from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from ..core.state import state
from ..services.sip_live_rep import (
    sip_live_rep_service as svc,
    list_history,
    clear_history,
)

logger = logging.getLogger("sip_live_rep_router")
router = APIRouter()


class SlrConfigIn(BaseModel):
    enabled:               Optional[bool] = None
    bind_host:             Optional[str] = None
    bind_port:             Optional[int] = None
    system_prompt:         Optional[str] = None
    voice:                 Optional[str] = None
    greeting:              Optional[str] = None
    max_call_s:            Optional[int] = None
    knowledge:             Optional[str] = None
    info_schema:           Optional[list[dict]] = None
    interruption_enabled:  Optional[bool] = None


class SlrConfigOut(BaseModel):
    enabled:               bool
    bind_host:             str
    bind_port:             int
    system_prompt:         str
    voice:                 str
    greeting:              str
    max_call_s:            int
    knowledge:             str
    info_schema:           list[dict]
    interruption_enabled:  bool


def _current() -> SlrConfigOut:
    return SlrConfigOut(
        enabled=bool(state.slr_enabled),
        bind_host=state.slr_bind_host or "0.0.0.0",
        bind_port=int(state.slr_bind_port or 8091),
        system_prompt=state.slr_system_prompt or "",
        voice=state.slr_voice or "Aoede",
        greeting=state.slr_greeting or "",
        max_call_s=int(state.slr_max_call_s or 0),
        knowledge=state.slr_knowledge or "",
        info_schema=list(state.slr_info_schema or []),
        interruption_enabled=bool(state.slr_interruption_enabled),
    )


@router.get("/config", response_model=SlrConfigOut)
async def get_config() -> SlrConfigOut:
    return _current()


@router.post("/config", response_model=SlrConfigOut)
async def set_config(payload: SlrConfigIn) -> SlrConfigOut:
    if payload.enabled       is not None: state.slr_enabled       = bool(payload.enabled)
    if payload.bind_host     is not None: state.slr_bind_host     = (payload.bind_host or "0.0.0.0").strip() or "0.0.0.0"
    if payload.bind_port     is not None: state.slr_bind_port     = max(1, min(65535, int(payload.bind_port)))
    if payload.system_prompt is not None: state.slr_system_prompt = payload.system_prompt
    if payload.voice         is not None: state.slr_voice         = (payload.voice or "Aoede").strip() or "Aoede"
    if payload.greeting      is not None: state.slr_greeting      = payload.greeting or ""
    if payload.max_call_s    is not None: state.slr_max_call_s    = max(0, int(payload.max_call_s))
    if payload.knowledge     is not None: state.slr_knowledge     = payload.knowledge
    if payload.interruption_enabled is not None:
        state.slr_interruption_enabled = bool(payload.interruption_enabled)
    if payload.info_schema   is not None:
        cleaned = []
        for f in payload.info_schema:
            if not isinstance(f, dict):
                continue
            name = (f.get("name") or "").strip()
            if not name:
                continue
            cleaned.append({
                "name":        name,
                "label":       (f.get("label") or name).strip(),
                "description": (f.get("description") or "").strip(),
            })
        state.slr_info_schema = cleaned
    state.save()
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
    }


@router.get("/history")
async def history(
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> dict:
    items, total = list_history(offset, limit)
    return {"items": items, "total": total, "offset": offset, "limit": limit}


@router.delete("/history")
async def history_clear() -> dict:
    clear_history()
    return {"ok": True}


@router.websocket("/ws")
async def live_ws(websocket: WebSocket) -> None:
    """Pushes status + per-call events. The Live Rep page subscribes here
    so its 'active' list updates without polling and per-turn transcript
    chunks appear in real time during a call."""
    await websocket.accept()
    items, total = list_history(0, 20)
    try:
        await websocket.send_text(json.dumps({
            "type": "snapshot",
            "status": svc.status(),
            "calls": svc.active_calls(),
            "history": items,
            "history_total": total,
        }))
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
