"""
SIP Live Assistant — bridges Asterisk/FreePBX calls to Gemini Live.

When a caller dials the configured FreePBX extension, Asterisk's dialplan
opens a TCP connection to this service via the `AudioSocket()` application
(chan_audiosocket). The AudioSocket protocol carries the caller's audio in
both directions as signed-linear 16-bit mono at 8 kHz; this service:

  1. Accepts the TCP connection.
  2. Reads the UUID frame Asterisk sends first.
  3. Opens a dedicated Gemini Live session (per-call) with the configured
     system prompt + voice.
  4. Streams 8 kHz mono → 16 kHz mono → Gemini realtime audio input.
  5. Streams Gemini's 24 kHz mono replies → 8 kHz mono → caller.
  6. Optionally calls Home Assistant tools (reusing live_agent's catalog)
     when Gemini decides to.
  7. Cleans up on hangup (caller drops, max_call_s elapsed, or service stop).

Architecture note: we do *not* speak SIP/RTP directly. AudioSocket
out-sources all of that to Asterisk — it negotiates the SIP INVITE,
manages RTP, transcodes codecs — and we just deal with cooked PCM frames
over a friendly TCP socket. Asterisk 18+ ships `app_audiosocket` and
`chan_audiosocket` in modules. See docs/LiveAssistantSIP.md.

Frame layout (per chan_audiosocket source):
    [TYPE:1][LEN:2 BE][PAYLOAD:LEN]
    TYPE 0x00 = Hangup
    TYPE 0x01 = UUID  (16 bytes, sent once at start)
    TYPE 0x02 = DTMF  (1 byte ASCII)
    TYPE 0x03 = Error (variable string)
    TYPE 0x10 = Audio (signed-linear 16-bit mono 8 kHz, big-endian SAMPLES on the wire
                       — actually little-endian per existing client impls; chan_audiosocket
                       hands the raw samples through)
"""
from __future__ import annotations

import asyncio
import audioop
import base64
import json
import logging
import struct
import time
import uuid
from typing import Any, Optional

import httpx

from google import genai
from google.genai import types

from ..core.state import state
from ..knowledge import homeassistant as ha_knowledge
from ..routers.ai_camera import _fetch_frigate_snapshot

logger = logging.getLogger("sip_live_agent")

# AudioSocket message types (chan_audiosocket).
_AS_HANGUP = 0x00
_AS_UUID   = 0x01
_AS_DTMF   = 0x02
_AS_ERROR  = 0x03
_AS_AUDIO  = 0x10

# AudioSocket carries signed-linear 16-bit @ 8 kHz mono, 20 ms frames =
# 160 samples = 320 bytes. We just pass whatever lengths the wire reports.
_SAMPLE_WIDTH = 2

_GEMINI_API_VERSION = "v1alpha"


# ============================================================
# HA tool execution — mirrors live_agent.py so the SIP agent can drive
# Home Assistant the same way the voice page can.
# ============================================================

async def _ha_get(path: str, params: Optional[dict] = None) -> Any:
    if not state.homeassistant_url or not state.homeassistant_token:
        raise RuntimeError("Home Assistant is not configured.")
    headers = {"Authorization": f"Bearer {state.homeassistant_token}"}
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
        r = await client.get(f"{state.homeassistant_url}/api{path}",
                             headers=headers, params=params or {})
        r.raise_for_status()
        return r.json() if r.content else None


async def _ha_post(path: str, body: dict) -> Any:
    if not state.homeassistant_url or not state.homeassistant_token:
        raise RuntimeError("Home Assistant is not configured.")
    headers = {
        "Authorization": f"Bearer {state.homeassistant_token}",
        "Content-Type":  "application/json",
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
        r = await client.post(f"{state.homeassistant_url}/api{path}",
                              headers=headers, json=body)
        r.raise_for_status()
        return r.json() if r.content else None


def _ha_tool_declarations() -> list[types.FunctionDeclaration]:
    return [
        types.FunctionDeclaration(
            name="list_home_assistant_entities",
            description="List HA entities, optionally filtered by domain or substring search.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "domain": types.Schema(type=types.Type.STRING),
                    "query":  types.Schema(type=types.Type.STRING),
                },
            ),
        ),
        types.FunctionDeclaration(
            name="call_home_assistant_service",
            description="Control one or more HA entities via a service call.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "domain":  types.Schema(type=types.Type.STRING),
                    "service": types.Schema(type=types.Type.STRING),
                    "entity_ids": types.Schema(
                        type=types.Type.ARRAY,
                        items=types.Schema(type=types.Type.STRING),
                    ),
                    "service_data": types.Schema(type=types.Type.OBJECT),
                },
                required=["domain", "service", "entity_ids"],
            ),
        ),
    ]


