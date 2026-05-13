"""
AI-Camera Playground.

A WebSocket-driven runner that gets its OWN Gemini client per page session
(independent of the Smart Home Live Agent). For each iteration:

  1. Pull a snapshot from each selected Frigate camera.
  2. Send the frame(s) + rule to Gemini via generate_content with a
     JSON-schema response.
  3. Parse a {triggered: bool, reason: ...} verdict.
  4. If triggered, fire a configured Home Assistant service call.

The scan pattern decides *when* an iteration runs:
  - periodic            — every N seconds.
  - motion              — when a new Frigate event arrives for any selected cam.
  - periodic_motion     — either of the above.
  - entity_state        — when an HA entity transitions to a target state.

Why generate_content instead of the Live API?
  The Live API ('gemini-…-live-001') is tuned for streaming audio/video
  with audio replies. For periodic image classification with a discrete
  JSON verdict, generate_content is simpler, faster, and supports a
  response_schema so we don't have to babysit the model's output format.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from typing import Any, Optional

import httpx
from fastapi import APIRouter, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect

from google import genai
from google.genai import types

from ..core.state import state
from ..services.mqtt import mqtt_service
from ..services import ollama as ollama_client

logger = logging.getLogger("ai_camera")
router = APIRouter()

_TIMEOUT = httpx.Timeout(10.0)

# Known-good vision-capable model names to try if nothing derived from the
# configured Live model is available in the user's account.
_GLOBAL_VISION_FALLBACKS = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
]


def _derive_candidates(live_model: str) -> list[str]:
    """Return ordered candidate non-Live model names derived from the Live model.

    `gemini-3.1-flash-live-preview` is for the Live API. The non-Live counterpart
    varies between model families:
      - some only have `gemini-<v>-flash`
      - some have `gemini-<v>-flash-preview`
      - some have both
    Return both forms so the resolver can pick whichever the account actually has.
    """
    if not live_model:
        return []

    out: list[str] = []
    if "-live-preview" in live_model:
        out.append(live_model.replace("-live-preview", "-preview"))  # keep preview tag
        out.append(live_model.replace("-live-preview", ""))           # bare base
    # Numbered live build (e.g. gemini-2.0-flash-live-001 → gemini-2.0-flash)
    import re
    m = re.match(r"^(.*?)-live(-\d+)?$", live_model)
    if m:
        out.append(m.group(1))
    # If the configured model isn't a Live variant, try it as-is.
    if "-live" not in live_model:
        out.append(live_model)

    # Dedupe while preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for c in out:
        if c and c not in seen:
            seen.add(c)
            deduped.append(c)
    return deduped


async def _resolve_vision_model(client: genai.Client) -> tuple[str, list[str]]:
    """Query Gemini's ListModels and pick the best vision-capable model that
    actually exists in this account. Returns (chosen_model, candidate_chain).

    The chain is useful for logging — it shows what we tried in order so a
    surprised user can tell which derivation matched."""
    derived = _derive_candidates(state.gemini_model or "")
    preferred = derived + [c for c in _GLOBAL_VISION_FALLBACKS if c not in derived]

    available: set[str] = set()
    try:
        async for m in await client.aio.models.list():
            actions = list(getattr(m, "supported_actions", None) or [])
            if "generateContent" not in actions:
                continue
            name = (getattr(m, "name", "") or "").split("/")[-1]
            if name:
                available.add(name)
    except Exception as e:
        logger.warning("ListModels failed: %s — proceeding with best-guess derived name", e)
        return preferred[0] if preferred else _GLOBAL_VISION_FALLBACKS[0], preferred

    # First preference: a name we derived or explicitly fall back to.
    for c in preferred:
        if c in available:
            return c, preferred

    # Otherwise: any flash variant that's not a Live model. Sort descending so
    # newer versions surface first.
    flashes = sorted(
        (n for n in available if "flash" in n.lower() and "-live" not in n.lower()),
        reverse=True,
    )
    if flashes:
        return flashes[0], preferred

    # Last resort: any model that does generateContent.
    if available:
        return sorted(available, reverse=True)[0], preferred

    return (preferred[0] if preferred else _GLOBAL_VISION_FALLBACKS[0]), preferred


# ============================================================
# HTTP helpers — Frigate snapshots & events, HA state polling
# ============================================================

async def _fetch_frigate_snapshot(camera: str, height: int = 720) -> Optional[bytes]:
    if not state.frigate_url:
        return None
    url = f"{state.frigate_url}/api/{camera}/latest.jpg"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(url, params={"h": height})
            r.raise_for_status()
            return r.content
    except Exception as e:
        logger.warning("snapshot %s failed: %s", camera, e)
        return None


async def _frigate_new_event_for(cameras: list[str], after_ts: float) -> bool:
    if not state.frigate_url:
        return False
    params: dict[str, Any] = {"after": after_ts, "limit": 5}
    if cameras:
        params["cameras"] = ",".join(cameras)
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(f"{state.frigate_url}/api/events", params=params)
            r.raise_for_status()
            events = r.json() or []
        return len(events) > 0
    except Exception:
        return False


async def _ha_entity_state(entity_id: str) -> Optional[str]:
    if not state.homeassistant_url or not state.homeassistant_token:
        return None
    headers = {"Authorization": f"Bearer {state.homeassistant_token}"}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(
                f"{state.homeassistant_url}/api/states/{entity_id}",
                headers=headers,
            )
            r.raise_for_status()
            return r.json().get("state")
    except Exception as e:
        logger.warning("ha state %s failed: %s", entity_id, e)
        return None


async def _ha_call_service(action: dict) -> dict:
    if not state.homeassistant_url or not state.homeassistant_token:
        raise RuntimeError("Home Assistant not configured")
    domain  = action.get("domain")  or "homeassistant"
    service = action.get("service") or "turn_on"
    eid     = action.get("entity_id")
    sd      = action.get("service_data") or {}
    if not eid:
        raise RuntimeError("action.entity_id is required")

    body: dict[str, Any] = {"entity_id": eid}
    if isinstance(sd, dict):
        body.update({k: v for k, v in sd.items() if v is not None})

    headers = {
        "Authorization": f"Bearer {state.homeassistant_token}",
        "Content-Type":  "application/json",
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.post(
            f"{state.homeassistant_url}/api/services/{domain}/{service}",
            headers=headers,
            json=body,
        )
        r.raise_for_status()
        return {"ok": True, "called": f"{domain}.{service}", "args": body}


# ============================================================
# Scan-pattern trigger generator
# ============================================================

class _RunContext:
    """Mutable state shared between the trigger loop and the countdown emitter.

    `accum_active` is the total time motion has been ON since the last scan,
    used to gate Periodic+Motion. `motion_on_since` is the monotonic clock
    when motion last turned ON, or None if it's currently OFF. The two
    together let us pause the countdown when motion stops and resume from
    where we left off when motion returns.
    """

    def __init__(self, scan: dict, cameras: list[str]) -> None:
        self.scan = scan
        self.cameras = list(cameras or [])
        self.mode = (scan.get("mode") or "periodic").lower()
        self.period_s = max(2, int(scan.get("period_s") or 30))

        # Plain periodic — countdown is wall-clock since last scan.
        self.last_scan_monotonic: Optional[float] = None

        # Periodic+motion — countdown is *accumulated motion time* since last scan.
        self.accum_active: float = 0.0
        self.motion_on_since: Optional[float] = None
        self.motion_active: bool = False
        self.first_motion_seen: bool = False

    def on_motion_change(self, active: bool) -> None:
        if active == self.motion_active:
            return
        if active:
            self.motion_on_since = time.monotonic()
        else:
            if self.motion_on_since is not None:
                self.accum_active += time.monotonic() - self.motion_on_since
                self.motion_on_since = None
        self.motion_active = active

    def current_active_s(self) -> float:
        s = self.accum_active
        if self.motion_on_since is not None:
            s += time.monotonic() - self.motion_on_since
        return s

    def reset_motion_window(self) -> None:
        """Call after a Periodic+Motion scan completes."""
        self.accum_active = 0.0
        self.motion_on_since = time.monotonic() if self.motion_active else None

    def countdown(self) -> Optional[dict]:
        if self.mode == "periodic":
            if self.last_scan_monotonic is None:
                return {"mode": "periodic", "total_s": self.period_s,
                        "remaining_s": 0, "paused": False, "waiting_for_motion": False}
            elapsed = time.monotonic() - self.last_scan_monotonic
            return {"mode": "periodic", "total_s": self.period_s,
                    "remaining_s": max(0, int(round(self.period_s - elapsed))),
                    "paused": False, "waiting_for_motion": False}
        if self.mode == "periodic_motion":
            if not self.first_motion_seen:
                return {"mode": "periodic_motion", "total_s": self.period_s,
                        "remaining_s": self.period_s, "paused": True,
                        "waiting_for_motion": True}
            return {"mode": "periodic_motion", "total_s": self.period_s,
                    "remaining_s": max(0, int(round(self.period_s - self.current_active_s()))),
                    "paused": not self.motion_active,
                    "waiting_for_motion": False}
        return None


async def _is_motion_active(cameras: list[str]) -> bool:
    """Return True iff any of the named cameras currently has motion.
    Prefers MQTT push (instant); falls back to HTTP polling Frigate's
    in-progress events if MQTT isn't connected."""
    if mqtt_service.connected:
        return mqtt_service.any_motion(cameras)
    return await _frigate_new_event_for(cameras, time.time() - 5)


