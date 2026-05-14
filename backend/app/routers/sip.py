"""SIP softphone configuration + PBX requirements check.

The actual SIP/RTP traffic flows browser → PBX (via SIP-over-WebSocket +
WebRTC). This backend only stores credentials, reports config status,
and probes the PBX for the bits the Live Assistant needs.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import ssl
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from ..core.state import state

logger = logging.getLogger("sip")
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


# ============================================================
# PBX — single-host setting + connectivity probe
# ============================================================

class PbxConfigIn(BaseModel):
    host: Optional[str] = None


class PbxConfigOut(BaseModel):
    host:           Optional[str] = None
    default_ws_url: Optional[str] = None   # derived (wss://<host>:8089/ws)


def _default_ws_url(host: Optional[str]) -> Optional[str]:
    h = (host or "").strip()
    return f"wss://{h}:8089/ws" if h else None


@router.get("/pbx", response_model=PbxConfigOut)
async def get_pbx() -> PbxConfigOut:
    return PbxConfigOut(host=state.pbx_host, default_ws_url=_default_ws_url(state.pbx_host))


@router.post("/pbx", response_model=PbxConfigOut)
async def set_pbx(payload: PbxConfigIn) -> PbxConfigOut:
    if payload.host is not None:
        state.pbx_host = (payload.host or "").strip() or None
    state.save()
    return PbxConfigOut(host=state.pbx_host, default_ws_url=_default_ws_url(state.pbx_host))


@router.post("/pbx/check")
async def check_pbx(payload: PbxConfigIn) -> dict:
    """Run a battery of connectivity probes against the PBX. Returns a
    list of {id, name, ok, message, optional?} so the UI can render a
    checklist with green/red marks."""
    host = ((payload.host if payload.host is not None else state.pbx_host) or "").strip()
    if not host:
        return {"ok": False, "host": "", "checks": [],
                "message": "Provide a PBX host first."}

    checks: list[dict] = []

    # 1. SIP-WebSocket TCP reachability (Asterisk default 8089).
    sip_ws_ok = await _check_tcp(host, 8089)
    checks.append({
        "id": "sip_ws_tcp",
        "name": "SIP-WebSocket port reachable (8089/tcp)",
        "ok": sip_ws_ok,
        "message": "OK" if sip_ws_ok else f"Cannot reach {host}:8089",
    })

    # 2. TLS handshake on 8089 (only attempt if TCP works).
    if sip_ws_ok:
        tls_ok, tls_msg = await _check_tls(host, 8089)
        checks.append({
            "id": "sip_ws_tls",
            "name": "TLS handshake on 8089 succeeds",
            "ok": tls_ok,
            "message": tls_msg,
        })

        # 3. WebSocket upgrade with the `sip` subprotocol.
        if tls_ok:
            ws_ok, ws_msg = await _check_sip_ws(host)
            checks.append({
                "id": "sip_ws_upgrade",
                "name": "WebSocket /ws accepts the 'sip' subprotocol",
                "ok": ws_ok,
                "message": ws_msg,
            })

    # 4. Local AudioSocket bridge running (needed for the Live Assistant
    # to actually receive call audio from the PBX).
    try:
        from ..services.sip_live_agent import sip_live_agent_service
        sla = sip_live_agent_service.status()
        running = bool(sla.get("running"))
        checks.append({
            "id": "local_audiosocket",
            "name": "Local AudioSocket bridge running",
            "ok": running,
            "message": (
                f"Listening on {sla['host']}:{sla['port']}"
                if running else
                "Not running — enable in SIP Phone → Live Assistant"
            ),
        })
    except Exception as e:
        checks.append({
            "id": "local_audiosocket",
            "name": "Local AudioSocket bridge running",
            "ok": False,
            "message": f"Service not importable: {e}",
        })

    # 5. AMI port — optional, only useful if you later use AMI for
    # provisioning / call control. Doesn't block overall pass.
    ami_ok = await _check_tcp(host, 5038)
    checks.append({
        "id": "pbx_ami",
        "name": "AMI port reachable (5038/tcp)",
        "ok": ami_ok,
        "message": "OK" if ami_ok else "Not reachable (only needed for AMI features)",
        "optional": True,
    })

    overall = all(c["ok"] for c in checks if not c.get("optional"))
    return {"ok": overall, "host": host, "checks": checks}


# ----- check helpers ---------------------------------------------------------

async def _check_tcp(host: str, port: int, timeout: float = 3.0) -> bool:
    try:
        fut = asyncio.open_connection(host, port)
        reader, writer = await asyncio.wait_for(fut, timeout=timeout)
        writer.close()
        try: await writer.wait_closed()
        except Exception: pass
        return True
    except Exception:
        return False


async def _check_tls(host: str, port: int, timeout: float = 5.0) -> tuple[bool, str]:
    ctx = ssl.create_default_context()
    # PBXes often run self-signed certs on the demo network — don't fail
    # the check just because we can't verify the chain.
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        fut = asyncio.open_connection(host, port, ssl=ctx, server_hostname=host)
        reader, writer = await asyncio.wait_for(fut, timeout=timeout)
        ssl_obj = writer.get_extra_info("ssl_object")
        msg = "TLS handshake OK"
        if ssl_obj is not None:
            try:
                cipher = ssl_obj.cipher()
                if cipher:
                    msg = f"TLS handshake OK · {cipher[0]} ({cipher[1]})"
            except Exception:
                pass
        writer.close()
        try: await writer.wait_closed()
        except Exception: pass
        return True, msg
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


async def _check_sip_ws(host: str, timeout: float = 5.0) -> tuple[bool, str]:
    """Open a real WebSocket upgrade with `sip` subprotocol, check the response."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        fut = asyncio.open_connection(host, 8089, ssl=ctx, server_hostname=host)
        reader, writer = await asyncio.wait_for(fut, timeout=timeout)

        key = base64.b64encode(os.urandom(16)).decode("ascii")
        req = (
            f"GET /ws HTTP/1.1\r\n"
            f"Host: {host}:8089\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n"
            f"Sec-WebSocket-Protocol: sip\r\n"
            f"\r\n"
        ).encode("ascii")
        writer.write(req)
        await writer.drain()

        # Read until end of headers (\r\n\r\n).
        buf = b""
        while b"\r\n\r\n" not in buf and len(buf) < 16384:
            chunk = await asyncio.wait_for(reader.read(2048), timeout=timeout)
            if not chunk: break
            buf += chunk
        writer.close()
        try: await writer.wait_closed()
        except Exception: pass

        if not buf:
            return False, "Empty response from PBX"
        first = buf.split(b"\r\n", 1)[0].decode("ascii", "replace")
        if "101" not in first:
            return False, f"Expected 101 Switching Protocols, got: {first[:100]}"

        # Look for Sec-WebSocket-Protocol header.
        for line in buf.split(b"\r\n"):
            if line.lower().startswith(b"sec-websocket-protocol:"):
                proto = line.split(b":", 1)[1].decode("ascii", "replace").strip()
                if "sip" in proto.lower():
                    return True, f"SIP subprotocol negotiated ({proto})"
                return True, f"WebSocket upgraded but subprotocol = {proto!r}"
        return True, "WebSocket upgraded (no Sec-WebSocket-Protocol header)"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
