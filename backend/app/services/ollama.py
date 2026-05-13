"""
Ollama client — talks to a local Ollama daemon over HTTP.

Used by the AI-Camera rules engine as an alternative vision provider to
Gemini. Configuration is just the base URL (no auth — Ollama is typically
deployed on a trusted local network).

Two surfaces:
  - `list_models()`        →  GET /api/tags    (for the model picker)
  - `generate_verdict(…)`  →  POST /api/generate with images + format=json
"""
from __future__ import annotations

import base64
import json
import logging
from typing import Optional

import httpx

from ..core.state import state

logger = logging.getLogger("ollama")

# Vision inference on a local RTX can take several seconds for larger images
# or first-call model warm-up. Generous overall timeout, short connect.
_TIMEOUT = httpx.Timeout(60.0, connect=5.0)


def _base_url() -> Optional[str]:
    url = (state.ollama_url or "").strip().rstrip("/")
    return url or None


def is_configured() -> bool:
    return _base_url() is not None


async def health() -> dict:
    """Probe `/api/version`. Returns {status: ok|err, message, version?}."""
    base = _base_url()
    if not base:
        return {"status": "err", "message": "Ollama URL not configured"}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            r = await client.get(f"{base}/api/version")
            r.raise_for_status()
            data = r.json() or {}
            return {"status": "ok", "version": data.get("version"), "message": "Connected"}
    except Exception as e:
        return {"status": "err", "message": f"{type(e).__name__}: {e}"}


async def list_models() -> list[dict]:
    """Return the list of installed models from Ollama's /api/tags.
    Each entry: {"name": "moondream:latest", "size": ..., "modified_at": ...}.
    Empty list on error (logged)."""
    base = _base_url()
    if not base:
        return []
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            r = await client.get(f"{base}/api/tags")
            r.raise_for_status()
            data = r.json() or {}
            models = data.get("models") or []
            return [m for m in models if isinstance(m, dict) and m.get("name")]
    except Exception:
        logger.warning("ollama list_models failed", exc_info=True)
        return []


async def generate_verdict(
    model: str,
    system_instruction: str,
    user_prompt: str,
    images: list[bytes],
) -> dict:
    """Call Ollama with vision images + a verdict prompt. Returns the same
    shape as the Gemini path:
      {"text": <raw response string>, "ok": bool, "error": str|None}.

    Ollama's `format: "json"` constrains the output to a JSON object — combined
    with the existing system instruction it yields the same {triggered, reason}
    contract as Gemini, though without hard schema enforcement.
    """
    base = _base_url()
    if not base:
        return {"text": "", "ok": False, "error": "Ollama URL not configured"}

    encoded_images = [base64.b64encode(img).decode("ascii") for img in images]

    body = {
        "model": model,
        "system": system_instruction,
        "prompt": user_prompt,
        "images": encoded_images,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0.1,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.post(f"{base}/api/generate", json=body)
            r.raise_for_status()
            data = r.json() or {}
    except httpx.HTTPStatusError as e:
        # Try to surface the server's message (Ollama puts it in JSON `error`).
        msg = f"HTTP {e.response.status_code}"
        try:
            err = e.response.json().get("error")
            if err:
                msg = f"{msg}: {err}"
        except Exception:
            pass
        return {"text": "", "ok": False, "error": msg}
    except Exception as e:
        return {"text": "", "ok": False, "error": f"{type(e).__name__}: {e}"}

    text = (data.get("response") or "").strip()
    return {"text": text, "ok": True, "error": None}


async def generate_text(
    model: str,
    prompt: str,
    images: Optional[list[bytes]] = None,
    system_instruction: Optional[str] = None,
) -> dict:
    """Free-form text generation — *not* constrained to JSON. Used by the
    Test AI Model page for arbitrary Q&A about an uploaded image.

    Returns the same shape as generate_verdict():
      {"text": <response string>, "ok": bool, "error": str|None}
    """
    base = _base_url()
    if not base:
        return {"text": "", "ok": False, "error": "Ollama URL not configured"}

    body: dict = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.4},
    }
    if system_instruction:
        body["system"] = system_instruction
    if images:
        body["images"] = [base64.b64encode(img).decode("ascii") for img in images]

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.post(f"{base}/api/generate", json=body)
            r.raise_for_status()
            data = r.json() or {}
    except httpx.HTTPStatusError as e:
        msg = f"HTTP {e.response.status_code}"
        try:
            err = e.response.json().get("error")
            if err:
                msg = f"{msg}: {err}"
        except Exception:
            pass
        return {"text": "", "ok": False, "error": msg}
    except Exception as e:
        return {"text": "", "ok": False, "error": f"{type(e).__name__}: {e}"}

    text = (data.get("response") or "").strip()
    return {"text": text, "ok": True, "error": None}
