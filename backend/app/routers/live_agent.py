"""
Live Agent — bridges the browser to the Gemini Live API.

Flow:
    Browser  <--WebSocket-->  this backend  <--SDK-->  Gemini Live API

The browser opens a WebSocket to /api/live-agent/ws. We forward:
- microphone audio (PCM 16 kHz mono)  ─►  Gemini realtime input
- selected camera frames (JPEG)       ─►  Gemini realtime input
- text turns                          ─►  Gemini client content

Gemini sends back:
- audio chunks (PCM 24 kHz mono)      ─►  forwarded as base64 to the browser
- text deltas                         ─►  forwarded as text to the browser
- function calls (Home Assistant)     ─►  executed locally via the HA router
                                          and the result is returned to Gemini
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import traceback
from typing import Any, Optional

import httpx
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from google import genai
from google.genai import types

from ..core.state import state
from ..knowledge import homeassistant as ha_knowledge

logger = logging.getLogger("live_agent")
router = APIRouter()

# ---------------------------------------------------------------------------
# Config endpoints
# ---------------------------------------------------------------------------

class LiveConfigIn(BaseModel):
    api_key: Optional[str] = None
    model:   Optional[str] = None


class LiveConfigOut(BaseModel):
    api_key_set: bool = False
    model:       str  = ""


@router.get("/config", response_model=LiveConfigOut)
async def get_config() -> LiveConfigOut:
    return LiveConfigOut(
        api_key_set=bool(state.gemini_api_key),
        model=state.gemini_model,
    )


@router.post("/config", response_model=LiveConfigOut)
async def set_config(payload: LiveConfigIn) -> LiveConfigOut:
    if payload.api_key is not None:
        state.gemini_api_key = payload.api_key.strip() or None
    if payload.model is not None and payload.model.strip():
        state.gemini_model = payload.model.strip()
    state.save()
    return LiveConfigOut(
        api_key_set=bool(state.gemini_api_key),
        model=state.gemini_model,
    )


# ---------------------------------------------------------------------------
# Tool definitions exposed to Gemini
# ---------------------------------------------------------------------------

def _build_function_declarations() -> list[types.FunctionDeclaration]:
    return [
        types.FunctionDeclaration(
            name="list_home_assistant_entities",
            description=(
                "List Home Assistant entities. Use this to discover devices before controlling them. "
                "Pass `query` to search by name fragment — matches against entity_id and friendly_name "
                "(case-insensitive substring). Pass `domain` to narrow by domain. Combine both."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "domain": types.Schema(
                        type=types.Type.STRING,
                        description="Optional domain filter: light, switch, climate, fan, cover, lock, scene, script, etc.",
                    ),
                    "query": types.Schema(
                        type=types.Type.STRING,
                        description=(
                            "Optional case-insensitive substring to search in entity_id and friendly_name. "
                            "Examples: 'kitchen', 'operation room', 'bedroom lamp'. "
                            "If the user mentions an area or room, search for it here."
                        ),
                    ),
                },
            ),
        ),
        types.FunctionDeclaration(
            name="list_home_assistant_areas",
            description=(
                "List the named Home Assistant areas (rooms / zones) and the entities in each. "
                "Use this when the user references a room or area by name (e.g. 'turn off the kitchen'). "
                "After finding the area's entities, pass them as a list to call_home_assistant_service."
            ),
            parameters=types.Schema(type=types.Type.OBJECT, properties={}),
        ),
        types.FunctionDeclaration(
            name="get_home_assistant_entity",
            description="Get the current state and attributes of a single Home Assistant entity.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "entity_id": types.Schema(type=types.Type.STRING, description="e.g. light.kitchen_ceiling"),
                },
                required=["entity_id"],
            ),
        ),
        types.FunctionDeclaration(
            name="call_home_assistant_service",
            description=(
                "Call a Home Assistant service to control one or more entities. "
                "Use this for every state change: turning lights on/off, setting brightness or color, "
                "opening covers, changing thermostats, running scripts/automations, etc. "
                "Pass entity_ids as a LIST so you can act on multiple entities (e.g. all kitchen lights) "
                "in a single call. Use list_home_assistant_entities or list_home_assistant_areas first if "
                "you don't already know which entity ids to use."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "domain":  types.Schema(type=types.Type.STRING, description="e.g. light, switch, climate"),
                    "service": types.Schema(type=types.Type.STRING, description="e.g. turn_on, turn_off, set_temperature, set_cover_position"),
                    "entity_ids": types.Schema(
                        type=types.Type.ARRAY,
                        items=types.Schema(type=types.Type.STRING),
                        description="One or more entity ids, e.g. ['light.kitchen_main'] or ['light.a','light.b']. Always use a list, even for a single entity.",
                    ),
                    "service_data": types.Schema(
                        type=types.Type.OBJECT,
                        description=(
                            "Additional service-specific parameters. Examples: "
                            "{brightness_pct: 50}, {rgb_color: [255,180,100]}, "
                            "{temperature: 22, hvac_mode: 'cool'}, {position: 60}. "
                            "Only include parameters you actually want to set; do not mix mutually exclusive options."
                        ),
                    ),
                },
                required=["domain", "service", "entity_ids"],
            ),
        ),
    ]


def _build_system_instruction() -> str:
    lines = [
        "You are a real-time voice assistant for a smart home, integrated with Home Assistant and Frigate camera DVR.",
        "",
        "Speak conversationally. Keep replies short. When the user asks you to do something, do it — don't describe what you're about to do at length.",
        "",
        "## Capabilities",
        "- You can list and control Home Assistant entities via tool calls.",
        "- You may receive frames from a security camera. Reason about what you see and answer questions about the scene.",
        "",
        "## Home Assistant capability catalog",
        "Below is the curated catalog of what each domain supports. Use it to pick the right `domain`, `service`, and `service_data`.",
        "Required: don't mix mutually exclusive light parameters (brightness OR brightness_pct OR rgb_color OR color_temp OR kelvin — pick one).",
        "",
    ]
    for domain, cap in sorted(ha_knowledge.DOMAIN_CAPABILITIES.items()):
        if cap.get("read_only"):
            continue
        services = cap.get("services", {}) or {}
        if not services:
            continue
        lines.append(f"### {domain} — {cap.get('description', '')}")
        for svc, sd in services.items():
            if svc == "*":
                continue
            params = sd.get("params", []) or []
            param_bits = []
            for p in params:
                bit = p["name"] + ("?" if p.get("optional") else "")
                if p.get("range"):
                    bit += f"[{p['range'][0]}..{p['range'][1]}]"
                elif p.get("choices"):
                    bit += f"<{'|'.join(p['choices'])}>"
                param_bits.append(bit)
            sig = ", ".join(param_bits) if param_bits else ""
            lines.append(f"  - `{domain}.{svc}({sig})` — {sd.get('description','')}")
        lines.append("")
    lines += [
        "",
        "## Visibility filter — 'Only Areas'",
        "The user has a toggle called 'Only Areas'. When ON, every tool below sees ONLY entities "
        "that have been assigned to a Home Assistant Area; entities not in any Area are invisible "
        "to you and any attempt to control them will be rejected. When OFF, you see all entities. "
        "You CANNOT see the toggle state directly — instead, every tool result includes a `scope` "
        "field (\"only_areas\" or \"all\") and a `count` you can rely on. The toggle can change "
        "during the conversation: never assume the previous tool result is still valid.",
        "",
        "## Counting & listing — always call tools fresh",
        "When the user asks about counts ('how many lights are on?', 'how many entities do I have?', "
        "'list my switches'), you MUST call the relevant tool *in the current turn*. Never reuse a "
        "number from earlier — the filter can have changed, or the state can have changed. State the "
        "filter scope in your answer (e.g. 'You have 80 lights in areas' vs '150 lights total').",
        "",
        "## Finding the right entities",
        "Users rarely use exact entity ids. They say things like 'kitchen lights', 'operation room hallway', "
        "'upstairs bedroom'. Resolve these by:",
        "  1. If the user names a room or zone, call list_home_assistant_areas first. Match the area "
        "     by name fuzzily (case-insensitive). Pick all entities of the relevant domain from that area.",
        "  2. Otherwise, call list_home_assistant_entities with a `query` substring (e.g. 'operation room') "
        "     and `domain` (e.g. 'light') to narrow the result set.",
        "  3. Then call_home_assistant_service ONCE with `entity_ids` as a list of every entity you matched. "
        "     Do NOT issue one call per entity if you can batch.",
        "",
        "## Examples",
        "- User: 'turn off the kitchen lights'",
        "  → list_home_assistant_areas → find area named 'Kitchen', take its light.* entities",
        "  → call_home_assistant_service(domain='light', service='turn_off', entity_ids=[...all matched...])",
        "",
        "- User: 'set operation room hallway lights to 30%'",
        "  → list_home_assistant_entities(domain='light', query='operation room hallway')",
        "  → call_home_assistant_service(domain='light', service='turn_on',",
        "       entity_ids=[...matched...], service_data={'brightness_pct': 30})",
        "",
        "- User: 'how many lights are on?'",
        "  → list_home_assistant_entities(domain='light')  — count entities with state == 'on'",
        "",
        "Confirm important destructive actions (locks, alarm, garage doors) before triggering them. "
        "If a query returns no matches, say so plainly and ask the user to clarify.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool execution — talks to the local HA backend
# ---------------------------------------------------------------------------

class _HaError(Exception):
    pass


async def _ha_get(path: str, params: Optional[dict] = None) -> Any:
    if not state.homeassistant_url or not state.homeassistant_token:
        raise _HaError("Home Assistant is not configured.")
    headers = {"Authorization": f"Bearer {state.homeassistant_token}"}
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
        r = await client.get(f"{state.homeassistant_url}/api{path}", headers=headers, params=params or {})
        r.raise_for_status()
        return r.json() if r.content else None


async def _ha_post(path: str, json_body: dict) -> Any:
    if not state.homeassistant_url or not state.homeassistant_token:
        raise _HaError("Home Assistant is not configured.")
    headers = {
        "Authorization": f"Bearer {state.homeassistant_token}",
        "Content-Type":  "application/json",
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
        r = await client.post(f"{state.homeassistant_url}/api{path}", headers=headers, json=json_body)
        r.raise_for_status()
        return r.json() if r.content else None


_AREAS_TEMPLATE = (
    "[{% for a in areas() %}"
    "{\"id\": {{ a | tojson }}, "
    "\"name\": {{ area_name(a) | tojson }}, "
    "\"entities\": {{ area_entities(a) | tojson }}}"
    "{% if not loop.last %},{% endif %}"
    "{% endfor %}]"
)


async def _ha_render_template(template: str) -> Any:
    """Render a Jinja2 template against HA state and return its parsed JSON."""
    if not state.homeassistant_url or not state.homeassistant_token:
        raise _HaError("Home Assistant is not configured.")
    headers = {
        "Authorization": f"Bearer {state.homeassistant_token}",
        "Content-Type":  "application/json",
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
        r = await client.post(
            f"{state.homeassistant_url}/api/template",
            headers=headers,
            json={"template": template},
        )
        r.raise_for_status()
        text = r.text.strip()
    # Template returns plain text; we tojson'd it server-side.
    try:
        return json.loads(text)
    except Exception:
        return text


async def _refresh_area_entity_ids() -> set[str]:
    """Set of entity_ids that belong to *any* HA area. Used to filter tool
    outputs when the session's only_areas flag is on."""
    try:
        data = await _ha_render_template(_AREAS_TEMPLATE)
    except Exception:
        return set()
    # _ha_render_template returns either a parsed object (when JSON-parseable)
    # or the raw text. Accept both.
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:
            return set()
    out: set[str] = set()
    if isinstance(data, list):
        for a in data:
            if not isinstance(a, dict):
                continue
            for eid in (a.get("entities") or []):
                if isinstance(eid, str):
                    out.add(eid)
    return out


