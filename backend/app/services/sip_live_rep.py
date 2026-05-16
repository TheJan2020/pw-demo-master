"""
SIP Live Representative — Primewave's public-facing AI rep over SIP.

Architecture mirrors `services/sip_live_agent.py` (AudioSocket ⇄ Gemini Live
bridge with the same pacing, buffering, and half-duplex echo gate), but
differs in three deliberate ways:

  * No HA tools / no camera vision — this rep is a customer-service voice
    rather than a smart-home controller.
  * Persistent call history — every finished call is appended to
    `data/sip_live_rep/calls.jsonl` so the UI can show a permanent log of
    every conversation (transcripts only; raw audio not stored).
  * Its own state.slr_* config namespace, bind port (default 8091), and
    FreePBX feature code (8888 → custom destination → pwdemo-live-rep,s,1).
"""
from __future__ import annotations

import asyncio
import audioop
import json
import logging
import struct
import time
import uuid
from pathlib import Path
from typing import Optional

from google import genai
from google.genai import types

from ..core.state import state

logger = logging.getLogger("sip_live_rep")

# AudioSocket message types (chan_audiosocket).
_AS_HANGUP = 0x00
_AS_UUID   = 0x01
_AS_DTMF   = 0x02
_AS_ERROR  = 0x03
_AS_AUDIO  = 0x10

_SAMPLE_WIDTH = 2
_GEMINI_API_VERSION = "v1alpha"

# Persistent history on disk — JSONL, append-only, newest-last.
_HISTORY_DIR = Path(__file__).resolve().parents[3] / "data" / "sip_live_rep"
_HISTORY_PATH = _HISTORY_DIR / "calls.jsonl"


def _ensure_history_dir() -> None:
    _HISTORY_DIR.mkdir(parents=True, exist_ok=True)


def _append_history(entry: dict) -> None:
    try:
        _ensure_history_dir()
        with _HISTORY_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n")
    except Exception:
        logger.exception("failed to append call history")


def list_history(offset: int = 0, limit: int = 20) -> tuple[list[dict], int]:
    """Return (slice_newest_first, total). Demo-scale read of the whole
    JSONL file — fine for thousands of calls; revisit if it grows past
    that."""
    if not _HISTORY_PATH.exists():
        return [], 0
    rows: list[dict] = []
    try:
        with _HISTORY_PATH.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        logger.exception("failed to read call history")
        return [], 0
    total = len(rows)
    rows.reverse()  # newest first
    return rows[offset:offset + limit], total


def clear_history() -> None:
    try:
        if _HISTORY_PATH.exists():
            _HISTORY_PATH.unlink()
    except Exception:
        logger.exception("failed to clear call history")


# ============================================================
# Live system instruction + dynamic tool schema
# ============================================================

def _build_system_instruction() -> str:
    """Compose persona + knowledge base + info-collection prompt into one
    system instruction. Pulled fresh from state on every call so edits in
    the UI take effect on the next call without restarting anything.

    Sections are labelled so persona text can reliably reference the
    "information to collect" block (e.g. "see below") without ambiguity.
    """
    parts: list[str] = []
    persona = (state.slr_system_prompt or "").strip()
    if persona:
        parts.append("## PERSONA\n" + persona)

    kb = (state.slr_knowledge or "").strip()
    if kb:
        parts.append("## KNOWLEDGE BASE — معلومات عن شركتنا وخدماتنا (مرجع لكِ)\n" + kb)

    schema = state.slr_info_schema or []
    if schema:
        fields_md = "\n".join(
            f"- `{f.get('name','')}` ({f.get('label','')}): "
            f"{f.get('description','')}"
            for f in schema
        )
        parts.append(
            "## INFORMATION TO COLLECT — المعلومات المطلوب جمعها من المتصل\n"
            "حاولي خلال الحديث، وبشكل طبيعي وغير مزعج، تجمعي هذه المعلومات:\n"
            f"{fields_md}\n\n"
            "### قاعدة إلزامية — لازم تنفذيها\n"
            "كل ما تأكدتي من معلومة (حتى لو واحدة)، **استدعي فوراً الوظيفة "
            "`save_caller_information`** وحطي القيمة بالحقل المناسب. "
            "ممكن تستدعيها أكثر من مرة خلال نفس المكالمة، كل ما تتأكدي من "
            "شي جديد. لا تنتظري آخر المكالمة. لا تخبّري المتصل أنك حافظة "
            "المعلومات — احفظيها بصمت بالخلفية وكملي الحوار بشكل طبيعي.\n"
            "Translation for the model: as soon as you confirm any field "
            "above, you MUST call the `save_caller_information` function "
            "tool with that field set. Call it multiple times throughout "
            "the call, never wait until the end. Do not announce the save "
            "to the caller — just call the tool silently while continuing "
            "the conversation."
        )
    return "\n\n".join(parts).strip()


