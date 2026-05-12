"""Home Assistant integration: config, health, states, services, call."""
from __future__ import annotations

import json
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel

from ..core.state import state
from ..knowledge import homeassistant as ha_knowledge

router = APIRouter()

_TIMEOUT = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)


# ============================================================
# Helpers
# ============================================================
def _require_config() -> tuple[str, str]:
    if not state.homeassistant_url or not state.homeassistant_token:
        raise HTTPException(status_code=503, detail="Home Assistant not configured")
    return state.homeassistant_url, state.homeassistant_token


def _normalize(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    u = raw.strip()
    if not u:
        return None
    if not (u.startswith("http://") or u.startswith("https://")):
        u = "http://" + u
    return u.rstrip("/")


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


async def _ha_get(path: str) -> Any:
    base, token = _require_config()
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(f"{base}/api{path}", headers=_headers(token))
            r.raise_for_status()
            return r.json() if r.content else None
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text[:200]) from e
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Upstream error: {e}") from e


async def _ha_post(path: str, payload: Optional[dict] = None) -> Any:
    base, token = _require_config()
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.post(
                f"{base}/api{path}",
                headers=_headers(token),
                json=payload or {},
            )
            r.raise_for_status()
            return r.json() if r.content else None
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text[:200]) from e
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Upstream error: {e}") from e


# ============================================================
# Configuration
# ============================================================
class HAConfigIn(BaseModel):
    url: Optional[str] = None
    token: Optional[str] = None


class HAConfigOut(BaseModel):
    url: Optional[str] = None
    token_set: bool = False


@router.get("/config", response_model=HAConfigOut)
async def get_config() -> HAConfigOut:
    return HAConfigOut(
        url=state.homeassistant_url,
        token_set=bool(state.homeassistant_token),
    )


@router.post("/config", response_model=HAConfigOut)
async def set_config(payload: HAConfigIn) -> HAConfigOut:
    # Empty url clears everything. Token can be left unchanged by sending None.
    if payload.url is not None:
        state.homeassistant_url = _normalize(payload.url)
        if not state.homeassistant_url:
            state.homeassistant_token = None
    if payload.token is not None:
        state.homeassistant_token = payload.token.strip() or None
    state.save()
    return HAConfigOut(
        url=state.homeassistant_url,
        token_set=bool(state.homeassistant_token),
    )


# ============================================================
# Health
# ============================================================
@router.get("/health")
async def health() -> dict:
    if not state.homeassistant_url or not state.homeassistant_token:
        return {"status": "idle", "message": "Not configured"}
    base, token = state.homeassistant_url, state.homeassistant_token
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(f"{base}/api/", headers=_headers(token))
        if r.status_code == 401:
            return {"status": "err", "message": "Unauthorized — bad token"}
        r.raise_for_status()
        body = r.json() if r.content else {}
        return {"status": "ok", "message": body.get("message", "Connected")}
    except httpx.HTTPStatusError as e:
        return {"status": "err", "message": f"HTTP {e.response.status_code}"}
    except Exception as e:
        return {"status": "err", "message": f"Unreachable: {type(e).__name__}"}


# ============================================================
# Entities & services
# ============================================================
@router.get("/entities")
async def list_entities(domain: Optional[str] = None) -> list[dict[str, Any]]:
    """Return all entity states. Optional ?domain=light filter."""
    data = await _ha_get("/states")
    if not isinstance(data, list):
        return []
    out = []
    for ent in data:
        eid = ent.get("entity_id", "")
        ent_domain = eid.split(".", 1)[0] if "." in eid else ""
        if domain and ent_domain != domain:
            continue
        out.append({
            "entity_id":   eid,
            "domain":      ent_domain,
            "state":       ent.get("state"),
            "attributes":  ent.get("attributes") or {},
            "last_changed": ent.get("last_changed"),
            "last_updated": ent.get("last_updated"),
            "friendly_name": (ent.get("attributes") or {}).get("friendly_name") or eid,
        })
    out.sort(key=lambda e: (e["domain"], e["entity_id"]))
    return out


@router.get("/entity/{entity_id}")
async def get_entity(entity_id: str) -> dict[str, Any]:
    data = await _ha_get(f"/states/{entity_id}")
    if not isinstance(data, dict):
        raise HTTPException(status_code=404, detail="Entity not found")
    eid = data.get("entity_id", entity_id)
    return {
        "entity_id":   eid,
        "domain":      eid.split(".", 1)[0] if "." in eid else "",
        "state":       data.get("state"),
        "attributes":  data.get("attributes") or {},
        "last_changed": data.get("last_changed"),
        "last_updated": data.get("last_updated"),
        "friendly_name": (data.get("attributes") or {}).get("friendly_name") or eid,
    }


@router.get("/domains")
async def list_domains() -> list[dict[str, Any]]:
    """Distinct domains present in the running HA instance, with entity counts."""
    entities = await list_entities()
    counts: dict[str, int] = {}
    for e in entities:
        counts[e["domain"]] = counts.get(e["domain"], 0) + 1
    return [{"domain": d, "count": c} for d, c in sorted(counts.items())]


@router.get("/services")
async def list_services() -> list[dict[str, Any]]:
    """Full HA services index — useful for the Live Agent and the Test UI."""
    data = await _ha_get("/services")
    return data if isinstance(data, list) else []


class ServiceCallIn(BaseModel):
    domain: str
    service: str
    # service_data may include entity_id, brightness, target temperature, etc.
    service_data: Optional[dict[str, Any]] = None


@router.post("/call")
async def call_service(payload: ServiceCallIn = Body(...)) -> dict[str, Any]:
    """Generic service-call passthrough: domain/service + arbitrary data."""
    result = await _ha_post(
        f"/services/{payload.domain}/{payload.service}",
        payload.service_data or {},
    )
    return {"ok": True, "result": result if result is not None else []}


# ============================================================
# Areas — uses HA's template API to enumerate areas + their entities
# ============================================================
_AREAS_TEMPLATE = (
    "[{% for a in areas() %}"
    "{\"id\": {{ a | tojson }}, "
    "\"name\": {{ area_name(a) | tojson }}, "
    "\"entities\": {{ area_entities(a) | tojson }}}"
    "{% if not loop.last %},{% endif %}"
    "{% endfor %}]"
)


async def _ha_render_template(template: str) -> str:
    base, token = _require_config()
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.post(
                f"{base}/api/template",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"template": template},
            )
            r.raise_for_status()
            return r.text
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text[:200]) from e
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Upstream error: {e}") from e


@router.get("/areas")
async def list_areas() -> list[dict[str, Any]]:
    """All HA areas with the entity_ids in each."""
    text = await _ha_render_template(_AREAS_TEMPLATE)
    try:
        data = json.loads(text)
    except Exception:
        return []
    return data if isinstance(data, list) else []


# ============================================================
# Knowledge — curated domain capabilities for the UI & Live Agent
# ============================================================
@router.get("/knowledge")
async def get_knowledge() -> dict[str, Any]:
    """Capability table covering common HA domains. Source of truth lives in
    backend/app/knowledge/homeassistant.py."""
    return {
        "domains": ha_knowledge.DOMAIN_CAPABILITIES,
        "universal": ha_knowledge.UNIVERSAL_SERVICES,
    }


@router.get("/knowledge/{domain}")
async def get_domain_knowledge(domain: str) -> dict[str, Any]:
    return ha_knowledge.capabilities_for(domain)