async def _execute_tool(name: str, args: dict, ctx: dict) -> dict:
    only_areas = bool(ctx.get("only_areas"))
    area_ids: Optional[set[str]] = ctx.get("area_entity_ids") if only_areas else None

    try:
        # -------- list_home_assistant_entities -----------------------------
        if name == "list_home_assistant_entities":
            data = await _ha_get("/states")
            if not isinstance(data, list):
                return {"error": "Unexpected HA response."}
            domain_filter = (args.get("domain") or "").strip().lower() or None
            query = (args.get("query") or "").strip().lower() or None
            simplified = []
            for ent in data:
                eid = ent.get("entity_id", "")
                if area_ids is not None and eid not in area_ids:
                    continue
                ent_domain = eid.split(".", 1)[0] if "." in eid else ""
                if domain_filter and ent_domain != domain_filter:
                    continue
                friendly = (ent.get("attributes") or {}).get("friendly_name") or eid
                if query:
                    hay = f"{eid} {friendly}".lower()
                    if query not in hay:
                        continue
                simplified.append({
                    "entity_id": eid,
                    "domain":    ent_domain,
                    "state":     ent.get("state"),
                    "name":      friendly,
                })
            return {
                "scope":     "only_areas" if only_areas else "all",
                "count":     len(simplified),
                "entities":  simplified[:200],
                "truncated": len(simplified) > 200,
            }

        # -------- list_home_assistant_areas --------------------------------
        if name == "list_home_assistant_areas":
            areas = await _ha_render_template(_AREAS_TEMPLATE)
            if not isinstance(areas, list):
                return {"error": "Area template did not return a list", "raw": areas}
            # Decorate each entity with friendly_name + state for usability.
            try:
                states = await _ha_get("/states")
                idx = {
                    s.get("entity_id"): {
                        "state": s.get("state"),
                        "name":  (s.get("attributes") or {}).get("friendly_name") or s.get("entity_id"),
                    }
                    for s in (states or []) if isinstance(s, dict)
                }
            except Exception:
                idx = {}
            for a in areas:
                ents = a.get("entities") or []
                a["entities"] = [
                    {"entity_id": eid, **(idx.get(eid) or {"state": None, "name": eid})}
                    for eid in ents
                ]
            return {"count": len(areas), "areas": areas}

        # -------- get_home_assistant_entity --------------------------------
        if name == "get_home_assistant_entity":
            eid = args.get("entity_id")
            if not eid:
                return {"error": "entity_id is required."}
            if area_ids is not None and eid not in area_ids:
                return {"error": f"{eid} is not assigned to any HA Area. Only-Areas filter is active."}
            data = await _ha_get(f"/states/{eid}")
            return {
                "entity_id":   data.get("entity_id"),
                "state":       data.get("state"),
                "attributes":  data.get("attributes"),
                "last_changed": data.get("last_changed"),
            }

        # -------- call_home_assistant_service ------------------------------
        if name == "call_home_assistant_service":
            domain  = args.get("domain")
            service = args.get("service")
            # Accept both `entity_ids` (new, list) and `entity_id` (legacy).
            eids = args.get("entity_ids")
            if eids is None:
                eids = args.get("entity_id")
            if isinstance(eids, str):
                eids = [eids]
            if not (domain and service and eids):
                return {"error": "domain, service, and entity_ids are all required."}
            if area_ids is not None:
                rejected = [e for e in eids if e not in area_ids]
                if rejected:
                    return {
                        "error": f"Refusing to act on entities not assigned to an HA Area: {rejected}. Only-Areas filter is active.",
                    }
            sd = args.get("service_data") or {}
            body: dict[str, Any] = {"entity_id": eids}
            if isinstance(sd, dict):
                body.update({k: v for k, v in sd.items() if v is not None})
            result = await _ha_post(f"/services/{domain}/{service}", body)
            return {"ok": True, "called": f"{domain}.{service}", "args": body, "result": result}

        return {"error": f"Unknown tool: {name}"}

    except _HaError as e:
        return {"error": str(e)}
    except httpx.HTTPStatusError as e:
        return {"error": f"HA HTTP {e.response.status_code}: {e.response.text[:200]}"}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