async def _trigger_stream(ctx: _RunContext):
    """Yields a label whenever the scan pattern says "now run an iteration".
    Updates the shared `ctx` so the countdown emitter has live data to report."""

    if ctx.mode == "periodic":
        ctx.last_scan_monotonic = time.monotonic()
        yield "initial"
        while True:
            await asyncio.sleep(ctx.period_s)
            ctx.last_scan_monotonic = time.monotonic()
            yield "periodic"
        return

    if ctx.mode == "motion":
        last_ts = time.time()
        while True:
            await asyncio.sleep(2)
            if await _is_motion_active(ctx.cameras) or await _frigate_new_event_for(ctx.cameras, last_ts):
                last_ts = time.time()
                yield "motion"
        return

    if ctx.mode == "periodic_motion":
        # Motion gates everything:
        #   - First scan fires the moment motion turns ON for the first time.
        #   - After that, we accumulate time-while-motion-active; when it
        #     reaches period_s, we scan again and reset the accumulator.
        #   - When motion turns OFF, the accumulator pauses.
        while True:
            current = await _is_motion_active(ctx.cameras)
            ctx.on_motion_change(current)

            if not ctx.first_motion_seen:
                if current:
                    ctx.first_motion_seen = True
                    yield "motion_initial"
                    ctx.reset_motion_window()
            else:
                if ctx.motion_active and ctx.current_active_s() >= ctx.period_s:
                    yield "periodic_motion"
                    ctx.reset_motion_window()

            await asyncio.sleep(0.5)
        return

    if ctx.mode == "entity_state":
        entity_id = ctx.scan.get("entity_id")
        target = str(ctx.scan.get("target_state") or "")
        if not entity_id or not target:
            while True:
                await asyncio.sleep(60)
        prev_match = False
        while True:
            await asyncio.sleep(2)
            curr = await _ha_entity_state(entity_id)
            now_match = curr == target
            if now_match and not prev_match:
                yield "entity_state"
            prev_match = now_match
        return

    # Unknown → behave like Periodic.
    ctx.last_scan_monotonic = time.monotonic()
    yield "initial"
    while True:
        await asyncio.sleep(ctx.period_s)
        ctx.last_scan_monotonic = time.monotonic()
        yield "periodic"


