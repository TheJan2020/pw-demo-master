"""
Clinic Demo Live Agent — Gemini Live behind an AudioSocket connector for
the clinic vertical demo.

Mirrors the structure of `services.sip_live_rep` / `services.sip_live_agent`
but is fully isolated from them:

- Different state namespace: cda_* (clinic-demo-agent)
- Different default port: 8092  (admin SLA = 8090, admin SLR = 8091)
- Persona + Knowledge Base are read from disk on every call so the
  Clinic SPA's KB / Persona pages can publish updates without restarting
  the backend:
    data/demos/clinic/persona.txt   — overrides DEFAULT_PERSONA below
    data/demos/clinic/kb.txt        — overrides DEFAULT_KB below
- No info-collection function tool yet. Future tools (lookup_patient,
  list_free_slots, create_appointment, …) will live in this same module
  once we wire the clinic-side data layer to the backend. For now the
  agent is "knowledge-only" — it can talk about clinics, prices,
  policies, and read the persona, but it cannot mutate clinic data.

FreePBX dialplan flow:
  caller dials extension → FreePBX → AudioSocket(<UUID>, host:8092)
  → this service accepts the TCP connection → spins up a per-call
  Gemini Live session → bridges PCM both directions over AudioSocket.
"""
from __future__ import annotations

import asyncio
import audioop
import logging
import struct
import time
import uuid
from pathlib import Path
from typing import Optional

from google import genai
from google.genai import types

from ...core.state import state

logger = logging.getLogger("clinic_live_agent")

# AudioSocket framing — identical wire protocol to chan_audiosocket.
_AS_HANGUP = 0x00
_AS_UUID   = 0x01
_AS_DTMF   = 0x02
_AS_ERROR  = 0x03
_AS_AUDIO  = 0x10

_SAMPLE_WIDTH = 2  # signed-linear 16-bit
_GEMINI_API_VERSION = "v1alpha"

# On-disk overrides — the Clinic SPA's KB / Persona pages POST here via
# /api/demo/clinic/agent/prompt. Service rereads per call so the user
# doesn't need to restart anything.
_DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "demos" / "clinic"
_PERSONA_PATH = _DATA_DIR / "persona.txt"
_KB_PATH      = _DATA_DIR / "kb.txt"


# ============================================================================
# Defaults — kept in sync with the Clinic SPA's clinicLiveData.ts seeds.
# (Demo: when the SPA's "Apply to live agent" button hasn't been clicked
# yet, the backend uses these defaults.)
# ============================================================================

DEFAULT_PERSONA = """# Layla — Receptionist persona for Primewave Mate Clinics

You are Layla (ليلى), the AI receptionist for Primewave Mate Clinics in
Riyadh. You answer phone calls and route them politely and efficiently.

## Voice & tone
- Warm, professional, and concise. Never robotic.
- Use the caller's first name after they share it.
- Sentences short. One question at a time.

## Language — Arabic by default
- Always greet in Arabic (Najdi / Hijazi).
- Detect the caller's language from their first reply and switch
  smoothly (English, Urdu, Tagalog, French, or mixed Arabic-English).
- Stay in that language for the rest of the call unless the caller
  switches again.

## Greeting (always Arabic)
"السلام عليكم، عيادات برايم ميت. أنا ليلى. كيف أقدر أخدمك؟"

## You CAN
- Take new appointment requests — collect patient name, mobile,
  clinic / specialty, preferred date + time, reason.
- Quote prices for common visits.
- Explain insurance acceptance and payment methods.

## You MUST NOT
- Never give medical diagnoses or treatment advice.
- Never confirm a booking outside working hours.
- If the caller mentions an emergency (chest pain, heavy bleeding,
  loss of consciousness): tell them to call 997 (Saudi Red Crescent)
  immediately, and stay on the line.

## Booking flow — always confirm in this order
1. Patient full name (ask for Arabic spelling too).
2. Mobile number (Saudi format: +9665X XXX XXXX).
3. Existing file number if known (format: A/B/C + 6 digits).
4. Preferred clinic / specialty.
5. Preferred date + time.
6. Read back the booking summary in both Arabic and English; ask
   the caller to confirm "yes" / "نعم" before finalising.

## End of call
"إن شاء الله نشوفك. شكراً للاتصال."
"""