def _build_system_instruction() -> str:
    base = (state.sla_system_prompt or "").strip()
    cams = list(state.sla_cameras or [])
    if cams:
        base = (
            base + "\n\n"
            "## Camera vision\n"
            f"You also receive live video frames every ~1 s from these Frigate cameras: "
            f"{', '.join(cams)}.\n"
            "Frames arrive in round-robin order. When the caller asks what you see, "
            "describe the most recent frame plainly and reference the camera by name. "
            "If the caller asks about a specific camera not in the list above, say so."
        )
    if not state.sla_enable_ha_tools:
        return base
    lines = [base, "", "## Home Assistant capability catalog"]
    for domain, cap in sorted(ha_knowledge.DOMAIN_CAPABILITIES.items()):
        if cap.get("read_only"): continue
        services = cap.get("services", {}) or {}
        if not services: continue
        lines.append(f"### {domain} — {cap.get('description','')}")
        for svc, sd in services.items():
            if svc == "*": continue
            lines.append(f"  - `{domain}.{svc}` — {sd.get('description','')}")
        lines.append("")
    lines.append(
        "When asked about counts or which entities exist, ALWAYS call "
        "list_home_assistant_entities fresh. Use call_home_assistant_service "
        "with entity_ids as a list to act on multiple entities in one call."
    )
    return "\n".join(lines)


async def _execute_tool(name: str, args: dict, ctx: dict) -> dict:
    only_areas: bool = bool(ctx.get("only_areas"))
    area_ids: Optional[set[str]] = ctx.get("area_entity_ids") if only_areas else None
    try:
        if name == "list_home_assistant_entities":
            data = await _ha_get("/states")
            domain_filter = (args.get("domain") or "").strip().lower() or None
            query = (args.get("query") or "").strip().lower() or None
            out = []
            for ent in (data or []):
                eid = ent.get("entity_id", "")
                if area_ids is not None and eid not in area_ids:
                    continue
                ent_domain = eid.split(".", 1)[0] if "." in eid else ""
                if domain_filter and ent_domain != domain_filter:
                    continue
                friendly = (ent.get("attributes") or {}).get("friendly_name") or eid
                if query and query not in f"{eid} {friendly}".lower():
                    continue
                out.append({
                    "entity_id": eid, "domain": ent_domain,
                    "state": ent.get("state"), "name": friendly,
                })
            return {"count": len(out), "entities": out[:200]}

        if name == "call_home_assistant_service":
            domain  = args.get("domain")
            service = args.get("service")
            eids    = args.get("entity_ids") or []
            if isinstance(eids, str): eids = [eids]
            if not (domain and service and eids):
                return {"error": "domain, service, entity_ids required."}
            if area_ids is not None:
                rejected = [e for e in eids if e not in area_ids]
                if rejected:
                    return {"error": f"Entities not in any HA Area: {rejected}"}
            body: dict[str, Any] = {"entity_id": eids}
            sd = args.get("service_data") or {}
            if isinstance(sd, dict):
                body.update({k: v for k, v in sd.items() if v is not None})
            r = await _ha_post(f"/services/{domain}/{service}", body)
            return {"ok": True, "called": f"{domain}.{service}", "result": r}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
    return {"error": f"Unknown tool: {name}"}


# ============================================================
# CallSession — one TCP connection from Asterisk = one call = one Gemini Live session
# ============================================================