# ============================================================
# Gemini session + iteration logic
# ============================================================

def _build_system_instruction(rule: str) -> str:
    return (
        "You are a vision-analysis assistant for a security/operations camera. "
        "On each turn you will receive one or more frames from the camera(s) "
        "followed by a short prompt. Decide whether the following RULE is "
        "currently true based ONLY on what you can see in the frames.\n"
        "\n"
        f"RULE: {rule.strip()}\n"
        "\n"
        "Be conservative. Reply with `triggered: true` ONLY if you can clearly "
        "see the condition in the frame. If unsure, reply `false`.\n"
        "\n"
        "When triggered=true, ALSO populate `bbox` with the bounding box of the "
        "single region most responsible for the trigger:\n"
        "  - Coordinates are integers in 0..1000, normalized to the frame "
        "    (0,0 = top-left, 1000,1000 = bottom-right).\n"
        "  - `camera` MUST equal the camera label printed next to the frame.\n"
        "  - `label` is a 1-3 word description of what's in the box.\n"
        "When triggered=false, omit `bbox` entirely.\n"
        "\n"
        "Respond with NOTHING but a single JSON object, no prose, no markdown fences:\n"
        '  {"triggered": true|false, "reason": "<≤120 chars>", '
        '"bbox": {"camera": "...", "y0": 0, "x0": 0, "y1": 0, "x1": 0, "label": "..."}}'
    )