DEFAULT_KB = """# Primewave Mate Clinics — Riyadh (Knowledge Base)

Multi-specialty outpatient center in Olaya, Riyadh. Serving the
community since 2018. Multilingual staff (Arabic, English, Urdu),
integrated EHR across all clinics in the building.

## Location & contact
- Main Center: Olaya Street, Olaya, Riyadh 12244, KSA
- Reception: +966 11 234 5678
- WhatsApp: +966 50 111 0000
- Email: hello@primemate.clinic

## Operating hours (default — agent should still confirm with the
## live state in the system instruction if available)
- Sunday – Thursday: 09:00 – 17:00 (lunch break 13:00 – 14:00)
- Saturday: 09:00 – 13:00 (morning only)
- Friday: closed

## Insurance accepted
BUPA Arabia, Tawuniya, MedGulf, AXA, Globemed.
Cash, mada, Visa, Mastercard, Apple Pay.
Pre-approval required for procedures over SAR 1,000.

## Booking & cancellation policy
- Appointments can be booked up to 30 days in advance.
- Walk-ins accepted subject to availability.
- Free cancellation if at least 4 hours before the slot.
- Inside 4 hours: SAR 100 fee.
- 15+ minutes late may forfeit the slot.

## Typical pricing
- General consultation: SAR 350
- Specialist consultation: SAR 500
- Pediatric consultation: SAR 400
- Dental check-up + cleaning: SAR 450
- X-ray (single view): SAR 200
- Basic ultrasound: SAR 350

## Services
Pediatrics, Cardiology, Dentistry, Family Medicine, Dermatology,
Orthopedics. On-site labs + basic imaging. Telemedicine follow-ups
for established patients. Home visits within 10 km (SAR 250 extra).

## Languages spoken
Arabic, English, Urdu, Tagalog.
"""


# ============================================================================
# Prompt persistence helpers — used by both the service and the router.
# ============================================================================

def load_persona() -> str:
    if _PERSONA_PATH.exists():
        try:
            txt = _PERSONA_PATH.read_text(encoding="utf-8").strip()
            if txt:
                return txt
        except Exception:
            logger.exception("failed to read %s", _PERSONA_PATH)
    return DEFAULT_PERSONA


def load_kb() -> str:
    if _KB_PATH.exists():
        try:
            txt = _KB_PATH.read_text(encoding="utf-8").strip()
            if txt:
                return txt
        except Exception:
            logger.exception("failed to read %s", _KB_PATH)
    return DEFAULT_KB


def save_persona(text: str) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    _PERSONA_PATH.write_text((text or "").strip() + "\n", encoding="utf-8")


def save_kb(text: str) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    _KB_PATH.write_text((text or "").strip() + "\n", encoding="utf-8")


def _build_system_instruction() -> str:
    return f"{load_persona().strip()}\n\n{load_kb().strip()}"


# ============================================================================
# CallSession — one TCP connection from Asterisk = one call = one Gemini session
# ============================================================================

