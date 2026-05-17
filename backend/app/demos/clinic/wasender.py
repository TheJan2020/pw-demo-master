"""
Minimal WasenderApi client.

We don't pull the official `wasenderapi` Pydantic SDK — the v1 surface
we need is a single POST, so a 60-line `httpx` wrapper is lighter and
avoids version pins. Expand or swap to the SDK later if/when we add
contacts, message-logs, webhook event parsing, etc.

Docs reference: https://wasenderapi.com/api-docs
Wire format (verified against the official Python SDK source):

  POST https://www.wasenderapi.com/api/send-message
  Authorization: Bearer <per-session-api-key>
  Content-Type: application/json
  {"to": "<digits-only phone, country-code first>",
   "messageType": "text",
   "text": "<body>"}

  → 200 {"message": "...", "data": {"message_id": "..."}}
  → 4xx {"detail": "..."} or {"message": "..."}
  Response headers include X-RateLimit-Limit / -Remaining / -Reset.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger("demo_clinic.wasender")

WASENDER_BASE_URL = "https://www.wasenderapi.com/api"
_DIGITS = re.compile(r"\D+")


@dataclass
class WasenderCredentials:
    api_key: str

    def is_complete(self) -> bool:
        return bool(self.api_key)


def normalize_phone(s: str) -> str:
    """WasenderApi wants digits-only with country code first, no '+'.
    '+966 50 123 4567' → '966501234567'. Strips '00' international
    prefix; if the caller typed a Saudi national '0501234567' we
    prepend '966'. Empty string on a number we can't make sense of.
    """
    d = _DIGITS.sub("", s or "")
    if not d:
        return ""
    if d.startswith("00"):
        d = d[2:]
    # Bare 10-digit Saudi national format with leading 0 → add 966.
    if len(d) == 10 and d.startswith("05"):
        d = "966" + d[1:]
    # Bare 9-digit Saudi (no trunk 0) → add 966.
    if len(d) == 9 and d.startswith("5"):
        d = "966" + d
    # Anything else: assume the caller already typed the country code.
    return d


class WasenderClient:
    """Single-shot HTTPS client. The WasenderApi has no long-lived
    state we need to hold, so each call opens a fresh httpx connection.
    Throughput is irrelevant for a demo (a few messages per minute at
    peak)."""

    def __init__(self, creds: WasenderCredentials, *, timeout_s: float = 10.0):
        self.creds = creds
        self.timeout = timeout_s

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.creds.api_key}",
            "Content-Type":  "application/json",
            "Accept":        "application/json",
        }

    async def send_text(self, to: str, text: str) -> dict:
        """Returns a normalised result dict:
            {ok: bool, message_id: str?, status: int, error: str?, raw: dict}
        Never raises — UI shows the error in-band."""
        if not self.creds.is_complete():
            return {"ok": False, "status": 0, "error": "WhatsApp API key not configured"}
        phone = normalize_phone(to)
        if not phone:
            return {"ok": False, "status": 0, "error": "Phone number could not be parsed — use digits with country code"}
        body = {"to": phone, "messageType": "text", "text": text}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.post(
                    f"{WASENDER_BASE_URL}/send-message",
                    headers=self._headers(),
                    json=body,
                )
        except httpx.RequestError as e:
            logger.warning("WasenderApi send_text network error: %s", e)
            return {"ok": False, "status": 0, "error": f"network: {e}"}

        # Try to JSON-parse regardless of status; fall back to text.
        try:
            payload = r.json()
        except Exception:
            payload = {"raw_text": (r.text or "")[:500]}

        if 200 <= r.status_code < 300:
            data = (payload.get("data") or {}) if isinstance(payload, dict) else {}
            return {
                "ok":         True,
                "status":     r.status_code,
                "message_id": data.get("message_id"),
                "to":         phone,
                "raw":        payload,
            }

        # Pick the most useful error text — WasenderApi uses 'message'
        # for top-level errors and sometimes 'detail' / 'errors' for
        # validation. Be permissive about shape.
        err = (
            (isinstance(payload, dict) and (
                payload.get("error")
                or payload.get("message")
                or payload.get("detail")
            ))
            or f"HTTP {r.status_code}"
        )
        return {"ok": False, "status": r.status_code, "error": err, "raw": payload}

    async def list_messages(self, session_id: str, limit: int = 200) -> dict:
        """Pull recent message-logs for the paired session. Used by the
        inbox UI to render chat list + per-chat history (the WasenderApi
        has no 'group by chat' endpoint — we group client-side).

        Returns {ok, items: [...], error?}. Each item is the raw row from
        the API; the SPA + the chats endpoint do the normalisation since
        the response shape varies a bit by plan tier.
        """
        if not self.creds.is_complete():
            return {"ok": False, "items": [], "error": "API key not configured"}
        if not session_id:
            return {"ok": False, "items": [],
                    "error": "WhatsApp session ID not configured"}
        params = {"limit": str(max(1, min(500, int(limit))))}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.get(
                    f"{WASENDER_BASE_URL}/whatsapp-sessions/{session_id}/message-logs",
                    headers=self._headers(),
                    params=params,
                )
        except httpx.RequestError as e:
            return {"ok": False, "items": [], "error": f"network: {e}"}
        try:
            payload = r.json()
        except Exception:
            payload = {}
        if not (200 <= r.status_code < 300):
            err = (
                (isinstance(payload, dict) and (payload.get("message") or payload.get("error")))
                or f"HTTP {r.status_code}"
            )
            return {"ok": False, "items": [], "error": err, "status": r.status_code}
        # WasenderApi sometimes wraps the array under `data`, sometimes
        # under `messages`, sometimes returns it raw. Be tolerant.
        if isinstance(payload, list):
            items = payload
        elif isinstance(payload, dict):
            items = (
                payload.get("data")
                or payload.get("messages")
                or payload.get("items")
                or []
            )
            if isinstance(items, dict):  # paginated wrapper
                items = items.get("data") or items.get("items") or []
        else:
            items = []
        return {"ok": True, "items": items, "raw": payload}

    async def ping(self) -> dict:
        """Cheap key-validity check. We hit /contacts because it's the
        smallest endpoint that requires a valid per-session API key.
        Returns {ok, status, contact_count?, error?}. Used by the SPA's
        status pill so the operator knows whether the key is good
        without having to send a real message."""
        if not self.creds.is_complete():
            return {"ok": False, "status": 0, "error": "API key not configured"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.get(
                    f"{WASENDER_BASE_URL}/contacts",
                    headers=self._headers(),
                )
        except httpx.RequestError as e:
            return {"ok": False, "status": 0, "error": f"network: {e}"}
        if 200 <= r.status_code < 300:
            try:
                p = r.json()
                count = len(p.get("data") or p.get("contacts") or p) if isinstance(p, (list, dict)) else None
            except Exception:
                count = None
            return {"ok": True, "status": r.status_code, "contact_count": count}
        try:
            err = r.json().get("message") or r.json().get("error") or f"HTTP {r.status_code}"
        except Exception:
            err = f"HTTP {r.status_code}"
        return {"ok": False, "status": r.status_code, "error": err}


def build_client(api_key: Optional[str]) -> WasenderClient:
    return WasenderClient(WasenderCredentials(api_key=(api_key or "").strip()))