def _extract_json_object(text: str) -> Optional[dict]:
    if not text:
        return None
    s = text.strip()
    # Strip code fences if present.
    if s.startswith("```"):
        # drop leading and trailing fence lines
        lines = s.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        s = "\n".join(lines)
    # Take the largest {...} substring.
    start = s.find("{")
    end = s.rfind("}")
    if start < 0 or end <= start:
        return None
    candidate = s[start:end + 1]
    try:
        obj = json.loads(candidate)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


_BBOX_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "camera": types.Schema(type=types.Type.STRING,
                               description="Camera label of the frame the bbox belongs to."),
        "y0":     types.Schema(type=types.Type.INTEGER, description="Top   (0..1000)."),
        "x0":     types.Schema(type=types.Type.INTEGER, description="Left  (0..1000)."),
        "y1":     types.Schema(type=types.Type.INTEGER, description="Bottom (0..1000)."),
        "x1":     types.Schema(type=types.Type.INTEGER, description="Right (0..1000)."),
        "label":  types.Schema(type=types.Type.STRING,  description="1-3 word description."),
    },
)


_VERDICT_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "triggered": types.Schema(
            type=types.Type.BOOLEAN,
            description="True only if the rule is clearly satisfied in the frame(s).",
        ),
        "reason": types.Schema(
            type=types.Type.STRING,
            description="One-sentence description of what was seen.",
        ),
        "bbox": _BBOX_SCHEMA,
    },
    required=["triggered", "reason"],
)


def _parse_model_selector(selector: str) -> tuple[str, str]:
    """Same shape as the rules engine: `<provider>:<model>`. Empty → Gemini auto."""
    s = (selector or "").strip()
    if not s:
        return "gemini", ""
    if ":" not in s:
        return "gemini", s
    provider, _, model = s.partition(":")
    provider = provider.strip().lower()
    model = model.strip()
    if provider not in ("gemini", "ollama"):
        return "gemini", model
    return provider, model


async def _call_gemini_verdict(
    client: genai.Client, model: str, rule: str, snapshots: dict[str, bytes],
) -> dict:
    parts: list[types.Part] = []
    for cam, img in snapshots.items():
        parts.append(types.Part(inline_data=types.Blob(data=img, mime_type="image/jpeg")))
        parts.append(types.Part(text=f"(frame above is from camera: {cam})"))
    parts.append(types.Part(text="Apply the rule and reply now with the JSON verdict."))
    gen_config = types.GenerateContentConfig(
        system_instruction=_build_system_instruction(rule),
        response_mime_type="application/json",
        response_schema=_VERDICT_SCHEMA,
        temperature=0.1,
    )
    try:
        response = await client.aio.models.generate_content(
            model=model,
            contents=[types.Content(role="user", parts=parts)],
            config=gen_config,
        )
    except Exception as e:
        logger.warning("gemini generate_content failed in playground: %s", e)
        return {"text": "", "ok": False, "error": f"{type(e).__name__}: {e}"}
    return {"text": (response.text or "").strip(), "ok": True, "error": None}


