"""
MQTT service — singleton that connects to the user's MQTT broker and
subscribes to Frigate topics. Maintains an in-memory motion/audio cache
and broadcasts updates to subscribers (WebSocket clients).

Frigate topic layout (under `<prefix>/`, default `frigate/`):
  - frigate/<camera>/motion              payload: ON|OFF
  - frigate/<camera>/<label>             payload: ON|OFF (per-label detection)
  - frigate/<camera>/audio/<metric>      payload: float (dBFS, rms, snr) OR ON|OFF (per-label audio)
  - frigate/events                       payload: JSON

Subscribed topics: <prefix>/+/motion, <prefix>/+/audio/+, <prefix>/events.
Object labels come from the events stream so the UI can display
"MOTION · person, car"; audio levels (dBFS) drive the per-camera meter.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
from typing import Any, Optional, Set

import aiomqtt

from ..core.state import state

logger = logging.getLogger("mqtt")

# Audio "metric" topics under <prefix>/<cam>/audio/* that carry numeric levels
# rather than per-label ON/OFF state.
_AUDIO_METRICS = {"dBFS", "rms", "snr"}


def _default_cam_state() -> dict[str, Any]:
    return {
        "motion": False,
        "objects": set(),
        "audio_dbfs": None,        # latest dBFS reading (None until first message)
        "audio_labels": set(),     # active per-label audio detections (speech, dog_bark, …)
    }


class MqttService:
    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        # camera -> dict (see _default_cam_state)
        self._motion_state: dict[str, dict[str, Any]] = {}
        # asyncio.Queue's, each receives JSON-friendly dicts
        self._subscribers: Set[asyncio.Queue] = set()
        self.connected: bool = False
        self.last_error: Optional[str] = None

    # ---------- public API -----------------------------------------------

    def is_configured(self) -> bool:
        return bool(state.mqtt_host)

    def start(self) -> None:
        """Start (or restart on config change) the background MQTT loop."""
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = asyncio.create_task(self._run(), name="mqtt-service")

    def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None
        self.connected = False

    def snapshot(self) -> dict[str, dict]:
        """Current motion/audio state per camera (JSON-friendly)."""
        return {cam: self._serialize(s) for cam, s in self._motion_state.items()}

    @staticmethod
    def _serialize(s: dict[str, Any]) -> dict:
        return {
            "motion": bool(s.get("motion")),
            "objects": sorted(list(s.get("objects") or [])),
            "audio_dbfs": s.get("audio_dbfs"),
            "audio_labels": sorted(list(s.get("audio_labels") or [])),
        }

    def any_motion(self, cameras: list[str]) -> bool:
        """True if at least one of the given cameras currently has motion."""
        for c in cameras or []:
            s = self._motion_state.get(c)
            if s and s.get("motion"):
                return True
        return False

    def add_subscriber(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._subscribers.add(q)
        return q

    def remove_subscriber(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    # ---------- main loop ------------------------------------------------

    async def _run(self) -> None:
        while True:
            if not self.is_configured():
                self.connected = False
                self.last_error = "Not configured"
                # Wait until config arrives; .start() will cancel & restart us.
                await asyncio.sleep(60)
                continue

            host = state.mqtt_host
            port = int(state.mqtt_port or 1883)
            username = state.mqtt_username
            password = state.mqtt_password
            prefix = (state.mqtt_topic_prefix or "frigate").rstrip("/")

            kwargs: dict[str, Any] = {"hostname": host, "port": port}
            if username:
                kwargs["username"] = username
            if password:
                kwargs["password"] = password

            try:
                async with aiomqtt.Client(**kwargs) as client:
                    self.connected = True
                    self.last_error = None
                    logger.info("MQTT connected to %s:%s (prefix=%s)", host, port, prefix)

                    await client.subscribe(f"{prefix}/+/motion")
                    await client.subscribe(f"{prefix}/+/audio/+")
                    await client.subscribe(f"{prefix}/events")

                    async for msg in client.messages:
                        try:
                            self._handle_message(msg.topic.value, msg.payload, prefix)
                        except Exception:
                            logger.exception("error handling MQTT message")
            except asyncio.CancelledError:
                self.connected = False
                logger.info("MQTT service cancelled")
                raise
            except aiomqtt.MqttError as e:
                self.connected = False
                self.last_error = str(e)
                logger.warning("MQTT error, retrying in 5s: %s", e)
                await asyncio.sleep(5)
            except Exception as e:  # noqa: BLE001
                self.connected = False
                self.last_error = f"{type(e).__name__}: {e}"
                logger.exception("MQTT unexpected error")
                await asyncio.sleep(5)

    # ---------- message handling ----------------------------------------

    def _handle_message(self, topic: str, payload: bytes, prefix: str) -> None:
        parts = topic.split("/")
        if not parts or parts[0] != prefix:
            return

        # <prefix>/<camera>/motion → ON/OFF
        if len(parts) == 3 and parts[2] == "motion":
            camera = parts[1]
            value = payload.decode("utf-8", "replace").strip().upper()
            motion = (value == "ON")
            current = self._motion_state.setdefault(camera, _default_cam_state())
            current["motion"] = motion
            if not motion:
                # When motion ends, clear any lingering object labels.
                current["objects"].clear()
            self._broadcast_camera(camera)
            return

        # <prefix>/<camera>/audio/<metric_or_label>
        #   metric in {dBFS, rms, snr} → float level
        #   anything else (e.g. "speech", "dog_bark") → ON/OFF detection
        if len(parts) == 4 and parts[2] == "audio":
            camera = parts[1]
            metric = parts[3]
            payload_str = payload.decode("utf-8", "replace").strip()
            current = self._motion_state.setdefault(camera, _default_cam_state())
            if metric in _AUDIO_METRICS:
                try:
                    val = float(payload_str)
                except ValueError:
                    return
                if metric == "dBFS":
                    current["audio_dbfs"] = val
                elif metric == "rms" and current.get("audio_dbfs") is None:
                    # Fallback: convert int16 RMS to approximate dBFS so cameras
                    # that don't publish dBFS still drive the meter.
                    current["audio_dbfs"] = (
                        20.0 * math.log10(val / 32768.0) if val > 0 else -100.0
                    )
                # snr is informational; we don't render it.
            else:
                if payload_str.upper() == "ON":
                    current["audio_labels"].add(metric)
                else:
                    current["audio_labels"].discard(metric)
            self._broadcast_camera(camera)
            return

        # <prefix>/events → JSON envelope, gives us object labels in flight.
        if len(parts) == 2 and parts[1] == "events":
            try:
                data = json.loads(payload)
            except Exception:
                return
            etype = data.get("type")
            after = data.get("after") or data.get("before") or {}
            camera = after.get("camera")
            label = after.get("label")
            if not camera or not label:
                return
            current = self._motion_state.setdefault(camera, _default_cam_state())
            if etype == "end":
                current["objects"].discard(label)
            else:  # new / update
                current["objects"].add(label)
                # Object events imply something is happening, so promote motion
                # in case the per-camera motion topic hasn't landed yet.
                current["motion"] = True
            self._broadcast_camera(camera)
            return

    def _broadcast_camera(self, camera: str) -> None:
        s = self._motion_state.get(camera) or _default_cam_state()
        payload = {
            "type": "motion",
            "camera": camera,
            **self._serialize(s),
        }
        for q in list(self._subscribers):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                # Drop oldest by emptying — a slow subscriber shouldn't
                # block the broker loop.
                try:
                    q.get_nowait()
                    q.put_nowait(payload)
                except Exception:
                    pass


mqtt_service = MqttService()
