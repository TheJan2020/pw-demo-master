"""PW Demo Master — FastAPI app."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .routers import ai_camera, frigate, homeassistant, live_agent, mqtt
from .services.mqtt import mqtt_service

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Startup: kick off the background MQTT client (no-op until configured).
    mqtt_service.start()
    try:
        yield
    finally:
        # Shutdown: stop the MQTT client cleanly.
        mqtt_service.stop()


app = FastAPI(title="PW Demo Master", version="0.6.0", lifespan=lifespan)

# API routers — each integration gets its own prefix so it can grow independently.
app.include_router(frigate.router,        prefix="/api/frigate",        tags=["frigate"])
app.include_router(homeassistant.router,  prefix="/api/homeassistant",  tags=["homeassistant"])
app.include_router(live_agent.router,     prefix="/api/live-agent",     tags=["live-agent"])
app.include_router(ai_camera.router,      prefix="/api/ai-camera",      tags=["ai-camera"])
app.include_router(mqtt.router,           prefix="/api/mqtt",           tags=["mqtt"])


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