async def _call_ollama_verdict(
    model: str, rule: str, snapshots: dict[str, bytes],
) -> dict:
    # Ollama doesn't take interleaved image/text parts the way Gemini does —
    # we list the cameras in a single user prompt that references the images
    # in the order they're sent.
    cam_list = ", ".join(snapshots.keys())
    user_prompt = (
        f"Frames provided in order: {cam_list}.\n"
        "Apply the rule and reply now with the JSON verdict."
    )
    return await ollama_client.generate_verdict(
        model=model,
        system_instruction=_build_system_instruction(rule),
        user_prompt=user_prompt,
        images=list(snapshots.values()),
    )


async def _run_iteration(
    websocket: WebSocket,
    client: genai.Client,
    gemini_default_model: str,
    model_selector: str,
    rule: str,
    iter_id: int,
    cameras: list[str],
    reason: str,
) -> Optional[dict]:
    # Capture snapshots
    snapshots: dict[str, bytes] = {}
    for cam in cameras:
        img = await _fetch_frigate_snapshot(cam)
        if img:
            snapshots[cam] = img

    if not snapshots:
        await _safe_send(websocket, {
            "type": "iteration_skipped",
            "iteration_id": iter_id,
            "trigger_reason": reason,
            "message": "No snapshots could be fetched from Frigate.",
        })
        return None

    started_at = time.time()
    await _safe_send(websocket, {
        "type": "iteration_start",
        "iteration_id": iter_id,
        "trigger_reason": reason,
        "timestamp": started_at,
        "cameras": list(snapshots.keys()),
        "snapshots": {c: base64.b64encode(b).decode("ascii") for c, b in snapshots.items()},
    })

    provider, model_id = _parse_model_selector(model_selector)
    if provider == "ollama":
        result = await _call_ollama_verdict(model_id, rule, snapshots)
        used_model = model_id
    else:
        used_model = model_id or gemini_default_model
        result = await _call_gemini_verdict(client, used_model, rule, snapshots)
        provider = "gemini"

    if not result.get("ok"):
        err = result.get("error") or "unknown error"
        return {
            "iteration_id": iter_id,
            "trigger_reason": reason,
            "started_at": started_at,
            "finished_at": time.time(),
            "response_text": f"error: {err}",
            "parsed": {"error": True, "message": err},
            "triggered": False,
            "provider": provider,
            "model": used_model,
        }

    text_buf = (result.get("text") or "").strip()
    parsed = _extract_json_object(text_buf) or {}
    triggered = bool(parsed.get("triggered")) if isinstance(parsed, dict) else False

    return {
        "iteration_id": iter_id,
        "trigger_reason": reason,
        "started_at": started_at,
        "finished_at": time.time(),
        "response_text": text_buf,
        "parsed": parsed,
        "triggered": triggered,
        "provider": provider,
        "model": used_model,
    }


# ============================================================
# WebSocket endpoint
# ============================================================

