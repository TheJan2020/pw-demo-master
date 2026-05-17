"""Clinic demo backend — login, current-user, logout, and the Live Agent
control plane (config + persona/KB publish + status). The AudioSocket
service itself lives in demos.clinic.live_agent."""
from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
import asyncio

from ...core.state import state
from . import config
from .live_agent import (
    clinic_live_agent_service,
    load_kb, load_persona, save_kb, save_persona,
)
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
