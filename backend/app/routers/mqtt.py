"""MQTT broker configuration + health endpoints.

The MQTT service is a singleton (backend/app/services/mqtt.py). These
endpoints let the user point it at their broker and check whether the
connection is alive.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from ..core.state import state
from ..services.mqtt import mqtt_service

router = APIRouter()


class MqttConfigIn(BaseModel):
    host:         Optional[str] = None
    port:         Optional[int] = None
    username:     Optional[str] = None
    password:     Optional[str] = None
    topic_prefix: Optional[str] = None


class MqttConfigOut(BaseModel):
    host:         Optional[str] = None
    port:         int = 1883
    username:     Optional[str] = None
    password_set: bool = False
    topic_prefix: str = "frigate"


def _current() -> MqttConfigOut:
    return MqttConfigOut(
        host=state.mqtt_host,
        port=int(state.mqtt_port or 1883),
        username=state.mqtt_username,
        password_set=bool(state.mqtt_password),
        topic_prefix=state.mqtt_topic_prefix or "frigate",
    )


@router.get("/config", response_model=MqttConfigOut)
async def get_config() -> MqttConfigOut:
    return _current()


@router.post("/config", response_model=MqttConfigOut)
async def set_config(payload: MqttConfigIn) -> MqttConfigOut:
    if payload.host is not None:
        state.mqtt_host = (payload.host or "").strip() or None
    if payload.port is not None:
        state.mqtt_port = max(1, int(payload.port))
    if payload.username is not None:
        state.mqtt_username = payload.username.strip() or None
    if payload.password is not None:
        # Empty string clears the password.
        state.mqtt_password = payload.password or None
    if payload.topic_prefix is not None:
        state.mqtt_topic_prefix = (payload.topic_prefix or "frigate").strip() or "frigate"
    state.save()

    # Bounce the MQTT client so the new config takes effect immediately.
    mqtt_service.start()

    return _current()


@router.get("/health")
async def health() -> dict:
    if not state.mqtt_host:
        return {"status": "idle", "message": "Not configured"}
    if mqtt_service.connected:
        return {"status": "ok", "message": f"Connected to {state.mqtt_host}:{state.mqtt_port}"}
    return {"status": "err", "message": mqtt_service.last_error or "Disconnected"}