@router.websocket("/playground/ws")
async def playground_ws(websocket: WebSocket) -> None:
    await websocket.accept()

    if not state.gemini_api_key:
        await _safe_send(websocket, {
            "type": "error",
            "message": "Gemini API key not configured. Set it in Settings.",
        })
        await websocket.close()
        return

    # The first message must be a "start" with the run config.
    try:
        first = await asyncio.wait_for(websocket.receive_json(), timeout=10.0)
    except Exception:
        await websocket.close()
        return

    if first.get("type") != "start":
        await _safe_send(websocket, {"type": "error", "message": "expected start"})
        await websocket.close()
        return

    cameras: list[str] = list(first.get("cameras") or [])
    rule: str = (first.get("rule") or "").strip()
    scan: dict = first.get("scan") or {"mode": "periodic", "period_s": 30}
    action: Optional[dict] = first.get("action") or None
    cooldown_s: float = float(first.get("cooldown_s") or 0)
    model_selector: str = (first.get("model") or "").strip()

    if not cameras:
        await _safe_send(websocket, {"type": "error", "message": "Pick at least one camera."})
        await websocket.close()
        return
    if not rule:
        await _safe_send(websocket, {"type": "error", "message": "Provide a rule."})
        await websocket.close()
        return

    provider, requested_model = _parse_model_selector(model_selector)
    if provider == "ollama" and not ollama_client.is_configured():
        await _safe_send(websocket, {
            "type": "error",
            "message": "Ollama URL not configured. Set it in Settings → Ollama.",
        })
        await websocket.close()
        return

    # Dedicated client for this playground session — separate from any other
    # session in the app. Cleaned up when the WS closes.
    client = genai.Client(api_key=state.gemini_api_key)

    # Resolve the Gemini default once per session — used both as the fallback
    # for `gemini:` (with no specific model) and to label the ready message.
    gemini_default = ""
    try:
        gemini_default, candidates = await _resolve_vision_model(client)
    except Exception:
        candidates = []

    if provider == "ollama":
        display = f"Ollama · {requested_model}"
        ready_payload = {"type": "ready", "model": display, "provider": "ollama"}
    else:
        chosen = requested_model or gemini_default
        display = f"Gemini · {chosen}" if chosen else "Gemini"
        ready_payload = {"type": "ready", "model": display, "provider": "gemini", "candidates_tried": candidates}
    logger.info("ai-camera playground using %s", display)
    await _safe_send(websocket, ready_payload)

    stop_evt = asyncio.Event()
    ctx = _RunContext(scan, cameras)

    async def emit_countdown():
        """Send the current scan countdown to the client every second so the
        UI can render a live 'next scan in N s' chip. Skipped for modes
        without a countdown (motion, entity_state)."""
        while not stop_evt.is_set():
            cd = ctx.countdown()
            if cd is not None:
                await _safe_send(websocket, {"type": "countdown", **cd})
            try:
                await asyncio.wait_for(stop_evt.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                pass

    async def watch_stop():
        try:
            while True:
                msg = await websocket.receive_text()
                try:
                    data = json.loads(msg)
                except Exception:
                    continue
                if data.get("type") == "stop":
                    stop_evt.set()
                    return
        except WebSocketDisconnect:
            stop_evt.set()
        except Exception:
            stop_evt.set()

    async def run_loop():
        iter_id = 0
        last_action_ts = 0.0
        gen = _trigger_stream(ctx)
        try:
            while not stop_evt.is_set():
                # Either get a trigger or be cancelled by stop_evt.
                get_task = asyncio.create_task(gen.__anext__())
                stop_task = asyncio.create_task(stop_evt.wait())
                done, pending = await asyncio.wait(
                    {get_task, stop_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for t in pending: t.cancel()
                if stop_evt.is_set():
                    return
                try:
                    reason = get_task.result()
                except StopAsyncIteration:
                    return

                iter_id += 1
                try:
                    result = await _run_iteration(
                        websocket, client, gemini_default, model_selector,
                        rule, iter_id, cameras, reason,
                    )
                except Exception as e:
                    logger.exception("iteration error")
                    await _safe_send(websocket, {
                        "type": "iteration_error",
                        "iteration_id": iter_id,
                        "error": f"{type(e).__name__}: {e}",
                    })
                    continue
                if not result:
                    continue

                await _safe_send(websocket, {
                    "type": "iteration_result",
                    **result,
                })

                # Fire the action when the rule is satisfied (with cooldown).
                if result["triggered"] and action:
                    now = time.time()
                    if cooldown_s and (now - last_action_ts) < cooldown_s:
                        await _safe_send(websocket, {
                            "type": "action_cooldown",
                            "iteration_id": iter_id,
                            "remaining_s": cooldown_s - (now - last_action_ts),
                        })
                    else:
                        last_action_ts = now
                        try:
                            out = await _ha_call_service(action)
                            await _safe_send(websocket, {
                                "type": "action_executed",
                                "iteration_id": iter_id,
                                "action": action,
                                "result": out,
                            })
                        except Exception as e:
                            await _safe_send(websocket, {
                                "type": "action_error",
                                "iteration_id": iter_id,
                                "action": action,
                                "error": f"{type(e).__name__}: {e}",
                            })
        finally:
            try:
                await gen.aclose()
            except Exception:
                pass

    try:
        await asyncio.gather(run_loop(), watch_stop(), emit_countdown())
    except WebSocketDisconnect:
        return
    except Exception as e:
        logger.exception("playground fatal")
        await _safe_send(websocket, {"type": "error", "message": f"{type(e).__name__}: {e}"})
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


# ============================================================
# Helpers
# ============================================================

async def _safe_send(ws: WebSocket, payload: dict) -> None:
    try:
        await ws.send_text(json.dumps(payload))
    except Exception:
        pass


# ============================================================
# Test AI Model — free-form vision Q&A page
#
# Independent of the rules engine and the Playground WS: a one-shot REST
# endpoint that accepts an image + prompt + provider/model and returns the
# model's free-text reply. Used by the AI-Camera → Test AI Model page.
# ============================================================

@router.get("/test/models")
async def test_list_models() -> dict[str, list[dict]]:
    """Return vision-capable models grouped by provider for the Test page picker."""
    out: dict[str, list[dict]] = {"gemini": [], "ollama": []}

    # Gemini — list from the user's account, filter to non-Live generateContent.
    if state.gemini_api_key:
        try:
            client = genai.Client(api_key=state.gemini_api_key)
            async for m in await client.aio.models.list():
                actions = list(getattr(m, "supported_actions", None) or [])
                if "generateContent" not in actions:
                    continue
                name = (getattr(m, "name", "") or "").split("/")[-1]
                if not name or "-live" in name:
                    continue
                out["gemini"].append({
                    "name": name,
                    "display_name": getattr(m, "display_name", None) or name,
                })
            # Newest-ish first by name.
            out["gemini"].sort(key=lambda x: x["name"], reverse=True)
        except Exception as e:
            logger.warning("test/models gemini list failed: %s", e)

    # Ollama — local installed models.
    if ollama_client.is_configured():
        try:
            ms = await ollama_client.list_models()
            out["ollama"] = [{"name": m["name"], "display_name": m["name"]} for m in ms]
        except Exception as e:
            logger.warning("test/models ollama list failed: %s", e)

    return out


@router.post("/test/ask")
async def test_ask(
    provider: str = Form(...),
    model: str = Form(...),
    prompt: str = Form(...),
    image: UploadFile = File(...),
) -> dict:
    """Single-shot vision Q&A. Returns free text, *not* a JSON verdict."""
    provider = (provider or "").strip().lower()
    model = (model or "").strip()
    prompt = (prompt or "").strip()
    if provider not in ("gemini", "ollama"):
        raise HTTPException(status_code=400, detail="provider must be 'gemini' or 'ollama'")
    if not model:
        raise HTTPException(status_code=400, detail="model is required")
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is required")

    img_bytes = await image.read()
    if not img_bytes:
        raise HTTPException(status_code=400, detail="image upload is empty")
    mime = image.content_type or "image/jpeg"

    started = time.time()

    if provider == "gemini":
        if not state.gemini_api_key:
            raise HTTPException(status_code=503, detail="Gemini API key not configured")
        try:
            client = genai.Client(api_key=state.gemini_api_key)
            parts = [
                types.Part(inline_data=types.Blob(data=img_bytes, mime_type=mime)),
                types.Part(text=prompt),
            ]
            response = await client.aio.models.generate_content(
                model=model,
                contents=[types.Content(role="user", parts=parts)],
            )
            text = (response.text or "").strip()
            return {
                "ok": True,
                "provider": "gemini",
                "model": model,
                "text": text,
                "latency_ms": int((time.time() - started) * 1000),
            }
        except Exception as e:
            logger.warning("test/ask gemini failed: %s", e)
            return {
                "ok": False,
                "provider": "gemini",
                "model": model,
                "error": f"{type(e).__name__}: {e}",
                "latency_ms": int((time.time() - started) * 1000),
            }

    # Ollama
    if not ollama_client.is_configured():
        raise HTTPException(status_code=503, detail="Ollama URL not configured")
    res = await ollama_client.generate_text(model=model, prompt=prompt, images=[img_bytes])
    return {
        "ok": bool(res.get("ok")),
        "provider": "ollama",
        "model": model,
        "text": res.get("text") or "",
        "error": res.get("error"),
        "latency_ms": int((time.time() - started) * 1000),
    }
