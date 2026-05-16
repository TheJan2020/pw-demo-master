"""PW Demo Master — FastAPI app."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .routers import (
    ai_camera, ai_camera_rules, frigate, homeassistant, live_agent, mqtt,
    sip, sip_live_agent, sip_live_rep,
)
from .services import ai_camera_engine
from .services.mqtt import mqtt_service
from .services.sip_live_agent import sip_live_agent_service
from .services.sip_live_rep import sip_live_rep_service

# Per-vertical demo apps (see DEMOSITEMAP.md).
from .demos import landing as demos_landing
from .demos.clinic import router as demos_clinic

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
DEMOS_DIR = FRONTEND_DIR / "demos"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Startup: kick off the background MQTT client (no-op until configured),
    # spin up the AI-Camera rules engine so saved rules start scanning
    # without anyone opening a page, and (re)start the SIP Live Assistant
    # TCP listener if it's enabled in state.
    mqtt_service.start()
    await ai_camera_engine.start_engine()
    sip_live_agent_service.apply_config()
    sip_live_rep_service.apply_config()
    try:
        yield
    finally:
        await sip_live_rep_service.stop()
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
app.include_router(sip_live_rep.router,   prefix="/api/sip-live-rep",   tags=["sip-live-rep"])

# Per-vertical demos. `/demo` is the 6-card landing page; each vertical
# has a static SPA mount under `/demo/<slug>/` and its API at
# `/api/demo/<slug>/*`. The session cookie lives at path `/` with a
# per-slug name (`pw_demo_clinic`, `pw_demo_restaurant`, …) so verticals
# don't clobber each other in the same browser.
app.include_router(demos_landing.router,  prefix="/demo",                 tags=["demos"])
app.include_router(demos_clinic.router,   prefix="/api/demo/clinic",      tags=["demo-clinic"])


@app.get("/api/health")
async def app_health() -> dict:
    return {"status": "ok"}


# Per-vertical SPA mounts. These come BEFORE the root `/` static mount so
# `/demo/clinic/assets/...` requests hit the vertical's built bundle, not
# the main admin app's frontend folder.
if (DEMOS_DIR / "clinic").is_dir():
    app.mount(
        "/demo/clinic",
        StaticFiles(directory=str(DEMOS_DIR / "clinic"), html=True),
        name="demo-clinic-spa",
    )


# Serve the frontend last so /api/* takes precedence.
app.mount(
    "/",
    StaticFiles(directory=str(FRONTEND_DIR), html=True),
    name="frontend",
)


@app.exception_handler(404)
async def spa_fallback(request, exc):  # noqa: ARG001
    from fastapi.responses import JSONResponse

    path = request.url.path
    # Admin-app API paths should 404 as JSON.
    if path.startswith("/api"):
        return JSONResponse({"detail": "Not found"}, status_code=404)
    # SPA fallback for the Clinic demo — a direct GET on
    # /demo/clinic/dashboard (or any TanStack Router client route) should
    # return the clinic's index.html so the SPA can take over.
    if path.startswith("/demo/clinic/"):
        clinic_index = DEMOS_DIR / "clinic" / "index.html"
        if clinic_index.exists():
            return FileResponse(clinic_index)
    return FileResponse(FRONTEND_DIR / "index.html")
