"""SIP softphone configuration.

The actual SIP/RTP traffic flows browser → PBX (via SIP-over-WebSocket +
WebRTC). This backend only stores credentials and reports config status.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from ..core.state import state

router = APIRouter()


class SipConfigIn(BaseModel):
    ws_url:       Optional[str] = None
    extension:    Optional[str] = None
    password:     Optional[str] = None
    realm:        Optional[str] = None
    display_name: Optional[str] = None


class SipConfigOut(BaseModel):
    ws_url:       Optional[str] = None
    extension:    Optional[str] = None
    realm:        Optional[str] = None
    display_name: Optional[str] = None
    password_set: bool = False


def _current() -> SipConfigOut:
    return SipConfigOut(
        ws_url=state.sip_ws_url,
        extension=state.sip_extension,
        realm=state.sip_realm,
        display_name=state.sip_display_name,
        password_set=bool(state.sip_password),
    )


@router.get("/config", response_model=SipConfigOut)
async def get_config() -> SipConfigOut:
    return _current()


@router.post("/config", response_model=SipConfigOut)
async def set_config(payload: SipConfigIn) -> SipConfigOut:
    if payload.ws_url is not None:
        state.sip_ws_url = (payload.ws_url or "").strip() or None
    if payload.extension is not None:
        state.sip_extension = (payload.extension or "").strip() or None
    if payload.password is not None:
        # Empty string = clear; non-empty = update (so partial saves keep the
        # current password when the user leaves the field blank).
        state.sip_password = payload.password or None
    if payload.realm is not None:
        state.sip_realm = (payload.realm or "").strip() or None
    if payload.display_name is not None:
        state.sip_display_name = (payload.display_name or "").strip() or None
    state.save()
    return _current()


@router.get("/health")
async def health() -> dict:
    """Reports whether the SIP settings are filled in. Actual register status
    lives on the browser side — we don't speak SIP from the backend."""
    if not state.sip_ws_url or not state.sip_extension:
        return {"status": "idle", "message": "Not configured"}
    if not state.sip_password:
        return {"status": "warn", "message": "Password missing"}
    return {"status": "ok", "message": f"Configured · {state.sip_extension}"}


@router.get("/credentials")
async def get_credentials() -> dict:
    """Return the full SIP credentials INCLUDING the password.

    JsSIP runs in the browser and must hand the password to the PBX during
    register/INVITE digest auth — so it can't be hidden the way we hide HA
    tokens or Gemini keys. The endpoint exists only so the Extension page
    can fetch the password it needs to start the softphone. The same demo
    is bound to localhost via run.sh / run.ps1; if you expose the backend
    on a network, treat this endpoint as you would the SIP password.
    """
    return {
        "ws_url":       state.sip_ws_url,
        "extension":    state.sip_extension,
        "password":     state.sip_password or "",
        "realm":        state.sip_realm,
        "display_name": state.sip_display_name,
    }
