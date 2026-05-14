"""PW Demo Master — FastAPI app."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .routers import ai_camera, ai_camera_rules, frigate, homeassistant, live_agent, mqtt, sip, sip_live_agent
from .services import ai_camera_engine
from .services.mqtt import mqtt_service
from .services.sip_live_agent import sip_live_agent_service

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Startup: kick off the background MQTT client (no-op until configured),
    # spin up the AI-Camera rules engine so saved rules start scanning
    # without anyone opening a page, and (re)start the SIP Live Assistant
    # TCP listener if it's enabled in state.
    mqtt_service.start()
    await ai_camera_engine.start_engine()
    sip_live_agent_service.apply_config()
    try:
        yield
    finally:
        await sip_live_agent_service.stop()
        await ai_camera_engine.stop_engine()
        mqtt_service.stop()


app = FastAPI(title="PW Demo Master", version="0.6.0", lifespan=lifespan)

# API routers — each integration gets its own prefix so it can grow independently.
app.include_router(frigate.router,        prefix="/api/frigate",        tags=["frigate"])
app.include_router(homeassistant.router,  prefix="/api/homeassistant",  tags=["homeassistant"])
app.include_router(live_agent.router,     prefix="/api/live-agent",     tags=["live-agent"])
app.include_router(ai_camera.router,      prefix="/api/ai-camera",      tags=["ai-camera"])
app.include_router(ai_camera_rules.router, prefix="/api/ai-camera",     tags=["ai-camera-rules"])
app.include_router(mqtt.router,           prefix="/api/mqtt",           tags=["mqtt"])
app.include_router(sip.router,            prefix="/api/sip",            tags=["sip"])
app.include_router(sip_live_agent.router, prefix="/api/sip-live-agent", tags=["sip-live-agent"])


@app.get("/api/health")
async def app_health() -> dict:
    return {"status": "ok"}


# Serve the frontend last so /api/* takes precedence.
app.mount(
    "/",
    StaticFiles(directory=str(FRONTEND_DIR), html=True),
    name="frontend",
)


@app.exception_handler(404)
async def spa_fallback(request, exc):  # noqa: ARG001
    # Let unknown non-API paths fall through to index.html for hash-based routing.
    if request.url.path.startswith("/api"):
        return FileResponse(FRONTEND_DIR / "index.html", status_code=404)
    return FileResponse(FRONTEND_DIR / "index.html")