class CallSession:
    def __init__(self, call_id: str, peer: str,
                 reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
                 svc: "SipLiveAgentService"):
        self.call_id = call_id
        self.peer = peer
        self.reader = reader
        self.writer = writer
        self.svc = svc
        self.uuid: Optional[str] = None
        self.started_at = time.time()
        self.audio_in: asyncio.Queue = asyncio.Queue(maxsize=200)   # caller → Gemini, 16 kHz PCM
        self.audio_out: asyncio.Queue = asyncio.Queue(maxsize=200)  # Gemini → caller, 24 kHz PCM
        self.stop_evt = asyncio.Event()
        self._upstate = None    # audioop ratecv state for 8k→16k
        self._downstate = None  # audioop ratecv state for 24k→8k
        # Leftover sub-frame bytes carried between _write_loop iterations so
        # we never pad mid-stream — partial frames get glued onto the front
        # of the next chunk instead of being zero-padded out (which causes
        # audible "tong tong" clicks).
        self._out_leftover: bytes = b""
        # Monotonic "next frame should leave at" timestamp, kept across
        # _send_audio calls so 20 ms pacing is precise rather than drifting.
        self._next_send_at: Optional[float] = None
        # Half-duplex echo gate: while wall-clock < echo_until, the caller's
        # mic audio is NOT forwarded to Gemini. Prevents the agent's own
        # voice (played through the caller's speaker, picked up by the mic)
        # from triggering Gemini's VAD and self-interrupting.
        self.echo_until: float = 0.0
        self.heard_text = ""
        self.spoken_text = ""
        # Interleaved per-turn transcript. Each entry: {role, text, ts}.
        # role is "user" (caller) or "agent" (Gemini). A new turn starts
        # whenever the role flips between consecutive transcript chunks.
        self.turns: list[dict] = []

    # ------ wire protocol ------------------------------------------------
    @staticmethod
    async def _read_frame(reader: asyncio.StreamReader) -> tuple[int, bytes]:
        header = await reader.readexactly(3)
        msg_type = header[0]
        length = struct.unpack(">H", header[1:3])[0]
        payload = await reader.readexactly(length) if length else b""
        return msg_type, payload

    def _append_turn(self, role: str, text: str) -> None:
        """Extend the last turn if the role matches, else start a new one."""
        if self.turns and self.turns[-1]["role"] == role:
            self.turns[-1]["text"] += text
        else:
            self.turns.append({"role": role, "text": text, "ts": time.time()})

    async def _send_audio(self, pcm8k: bytes) -> None:
        # pcm8k is guaranteed to be a multiple of 320 bytes — see _write_loop
        # for the buffering that ensures this. Each 320-byte chunk is 20 ms
        # of slin audio; we pace them out at exactly 20 ms intervals using a
        # monotonic clock, otherwise drift accumulates and Asterisk's RTP
        # output ends up with rhythmic click artifacts.
        FRAME = 320
        n_frames = len(pcm8k) // FRAME
        if n_frames == 0:
            return
        # Open the half-duplex echo gate: while we're playing this clip plus
        # a 350 ms tail (room reverberation + phone AEC convergence), drop
        # whatever the caller's mic sends so Gemini doesn't hear its own
        # voice come back and VAD-interrupt itself.
        self.echo_until = max(
            self.echo_until, time.time() + n_frames * 0.020 + 0.35,
        )
        now = time.monotonic()
        if self._next_send_at is None or self._next_send_at < now - 0.05:
            # First frame ever, OR we fell behind by >50 ms — reset the
            # cadence so we don't try to "catch up" by sending bursts.
            self._next_send_at = now
        for i in range(0, len(pcm8k), FRAME):
            chunk = pcm8k[i:i + FRAME]
            self.writer.write(bytes([_AS_AUDIO]) + struct.pack(">H", len(chunk)) + chunk)
            await self.writer.drain()
            self._next_send_at += 0.020
            delay = self._next_send_at - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            else:
                # Yield to the event loop even when on-time / behind.
                await asyncio.sleep(0)

    async def _hangup(self) -> None:
        try:
            self.writer.write(bytes([_AS_HANGUP, 0, 0]))
            await self.writer.drain()
        except Exception:
            pass

    # ------ pumps --------------------------------------------------------
    async def _read_loop(self) -> None:
        """Asterisk → us. Reads frames forever; pushes 16 kHz PCM into audio_in."""
        try:
            while not self.stop_evt.is_set():
                msg_type, payload = await self._read_frame(self.reader)
                if msg_type == _AS_HANGUP:
                    logger.info("call %s: peer hangup", self.call_id)
                    self.stop_evt.set()
                    return
                if msg_type == _AS_UUID:
                    self.uuid = payload.hex()
                    continue
                if msg_type == _AS_DTMF:
                    digit = payload.decode("ascii", "replace") if payload else ""
                    logger.info("call %s: DTMF %s", self.call_id, digit)
                    continue
                if msg_type == _AS_ERROR:
                    logger.warning("call %s: peer error: %r", self.call_id, payload)
                    continue
                if msg_type == _AS_AUDIO and payload:
                    # Half-duplex: while the agent is speaking (or just
                    # finished), the caller's mic mostly contains the
                    # agent's own voice fed back through the phone speaker.
                    # Drop those frames so Gemini doesn't VAD-trigger on
                    # them and interrupt itself.
                    if time.time() < self.echo_until:
                        continue
                    pcm16k, self._upstate = audioop.ratecv(
                        payload, _SAMPLE_WIDTH, 1, 8000, 16000, self._upstate,
                    )
                    try:
                        self.audio_in.put_nowait(pcm16k)
                    except asyncio.QueueFull:
                        # Drop the oldest sample if we're stalled.
                        try: self.audio_in.get_nowait()
                        except Exception: pass
                        try: self.audio_in.put_nowait(pcm16k)
                        except Exception: pass
        except (asyncio.IncompleteReadError, ConnectionResetError):
            logger.info("call %s: read loop ended (connection)", self.call_id)
        finally:
            self.stop_evt.set()

    async def _write_loop(self) -> None:
        """us → Asterisk. Pulls Gemini's 24 kHz PCM, downsamples to 8 kHz,
        writes only complete 320-byte frames — leftover sub-frame bytes are
        carried into the next iteration via self._out_leftover so we never
        zero-pad mid-stream (which causes audible clicks at chunk seams)."""
        FRAME = 320
        try:
            while not self.stop_evt.is_set():
                try:
                    pcm24k = await asyncio.wait_for(self.audio_out.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                if pcm24k is None:
                    return
                pcm8k, self._downstate = audioop.ratecv(
                    pcm24k, _SAMPLE_WIDTH, 1, 24000, 8000, self._downstate,
                )
                if not pcm8k:
                    continue
                buf = self._out_leftover + pcm8k
                n_complete = (len(buf) // FRAME) * FRAME
                if n_complete:
                    await self._send_audio(buf[:n_complete])
                self._out_leftover = buf[n_complete:]
        except Exception as e:
            logger.warning("call %s: write loop ended: %s", self.call_id, e)

    async def _gemini_loop(self) -> None:
        """Open a Gemini Live session and bridge it to audio_in / audio_out."""
        if not state.gemini_api_key:
            logger.error("call %s: Gemini API key not set", self.call_id)
            return
        model = state.gemini_model
        client = genai.Client(api_key=state.gemini_api_key,
                              http_options={"api_version": _GEMINI_API_VERSION})

        tools = [types.Tool(function_declarations=_ha_tool_declarations())] if state.sla_enable_ha_tools else None
        cfg = types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            system_instruction=types.Content(
                parts=[types.Part(text=_build_system_instruction())]
            ),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=state.sla_voice or "Aoede",
                    ),
                ),
            ),
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            tools=tools,
        )

        ctx = {"only_areas": bool(state.sla_only_areas), "area_entity_ids": None}

        try:
            async with client.aio.live.connect(model=model, config=cfg) as session:
                logger.info("call %s: Gemini Live connected (model=%s)", self.call_id, model)

                # Optional greeting — synthesised by Gemini reading our text.
                if state.sla_greeting:
                    try:
                        await session.send_client_content(
                            turns=types.Content(role="user", parts=[
                                types.Part(text=f"(system) Greet the caller now with: {state.sla_greeting}")
                            ]),
                            turn_complete=True,
                        )
                    except Exception as e:
                        logger.warning("call %s: greeting failed: %s", self.call_id, e)

                async def feed():
                    while not self.stop_evt.is_set():
                        try:
                            chunk = await asyncio.wait_for(self.audio_in.get(), timeout=1.0)
                        except asyncio.TimeoutError:
                            continue
                        if not chunk:
                            continue
                        await session.send_realtime_input(
                            audio=types.Blob(data=chunk, mime_type="audio/pcm;rate=16000"),
                        )

                async def stream_cameras():
                    """Round-robin selected cameras at ~1 frame/sec/each so
                    Gemini gets fresh visual context throughout the call."""
                    cams = list(state.sla_cameras or [])
                    if not cams:
                        return
                    period = 1.0
                    idx = 0
                    while not self.stop_evt.is_set():
                        cam = cams[idx % len(cams)]
                        idx += 1
                        try:
                            jpg = await _fetch_frigate_snapshot(cam, height=480)
                            if jpg:
                                await session.send_realtime_input(
                                    video=types.Blob(data=jpg, mime_type="image/jpeg"),
                                )
                        except Exception:
                            logger.warning("call %s: camera %s frame failed", self.call_id, cam, exc_info=True)
                        await asyncio.sleep(period)

                async def receive():
                    while not self.stop_evt.is_set():
                        async for resp in session.receive():
                            data_bytes = getattr(resp, "data", None)
                            if data_bytes:
                                try:
                                    self.audio_out.put_nowait(data_bytes)
                                except asyncio.QueueFull:
                                    try: self.audio_out.get_nowait()
                                    except Exception: pass
                                    try: self.audio_out.put_nowait(data_bytes)
                                    except Exception: pass

                            sc = getattr(resp, "server_content", None)
                            if sc:
                                if getattr(sc, "interrupted", False):
                                    # Caller talked over the agent — drop any
                                    # buffered audio so we don't play stale
                                    # response after they've interjected.
                                    drained = 0
                                    while not self.audio_out.empty():
                                        try:
                                            self.audio_out.get_nowait()
                                            drained += 1
                                        except Exception:
                                            break
                                    if drained:
                                        logger.info("call %s: interrupted — flushed %d queued frames",
                                                    self.call_id, drained)
                                it = getattr(sc, "input_transcription", None)
                                if it and getattr(it, "text", None):
                                    self.heard_text += it.text
                                    self._append_turn("user", it.text)
                                    self.svc._broadcast({"type": "call_transcript",
                                                         "call_id": self.call_id,
                                                         "kind": "heard", "text": it.text,
                                                         "turns": self.turns})
                                ot = getattr(sc, "output_transcription", None)
                                if ot and getattr(ot, "text", None):
                                    self.spoken_text += ot.text
                                    self._append_turn("agent", ot.text)
                                    self.svc._broadcast({"type": "call_transcript",
                                                         "call_id": self.call_id,
                                                         "kind": "spoken", "text": ot.text,
                                                         "turns": self.turns})

                            tc = getattr(resp, "tool_call", None)
                            if tc:
                                resps = []
                                for fc in (tc.function_calls or []):
                                    args = dict(fc.args or {})
                                    self.svc._broadcast({"type": "call_tool",
                                                         "call_id": self.call_id,
                                                         "name": fc.name, "args": args})
                                    result = await _execute_tool(fc.name, args, ctx)
                                    resps.append(types.FunctionResponse(
                                        id=fc.id, name=fc.name,
                                        response={"result": result},
                                    ))
                                if resps:
                                    await session.send_tool_response(function_responses=resps)
                            if self.stop_evt.is_set():
                                return

                await asyncio.gather(feed(), receive(), stream_cameras())
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("call %s: Gemini loop failed: %s", self.call_id, e)

    async def run(self) -> None:
        max_call_s = int(state.sla_max_call_s or 0)
        deadline_task = None
        if max_call_s > 0:
            async def deadline():
                await asyncio.sleep(max_call_s)
                logger.info("call %s: max_call_s reached, hanging up", self.call_id)
                self.stop_evt.set()
            deadline_task = asyncio.create_task(deadline())

        try:
            await asyncio.gather(
                self._read_loop(),
                self._write_loop(),
                self._gemini_loop(),
            )
        finally:
            if deadline_task and not deadline_task.done():
                deadline_task.cancel()
            await self._hangup()
            try: self.writer.close()
            except Exception: pass