def _build_collect_tool() -> Optional[types.Tool]:
    """Build a Gemini Tool whose schema mirrors state.slr_info_schema. If
    no schema is configured we return None — the agent still works as a
    conversational rep, just won't extract structured info."""
    schema_fields = state.slr_info_schema or []
    if not schema_fields:
        return None
    properties: dict[str, types.Schema] = {}
    for f in schema_fields:
        name = (f.get("name") or "").strip()
        if not name:
            continue
        properties[name] = types.Schema(
            type=types.Type.STRING,
            description=f.get("description") or f.get("label") or name,
        )
    if not properties:
        return None
    return types.Tool(function_declarations=[
        types.FunctionDeclaration(
            name="save_caller_information",
            description=(
                "Persist information you've gathered from the caller. Call "
                "this whenever you confirm a new piece of information about "
                "them (name, contact, address, preferences, project phase, "
                "etc.). It may be called multiple times during one call as "
                "more details emerge. Pass only the fields you actually know."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties=properties,
            ),
        )
    ])


# ============================================================
# CallSession — one TCP connection from Asterisk = one call = one Gemini session
# ============================================================

class CallSession:
    def __init__(self, call_id: str, peer: str,
                 reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
                 svc: "SipLiveRepService"):
        self.call_id = call_id
        self.peer = peer
        self.reader = reader
        self.writer = writer
        self.svc = svc
        self.uuid: Optional[str] = None
        self.started_at = time.time()
        # Structured info collected from this call by Lena via the
        # save_caller_information function tool. Merged across multiple
        # tool calls; persisted with the call's history entry.
        self.collected_info: dict[str, str] = {}
        # Caller-audio → Gemini (already upsampled to 16 kHz on this side).
        self.audio_in: asyncio.Queue = asyncio.Queue(maxsize=200)
        # Gemini → caller (24 kHz, downsampled in the write loop).
        self.audio_out: asyncio.Queue = asyncio.Queue(maxsize=200)
        self.stop_evt = asyncio.Event()
        self._upstate = None
        self._downstate = None
        self._out_leftover: bytes = b""
        self._next_send_at: Optional[float] = None
        self.echo_until: float = 0.0
        self.heard_text = ""
        self.spoken_text = ""
        # Interleaved per-turn transcript — same shape as the Live Assistant
        # for consistency. The persistent history record uses this list.
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
        if self.turns and self.turns[-1]["role"] == role:
            self.turns[-1]["text"] += text
        else:
            self.turns.append({"role": role, "text": text, "ts": time.time()})

    async def _send_audio(self, pcm8k: bytes) -> None:
        FRAME = 320
        n_frames = len(pcm8k) // FRAME
        if n_frames == 0:
            return
        # Half-duplex echo gate — see sip_live_agent.py for the rationale.
        self.echo_until = max(
            self.echo_until, time.time() + n_frames * 0.020 + 0.35,
        )
        now = time.monotonic()
        if self._next_send_at is None or self._next_send_at < now - 0.05:
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
                await asyncio.sleep(0)

    async def _hangup(self) -> None:
        try:
            self.writer.write(bytes([_AS_HANGUP, 0, 0]))
            await self.writer.drain()
        except Exception:
            pass

    # ------ pumps --------------------------------------------------------
    async def _read_loop(self) -> None:
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
                    # Half-duplex echo gate — only active when interruption
                    # is OFF. When interruption is ON we always forward caller
                    # audio so Gemini's VAD can detect speech and signal
                    # barge-in; the phone network already does echo cancel.
                    if not state.slr_interruption_enabled and time.time() < self.echo_until:
                        continue
                    pcm16k, self._upstate = audioop.ratecv(
                        payload, _SAMPLE_WIDTH, 1, 8000, 16000, self._upstate,
                    )
                    try:
                        self.audio_in.put_nowait(pcm16k)
                    except asyncio.QueueFull:
                        try: self.audio_in.get_nowait()
                        except Exception: pass
                        try: self.audio_in.put_nowait(pcm16k)
                        except Exception: pass
        except (asyncio.IncompleteReadError, ConnectionResetError):
            logger.info("call %s: read loop ended (connection)", self.call_id)
        finally:
            self.stop_evt.set()

    async def _write_loop(self) -> None:
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
        if not state.gemini_api_key:
            logger.error("call %s: Gemini API key not set", self.call_id)
            return
        model = state.gemini_model
        client = genai.Client(
            api_key=state.gemini_api_key,
            http_options={"api_version": _GEMINI_API_VERSION},
        )

        collect_tool = _build_collect_tool()
        cfg = types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            system_instruction=types.Content(
                parts=[types.Part(text=_build_system_instruction())]
            ),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=state.slr_voice or "Aoede",
                    ),
                ),
            ),
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            tools=[collect_tool] if collect_tool else None,
            # Barge-in: with interruption ON we use HIGH start-of-speech
            # sensitivity so the agent cuts itself off the instant the caller
            # speaks. With interruption OFF we disable VAD altogether so the
            # agent finishes its turn before listening.
            realtime_input_config=types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(
                    disabled=not bool(state.slr_interruption_enabled),
                    start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_HIGH,
                    end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_HIGH,
                    silence_duration_ms=600,
                    prefix_padding_ms=200,
                ),
            ),
        )

        try:
            async with client.aio.live.connect(model=model, config=cfg) as session:
                logger.info("call %s: Gemini Live connected (model=%s)", self.call_id, model)

                if state.slr_greeting:
                    try:
                        await session.send_client_content(
                            turns=types.Content(role="user", parts=[
                                types.Part(text=f"(system) Greet the caller now with: {state.slr_greeting}")
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
                                    drained = 0
                                    while not self.audio_out.empty():
                                        try:
                                            self.audio_out.get_nowait()
                                            drained += 1
                                        except Exception:
                                            break
                                    # Also drop the resample leftover and
                                    # collapse the echo gate so the caller's
                                    # next syllable isn't gated out.
                                    self._out_leftover = b""
                                    self.echo_until = 0.0
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
                            # Save anything the agent extracted via the
                            # save_caller_information tool. Multiple calls
                            # accumulate / overwrite per-field.
                            tc = getattr(resp, "tool_call", None)
                            if tc:
                                fr_list = []
                                for fc in (tc.function_calls or []):
                                    if fc.name == "save_caller_information":
                                        args = dict(fc.args or {})
                                        # Filter to non-empty strings.
                                        clean = {
                                            k: v.strip() if isinstance(v, str) else v
                                            for k, v in args.items()
                                            if v is not None and str(v).strip()
                                        }
                                        if clean:
                                            self.collected_info.update(clean)
                                            logger.info(
                                                "call %s: collected %s",
                                                self.call_id, clean,
                                            )
                                            self.svc._broadcast({
                                                "type": "call_collected",
                                                "call_id": self.call_id,
                                                "fields": dict(self.collected_info),
                                            })
                                    fr_list.append(types.FunctionResponse(
                                        id=fc.id, name=fc.name,
                                        response={"ok": True, "stored": list(self.collected_info.keys())},
                                    ))
                                if fr_list:
                                    await session.send_tool_response(function_responses=fr_list)

                            if self.stop_evt.is_set():
                                return

                await asyncio.gather(feed(), receive())
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("call %s: Gemini loop failed: %s", self.call_id, e)

    async def run(self) -> None:
        max_call_s = int(state.slr_max_call_s or 0)
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
# Service singleton
# ============================================================

class SipLiveRepService:
    def __init__(self) -> None:
        self._server: Optional[asyncio.AbstractServer] = None
        self._task: Optional[asyncio.Task] = None
        self._calls: dict[str, CallSession] = {}
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
            "enabled":  bool(state.slr_enabled),
            "host":     state.slr_bind_host,
            "port":     state.slr_bind_port,
            "active":   len(self._calls),
            "bound_at": self.bound_at,
            "last_error": self.last_error,
        }

    def active_calls(self) -> list[dict]:
        return [
            {
                "call_id":    c.call_id,
                "peer":       c.peer,
                "uuid":       c.uuid,
                "started_at": c.started_at,
                "duration_s": int(time.time() - c.started_at),
                "heard":      c.heard_text[-400:],
                "spoken":     c.spoken_text[-400:],
                "turns":      list(c.turns),
                "collected":  dict(c.collected_info),
            }
            for c in self._calls.values()
        ]

    def apply_config(self) -> None:
        if state.slr_enabled and self._server is None:
            self.start()
        elif (not state.slr_enabled) and self._server is not None:
            asyncio.create_task(self.stop())
        elif self._server is not None:
            sock = next(iter(self._server.sockets or []), None)
            if sock:
                cur_host, cur_port = sock.getsockname()[:2]
                if cur_port != int(state.slr_bind_port) or cur_host != state.slr_bind_host:
                    asyncio.create_task(self._restart())

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._run(), name="sip-live-rep")

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
            if not state.slr_enabled:
                self.last_error = "Disabled"
                await asyncio.sleep(5)
                continue
            try:
                self._server = await asyncio.start_server(
                    self._handle,
                    host=state.slr_bind_host or "0.0.0.0",
                    port=int(state.slr_bind_port or 8091),
                )
                self.bound_at = time.time()
                self.last_error = None
                addrs = [s.getsockname() for s in (self._server.sockets or [])]
                logger.info("SIP Live Rep listening on %s", addrs)
                self._broadcast({"type": "status", **self.status()})
                async with self._server:
                    await self._server.serve_forever()
            except asyncio.CancelledError:
                raise
            except OSError as e:
                self.last_error = f"bind {state.slr_bind_host}:{state.slr_bind_port}: {e}"
                logger.warning("SIP Live Rep bind failed: %s", e)
                self._server = None
                self._broadcast({"type": "status", **self.status()})
                await asyncio.sleep(5)
            except Exception as e:
                self.last_error = f"{type(e).__name__}: {e}"
                logger.exception("SIP Live Rep loop crashed")
                self._server = None
                self._broadcast({"type": "status", **self.status()})
                await asyncio.sleep(5)

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        peer_label = f"{peer[0]}:{peer[1]}" if peer else "unknown"
        call_id = uuid.uuid4().hex[:10]
        session = CallSession(call_id, peer_label, reader, writer, self)
        self._calls[call_id] = session
        logger.info("SIP Live Rep: new call %s from %s", call_id, peer_label)
        self._broadcast({"type": "call_started", "call_id": call_id, "peer": peer_label,
                         "started_at": session.started_at})
        try:
            await session.run()
        except Exception:
            logger.exception("call %s crashed", call_id)
        finally:
            self._calls.pop(call_id, None)
            entry = {
                "call_id":   call_id,
                "peer":      peer_label,
                "uuid":      session.uuid,
                "started_at":session.started_at,
                "ended_at":  time.time(),
                "duration_s":int(time.time() - session.started_at),
                "heard":     session.heard_text,
                "spoken":    session.spoken_text,
                "turns":     list(session.turns),
                "collected": dict(session.collected_info),
            }
            # Permanent: append to JSONL on disk so the UI can show every
            # past conversation, not just the in-memory recent ones.
            _append_history(entry)
            self._broadcast({"type": "call_ended", **entry})
            try: writer.close()
            except Exception: pass


sip_live_rep_service = SipLiveRepService()
