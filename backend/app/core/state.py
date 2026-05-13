"""Persistent in-memory state. Backed by data/state.json."""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Optional

_STATE_PATH = Path(__file__).resolve().parents[3] / "data" / "state.json"
_lock = threading.Lock()


_DEFAULT_GEMINI_MODEL = "gemini-2.0-flash-live-001"


class State:
    def __init__(self) -> None:
        self.frigate_url: Optional[str] = None
        self.homeassistant_url: Optional[str] = None
        self.homeassistant_token: Optional[str] = None
        self.gemini_api_key: Optional[str] = None
        self.gemini_model: str = _DEFAULT_GEMINI_MODEL
        # MQTT broker (used to subscribe to Frigate's push events)
        self.mqtt_host: Optional[str] = None
        self.mqtt_port: int = 1883
        self.mqtt_username: Optional[str] = None
        self.mqtt_password: Optional[str] = None
        self.mqtt_topic_prefix: str = "frigate"
        # Ollama (local) — optional alternative vision provider for rules.
        self.ollama_url: Optional[str] = None
        # Persistent AI-Camera rules — see services/ai_camera_engine for the
        # runtime engine that consumes these. Each entry is a plain dict; the
        # rules router owns the schema, this layer only round-trips the list.
        self.ai_camera_rules: list[dict[str, Any]] = []
        # SIP softphone — settings the browser-side JsSIP client uses to
        # register with the PBX. ws_url is the WebSocket endpoint (ws:// or
        # wss://). realm is the SIP domain part of the AOR; falls back to the
        # host in ws_url if blank.
        self.sip_ws_url: Optional[str] = None
        self.sip_extension: Optional[str] = None
        self.sip_password: Optional[str] = None
        self.sip_realm: Optional[str] = None
        self.sip_display_name: Optional[str] = None
        self._load()

    def _load(self) -> None:
        if not _STATE_PATH.exists():
            return
        try:
            data = json.loads(_STATE_PATH.read_text())
            self.frigate_url = data.get("frigate_url") or None
            self.homeassistant_url = data.get("homeassistant_url") or None
            self.homeassistant_token = data.get("homeassistant_token") or None
            self.gemini_api_key = data.get("gemini_api_key") or None
            self.gemini_model = data.get("gemini_model") or _DEFAULT_GEMINI_MODEL
            self.mqtt_host = data.get("mqtt_host") or None
            self.mqtt_port = int(data.get("mqtt_port") or 1883)
            self.mqtt_username = data.get("mqtt_username") or None
            self.mqtt_password = data.get("mqtt_password") or None
            self.mqtt_topic_prefix = data.get("mqtt_topic_prefix") or "frigate"
            self.ollama_url = data.get("ollama_url") or None
            rules = data.get("ai_camera_rules")
            if isinstance(rules, list):
                self.ai_camera_rules = [r for r in rules if isinstance(r, dict)]
            self.sip_ws_url       = data.get("sip_ws_url") or None
            self.sip_extension    = data.get("sip_extension") or None
            self.sip_password     = data.get("sip_password") or None
            self.sip_realm        = data.get("sip_realm") or None
            self.sip_display_name = data.get("sip_display_name") or None
        except Exception:
            pass

    def save(self) -> None:
        with _lock:
            _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            _STATE_PATH.write_text(
                json.dumps(
                    {
                        "frigate_url": self.frigate_url,
                        "homeassistant_url": self.homeassistant_url,
                        "homeassistant_token": self.homeassistant_token,
                        "gemini_api_key": self.gemini_api_key,
                        "gemini_model": self.gemini_model,
                        "mqtt_host": self.mqtt_host,
                        "mqtt_port": self.mqtt_port,
                        "mqtt_username": self.mqtt_username,
                        "mqtt_password": self.mqtt_password,
                        "mqtt_topic_prefix": self.mqtt_topic_prefix,
                        "ollama_url": self.ollama_url,
                        "ai_camera_rules": self.ai_camera_rules,
                        "sip_ws_url":       self.sip_ws_url,
                        "sip_extension":    self.sip_extension,
                        "sip_password":     self.sip_password,
                        "sip_realm":        self.sip_realm,
                        "sip_display_name": self.sip_display_name,
                    },
                    indent=2,
                )
            )


state = State()