# ============================================================
# Service singleton — owns the TCP listener and tracks active calls
# ============================================================

class SipLiveAgentService:
    def __init__(self) -> None:
        self._server: Optional[asyncio.AbstractServer] = None
        self._task: Optional[asyncio.Task] = None
        self._calls: dict[str, CallSession] = {}
        self._history: list[dict] = []   # recent finished calls
        self._subs: set[asyncio.Queue] = set()
        self.last_error: Optional[str] = None
        self.bound_at: Optional[float] = None

    # ---- subscriber bus -------------------------------------------------
    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)

    def _broadcast(self, payload: dict) -> None:
        for q in list(self._subs):
            try: q.put_nowait(payload)
            except asyncio.QueueFull:
                try: q.get_nowait()
                except Exception: pass
                try: q.put_nowait(payload)
                except Exception: pass

    # ---- lifecycle ------------------------------------------------------
    def status(self) -> dict:
        return {
            "running":  self._server is not None,
            "enabled":  bool(state.sla_enabled),
            "host":     state.sla_bind_host,
            "port":     state.sla_bind_port,
            "active":   len(self._calls),
            "bound_at": self.bound_at,
            "last_error": self.last_error,
        }

    def active_calls(self) -> list[dict]:
        return [
            {
                "call_id":     c.call_id,
                "peer":        c.peer,
                "uuid":        c.uuid,
                "started_at":  c.started_at,
                "duration_s":  int(time.time() - c.started_at),
                "heard":       c.heard_text[-400:],
                "spoken":      c.spoken_text[-400:],
                "turns":       list(c.turns),
            }
            for c in self._calls.values()
        ]

    def history(self) -> list[dict]:
        return list(self._history)

    def apply_config(self) -> None:
        """Call after settings change. Starts/stops the TCP listener as needed."""
        if state.sla_enabled and self._server is None:
            self.start()
        elif (not state.sla_enabled) and self._server is not None:
            asyncio.create_task(self.stop())
        elif self._server is not None:
            # Rebind if host/port changed.
            sock = next(iter(self._server.sockets or []), None)
            if sock:
                cur_host, cur_port = sock.getsockname()[:2]
                if cur_port != int(state.sla_bind_port) or cur_host != state.sla_bind_host:
                    asyncio.create_task(self._restart())

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._run(), name="sip-live-agent")

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            try: await self._server.wait_closed()
            except Exception: pass
            self._server = None
            self.bound_at = None
        for c in list(self._calls.values()):
            c.stop_evt.set()
        self._calls.clear()
        if self._task:
            self._task.cancel()
            self._task = None
        self._broadcast({"type": "status", **self.status()})

    async def _restart(self) -> None:
        await self.stop()
        self.start()

    async def _run(self) -> None:
        while True:
            if not state.sla_enabled:
                self.last_error = "Disabled"
                await asyncio.sleep(5)
                continue
            try:
                self._server = await asyncio.start_server(
                    self._handle,
                    host=state.sla_bind_host or "0.0.0.0",
                    port=int(state.sla_bind_port or 8090),
                )
                self.bound_at = time.time()
                self.last_error = None
                addrs = [s.getsockname() for s in (self._server.sockets or [])]
                logger.info("SIP Live Agent listening on %s", addrs)
                self._broadcast({"type": "status", **self.status()})
                async with self._server:
                    await self._server.serve_forever()
            except asyncio.CancelledError:
                raise
            except OSError as e:
                self.last_error = f"bind {state.sla_bind_host}:{state.sla_bind_port}: {e}"
                logger.warning("SIP Live Agent bind failed: %s", e)
                self._server = None
                self._broadcast({"type": "status", **self.status()})
                await asyncio.sleep(5)
            except Exception as e:
                self.last_error = f"{type(e).__name__}: {e}"
                logger.exception("SIP Live Agent loop crashed")
                self._server = None
                self._broadcast({"type": "status", **self.status()})
                await asyncio.sleep(5)

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        peer_label = f"{peer[0]}:{peer[1]}" if peer else "unknown"
        call_id = uuid.uuid4().hex[:10]
        session = CallSession(call_id, peer_label, reader, writer, self)
        self._calls[call_id] = session
        logger.info("SIP Live Agent: new call %s from %s", call_id, peer_label)
        self._broadcast({"type": "call_started", "call_id": call_id, "peer": peer_label,
                         "started_at": session.started_at})
        try:
            await session.run()
        except Exception:
            logger.exception("call %s crashed", call_id)
        finally:
            self._calls.pop(call_id, None)
            self._history.insert(0, {
                "call_id":   call_id,
                "peer":      peer_label,
                "uuid":      session.uuid,
                "started_at":session.started_at,
                "ended_at":  time.time(),
                "duration_s":int(time.time() - session.started_at),
                "heard":     session.heard_text,
                "spoken":    session.spoken_text,
                "turns":     list(session.turns),
            })
            del self._history[40:]   # keep last 40
            self._broadcast({"type": "call_ended", "call_id": call_id})
            try: writer.close()
            except Exception: pass


sip_live_agent_service = SipLiveAgentService()