class CallSession:
    def __init__(
        self, call_id: str, peer: str,
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
        svc: "ClinicLiveAgentService",
    ) -> None:
        self.call_id = call_id
        self.peer = peer
        self.reader = reader
        self.writer = writer
        self.svc = svc
        self.uuid: Optional[str] = None
        self.started_at = time.time()
        # Caller -> Gemini (16 kHz mono PCM after upsample)
        self.audio_in: asyncio.Queue = asyncio.Queue(maxsize=200)
        # Gemini -> Caller (24 kHz mono PCM, downsampled in the write loop)
        self.audio_out: asyncio.Queue = asyncio.Queue(maxsize=200)
        self.stop_evt = asyncio.Event()
        self._upstate = None
        self._downstate = None
        self._out_leftover: bytes = b""
        self._next_send_at: Optional[float] = None
        self.echo_until: float = 0.0
        self.heard_text = ""
        self.spoken_text = ""

    # ---- wire protocol -----------------------------------------------------
    @staticmethod
    async def _read_frame(reader: asyncio.StreamReader) -> tuple[int, bytes]:
        header = await reader.readexactly(3)
        msg_type = header[0]
        length = struct.unpack(">H", header[1:3])[0]
        payload = await reader.readexactly(length) if length else b""
        return msg_type, payload

    async def _send_audio(self, pcm8k: bytes) -> None:
        FRAME = 320  # 20 ms @ 8 kHz, 16-bit mono
        n_frames = len(pcm8k) // FRAME
        if n_frames == 0:
            return
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

    # ---- pumps -------------------------------------------------------------
    async def _read_loop(self) -> None:
        try:
            while not self.stop_evt.is_set():
                msg_type, payload = await self._read_frame(self.reader)
                if msg_type == _AS_HANGUP:
                    logger.info("clinic call %s: peer hangup", self.call_id)
                    self.stop_evt.set()
                    return
                if msg_type == _AS_UUID:
                    self.uuid = payload.hex()
                    continue
                if msg_type == _AS_DTMF:
                    digit = payload.decode("ascii", "replace") if payload else ""
                    logger.info("clinic call %s: DTMF %s", self.call_id, digit)
                    continue
                if msg_type == _AS_ERROR:
                    logger.warning("clinic call %s: peer error: %r", self.call_id, payload)
                    continue
                if msg_type == _AS_AUDIO and payload:
                    # Half-duplex gate only when interruption is OFF (mirrors
                    # the fix landed for sip_live_rep — see its comments).
                    if not state.cda_interruption_enabled and time.time() < self.echo_until:
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
            self.stop_evt.set()
        except Exception:
            logger.exception("clinic call %s: read loop crashed", self.call_id)
            self.stop_evt.set()

    async def _write_loop(self) -> None:
        FRAME = 320
        try:
            while not self.stop_evt.is_set():
                try:
                    pcm24k = await asyncio.wait_for(self.audio_out.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue
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
            logger.warning("clinic call %s: write loop ended: %s", self.call_id, e)

    async def _gemini_loop(self) -> None:
        if not state.gemini_api_key:
            logger.error("clinic call %s: Gemini API key not set", self.call_id)
            return
        model = state.gemini_model
        client = genai.Client(
            api_key=state.gemini_api_key,
            http_options={"api_version": _GEMINI_API_VERSION},
        )

        cfg = types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            system_instruction=types.Content(
                parts=[types.Part(text=_build_system_instruction())],
            ),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=state.cda_voice or "Aoede",
                    ),
                ),
            ),
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            realtime_input_config=types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(
                    disabled=not bool(state.cda_interruption_enabled),
                    start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_HIGH,
                    end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_HIGH,
                    silence_duration_ms=600,
                    prefix_padding_ms=200,
                ),
            ),
        )

        try:
            async with client.aio.live.connect(model=model, config=cfg) as session:
                logger.info("clinic call %s: Gemini Live connected (model=%s)", self.call_id, model)

                if state.cda_greeting:
                    try:
                        await session.send_client_content(
                            turns=types.Content(role="user", parts=[
                                types.Part(text=f"(system) Greet the caller now with: {state.cda_greeting}")
                            ]),
                            turn_complete=True,
                        )
                    except Exception as e:
                        logger.warning("clinic call %s: greeting failed: %s", self.call_id, e)

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
                                try: self.audio_out.put_nowait(data_bytes)
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
                                        except Exception: break
                                    self._out_leftover = b""
                                    self.echo_until = 0.0
                                    if drained:
                                        logger.info("clinic call %s: interrupted (%d frames dropped)", self.call_id, drained)
                                it = getattr(sc, "input_transcription", None)
                                if it and getattr(it, "text", None):
                                    self.heard_text += it.text
                                    self.svc._broadcast({
                                        "type": "transcript", "call_id": self.call_id,
                                        "who": "caller", "text": it.text,
                                    })
                                ot = getattr(sc, "output_transcription", None)
                                if ot and getattr(ot, "text", None):
                                    self.spoken_text += ot.text
                                    self.svc._broadcast({
                                        "type": "transcript", "call_id": self.call_id,
                                        "who": "agent", "text": ot.text,
                                    })

                feeder = asyncio.create_task(feed())
                receiver = asyncio.create_task(receive())
                done, pending = await asyncio.wait(
                    {feeder, receiver, asyncio.create_task(self.stop_evt.wait())},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for t in pending:
                    t.cancel()

        except Exception:
            logger.exception("clinic call %s: Gemini Live failed", self.call_id)

    async def run(self) -> None:
        max_s = max(60, int(state.cda_max_call_s or 900))
        async def deadline():
            await asyncio.sleep(max_s)
            logger.info("clinic call %s: hit max duration %ds", self.call_id, max_s)
            self.stop_evt.set()
        tasks = [
            asyncio.create_task(self._read_loop()),
            asyncio.create_task(self._write_loop()),
            asyncio.create_task(self._gemini_loop()),
            asyncio.create_task(deadline()),
        ]
        try:
            await self.stop_evt.wait()
        finally:
            for t in tasks:
                t.cancel()
            await self._hangup()


# ============================================================================
# Service — TCP listener + per-call dispatch + tiny pub/sub bus
# ============================================================================

class ClinicLiveAgentService:
    def __init__(self) -> None:
        self._server: Optional[asyncio.AbstractServer] = None
        self._task: Optional[asyncio.Task] = None
        self._calls: dict[str, CallSession] = {}
        self._subs: set[asyncio.Queue] = set()
        self.last_error: Optional[str] = None
        self.bound_at: Optional[float] = None

    # ----- subscriber bus -----
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

    # ----- lifecycle -----
    def status(self) -> dict:
        return {
            "running":    self._server is not None,
            "enabled":    bool(state.cda_enabled),
            "host":       state.cda_bind_host,
            "port":       state.cda_bind_port,
            "active":     len(self._calls),
            "bound_at":   self.bound_at,
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
            }
            for c in self._calls.values()
        ]

    def apply_config(self) -> None:
        """Idempotent — call after edits to cda_enabled / host / port."""
        if state.cda_enabled and self._server is None:
            self.start()
        elif (not state.cda_enabled) and self._server is not None:
            asyncio.create_task(self.stop())
        elif self._server is not None:
            sock = next(iter(self._server.sockets or []), None)
            if sock:
                cur_host, cur_port = sock.getsockname()[:2]
                if cur_port != int(state.cda_bind_port) or cur_host != state.cda_bind_host:
                    asyncio.create_task(self._restart())

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._run(), name="clinic-live-agent")

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

    async def _restart(self) -> None:
        await self.stop()
        await asyncio.sleep(0.1)
        self.start()

    async def _run(self) -> None:
        host = state.cda_bind_host or "0.0.0.0"
        port = int(state.cda_bind_port or 8092)
        try:
            self._server = await asyncio.start_server(self._handle, host, port)
            self.bound_at = time.time()
            self.last_error = None
            logger.info("ClinicLiveAgent listening on %s:%d", host, port)
            async with self._server:
                await self._server.serve_forever()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
            logger.exception("ClinicLiveAgent bind/run failed")

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        peer_label = f"{peer[0]}:{peer[1]}" if peer else "unknown"
        call_id = uuid.uuid4().hex[:10]
        session = CallSession(call_id, peer_label, reader, writer, self)
        self._calls[call_id] = session
        logger.info("ClinicLiveAgent: new call %s from %s", call_id, peer_label)
        self._broadcast({"type": "call_started", "call_id": call_id, "peer": peer_label, "started_at": session.started_at})
        try:
            await session.run()
        except Exception:
            logger.exception("clinic call %s crashed", call_id)
        finally:
            self._calls.pop(call_id, None)
            self._broadcast({"type": "call_ended", "call_id": call_id})
            try: writer.close()
            except Exception: pass


clinic_live_agent_service = ClinicLiveAgentService()