# ---------------------------------------------------------------------------
# WebSocket bridge
# ---------------------------------------------------------------------------

# Gemini Live model id is configurable via state.gemini_model.
# v1alpha is the API version that exposes Live.
_GEMINI_API_VERSION = "v1alpha"


@router.websocket("/ws")
async def live_agent_ws(websocket: WebSocket) -> None:
    await websocket.accept()

    if not state.gemini_api_key:
        await _safe_send_json(websocket, {"type": "error", "message": "Gemini API key not configured. Set it in Settings."})
        await websocket.close()
        return

    client = genai.Client(
        api_key=state.gemini_api_key,
        http_options={"api_version": _GEMINI_API_VERSION},
    )

    tools = [types.Tool(function_declarations=_build_function_declarations())]
    config = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        system_instruction=types.Content(
            parts=[types.Part(text=_build_system_instruction())],
        ),
        tools=tools,
        # Surface what the model hears (our mic) and what it says (its TTS)
        # so the UI can show a live transcript and we can diagnose audio issues.
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
    )

    # Per-session context, mutated by config messages from the client.
    ctx: dict[str, Any] = {
        "only_areas":      False,
        "area_entity_ids": None,  # set when only_areas is turned on
        "notified_initial_filter": False,
    }

    try:
        async with client.aio.live.connect(model=state.gemini_model, config=config) as session:
            await _safe_send_json(websocket, {"type": "ready", "model": state.gemini_model})

            from_client = asyncio.create_task(_pump_client_to_gemini(websocket, session, ctx))
            from_server = asyncio.create_task(_pump_gemini_to_client(websocket, session, ctx))

            done, pending = await asyncio.wait(
                {from_client, from_server},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()
            for t in done:
                exc = t.exception()
                if exc and not isinstance(exc, WebSocketDisconnect):
                    logger.error("Live agent task error: %r", exc)
                    await _safe_send_json(websocket, {"type": "error", "message": f"{type(exc).__name__}: {exc}"})

    except WebSocketDisconnect:
        return
    except Exception as e:
        logger.error("Live agent fatal: %s\n%s", e, traceback.format_exc())
        await _safe_send_json(websocket, {"type": "error", "message": f"{type(e).__name__}: {e}"})
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


async def _pump_client_to_gemini(websocket: WebSocket, session: Any, ctx: dict) -> None:
    """Forward client messages to Gemini Live."""
    while True:
        raw = await websocket.receive_text()
        try:
            msg = json.loads(raw)
        except Exception:
            continue

        mtype = msg.get("type")

        if mtype == "config":
            # Client can toggle per-session options without reconnecting.
            if "only_areas" in msg:
                old = bool(ctx.get("only_areas"))
                new = bool(msg["only_areas"])
                ctx["only_areas"] = new
                count_note = ""
                if new:
                    ctx["area_entity_ids"] = await _refresh_area_entity_ids()
                    count_note = f" ({len(ctx['area_entity_ids'])} entities are in Areas)"
                else:
                    ctx["area_entity_ids"] = None

                # Tell the model the filter just changed so it doesn't keep
                # answering with stale counts from a prior tool call.
                if old != new:
                    note = (
                        f"(system) Only-Areas filter just turned {'ON' if new else 'OFF'}{count_note}. "
                        f"The set of entities your tools see has changed. "
                        f"If asked about counts or which entities exist, call the relevant tool again "
                        f"to get fresh data — do not reuse a number from earlier in this conversation."
                    )
                    try:
                        await session.send_client_content(
                            turns=types.Content(role="user", parts=[types.Part(text=note)]),
                            turn_complete=False,
                        )
                    except Exception as e:
                        logger.warning("filter-change notice failed: %s", e)

                await _safe_send_json(websocket, {
                    "type": "config_ack",
                    "only_areas": new,
                    "area_entity_count": len(ctx["area_entity_ids"]) if new else None,
                })
            continue

        if mtype == "audio":
            data = base64.b64decode(msg.get("data") or "")
            if not data:
                continue
            # Newer Live API: typed `audio=` blob (replaces deprecated `media=`).
            await session.send_realtime_input(
                audio=types.Blob(data=data, mime_type="audio/pcm;rate=16000"),
            )

        elif mtype == "video":
            data = base64.b64decode(msg.get("data") or "")
            if not data:
                continue
            mime = msg.get("mime") or "image/jpeg"
            await session.send_realtime_input(
                video=types.Blob(data=data, mime_type=mime),
            )

        elif mtype == "text":
            text = msg.get("text") or ""
            if not text.strip():
                continue
            await session.send_client_content(
                turns=types.Content(role="user", parts=[types.Part(text=text)]),
                turn_complete=True,
            )

        elif mtype == "end_audio":
            # Signal end-of-turn for the audio stream so Gemini commits the turn.
            try:
                await session.send_realtime_input(audio_stream_end=True)
            except TypeError:
                pass


async def _pump_gemini_to_client(websocket: WebSocket, session: Any, ctx: dict) -> None:
    """Forward Gemini responses (audio, text, tool calls) back to the client.

    NB: `session.receive()` in this SDK yields one turn and stops at
    turn_complete. We loop so the session stays open for the full conversation,
    exiting only when the underlying WebSocket to Gemini closes (which raises
    from inside the iterator)."""
    while True:
        async for response in session.receive():
            # Tool calls — execute locally and send result back to Gemini.
            if getattr(response, "tool_call", None):
                tool_call = response.tool_call
                function_responses = []
                for fc in tool_call.function_calls or []:
                    args = dict(fc.args or {})
                    await _safe_send_json(websocket, {
                        "type": "tool_call",
                        "name": fc.name,
                        "args": args,
                    })
                    result = await _execute_tool(fc.name, args, ctx)
                    await _safe_send_json(websocket, {
                        "type": "tool_result",
                        "name": fc.name,
                        "result": result,
                    })
                    function_responses.append(
                        types.FunctionResponse(
                            id=fc.id,
                            name=fc.name,
                            response={"result": result},
                        )
                    )
                if function_responses:
                    await session.send_tool_response(function_responses=function_responses)

            # Audio data — Gemini returns 16-bit PCM mono @ 24kHz.
            data_bytes = getattr(response, "data", None)
            if data_bytes:
                await _safe_send_json(websocket, {
                    "type": "audio",
                    "data": base64.b64encode(data_bytes).decode("ascii"),
                })

            # Text deltas, when any.
            text = getattr(response, "text", None)
            if text:
                await _safe_send_json(websocket, {"type": "text", "text": text})

            # Server content events (e.g. turn_complete, interrupted, transcription).
            sc = getattr(response, "server_content", None)
            if sc:
                if getattr(sc, "turn_complete", False):
                    await _safe_send_json(websocket, {"type": "turn_complete"})
                if getattr(sc, "interrupted", False):
                    await _safe_send_json(websocket, {"type": "interrupted"})

                # Transcriptions enabled in LiveConnectConfig — these tell us
                # exactly what Gemini heard (input) and is saying (output).
                input_tx = getattr(sc, "input_transcription", None)
                if input_tx and getattr(input_tx, "text", None):
                    await _safe_send_json(websocket, {"type": "user_text", "text": input_tx.text})

                output_tx = getattr(sc, "output_transcription", None)
                if output_tx and getattr(output_tx, "text", None):
                    await _safe_send_json(websocket, {"type": "agent_text", "text": output_tx.text})

                # Some SDK versions also deliver text via server_content.model_turn.parts
                mt = getattr(sc, "model_turn", None)
                if mt:
                    for part in getattr(mt, "parts", []) or []:
                        pt = getattr(part, "text", None)
                        if pt:
                            await _safe_send_json(websocket, {"type": "text", "text": pt})


async def _safe_send_json(ws: WebSocket, payload: dict) -> None:
    try:
        await ws.send_text(json.dumps(payload))
    except Exception:
        # Connection went away.
        pass
