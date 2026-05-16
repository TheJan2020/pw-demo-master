"""
AI-Camera Rules — REST CRUD, history endpoints, snapshot serving, and the
events WebSocket used by the shell-level alarm subsystem.

The engine in `services/ai_camera_engine` does the heavy lifting; this router
is the HTTP/WS surface in front of it.
"""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from ..core.state import state
from ..services import ai_camera_engine as engine
from ..services import ollama as ollama_client

logger = logging.getLogger("ai_camera_rules")
router = APIRouter()


# ============================================================
# CRUD
# ============================================================

@router.get("/rules")
async def list_rules() -> dict:
    return {"rules": engine.list_rules()}


@router.post("/rules")
async def create_rule(payload: dict) -> dict:
    rule = engine.create_rule(payload or {})
    await engine.apply_rule_change(rule["id"])
    return {"rule": rule}


@router.get("/rules/{rule_id}")
async def get_rule(rule_id: str) -> dict:
    r = engine.get_rule(rule_id)
    if not r:
        raise HTTPException(404, "rule not found")
    out = dict(r)
    try:
        out["scoring"] = engine.compute_rule_scoring(rule_id)
    except Exception:
        pass
    return {"rule": out}


@router.patch("/rules/{rule_id}")
async def patch_rule(rule_id: str, patch: dict) -> dict:
    r = engine.update_rule(rule_id, patch or {})
    if not r:
        raise HTTPException(404, "rule not found")
    await engine.apply_rule_change(rule_id)
    return {"rule": r}


@router.delete("/rules/{rule_id}")
async def delete_rule(rule_id: str) -> dict:
    if not engine.get_rule(rule_id):
        raise HTTPException(404, "rule not found")
    await engine.apply_rule_delete(rule_id)
    engine.delete_rule(rule_id)
    # Best-effort cleanup of stored history + snapshots.
    try:
        shutil.rmtree(engine._rule_dir(rule_id), ignore_errors=True)  # noqa: SLF001
    except Exception:
        logger.exception("failed to clean rule data dir %s", rule_id)
    return {"ok": True}


# ============================================================
# History (paginated, newest first)
# ============================================================

@router.get("/rules/{rule_id}/triggers")
async def rule_triggers(
    rule_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> dict:
    if not engine.get_rule(rule_id):
        raise HTTPException(404, "rule not found")
    rows, total = engine.list_triggers(rule_id, offset, limit)
    return {"items": rows, "total": total, "offset": offset, "limit": limit}


@router.get("/rules/{rule_id}/iterations")
async def rule_iterations(
    rule_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> dict:
    if not engine.get_rule(rule_id):
        raise HTTPException(404, "rule not found")
    rows, total = engine.list_iterations(rule_id, offset, limit)
    return {"items": rows, "total": total, "offset": offset, "limit": limit}


@router.get("/rules/{rule_id}/incorrect")
async def rule_incorrect(
    rule_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> dict:
    """Paginated list of iterations the user has marked as incorrect.
    Deduped across triggers / iterations storage; newest first."""
    if not engine.get_rule(rule_id):
        raise HTTPException(404, "rule not found")
    rows, total = engine.list_incorrect(rule_id, offset, limit)
    return {"items": rows, "total": total, "offset": offset, "limit": limit}


@router.put("/rules/{rule_id}/iterations/{iteration_id}/score")
async def score_iteration_standalone(rule_id: str, iteration_id: int,
                                     payload: dict) -> dict:
    """Set the review verdict on a standalone iteration (All Iterations tab).
    The same score is mirrored into any triggered episode that contains this
    iteration_id so the two views stay in sync."""
    if not engine.get_rule(rule_id):
        raise HTTPException(404, "rule not found")
    score = payload.get("score") if isinstance(payload, dict) else None
    if score not in (None, "correct", "incorrect"):
        raise HTTPException(400, "score must be 'correct', 'incorrect', or null")
    try:
        scoring = engine.set_iteration_score(rule_id, iteration_id, score)
    except KeyError:
        raise HTTPException(404, "iteration not found")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "scoring": scoring}


@router.post("/rules/{rule_id}/iterations/{iteration_id}/promote")
async def promote_iteration(rule_id: str, iteration_id: int) -> dict:
    """Convert a non-triggered iteration into a triggered episode
    (false-negative correction). Increments the rule's trigger_count."""
    if not engine.get_rule(rule_id):
        raise HTTPException(404, "rule not found")
    try:
        result = engine.promote_iteration_to_triggered(rule_id, iteration_id)
    except KeyError:
        raise HTTPException(404, "iteration not found")
    except ValueError as e:
        raise HTTPException(409, str(e))
    return {"ok": True, **result}


@router.put("/rules/{rule_id}/triggers/{episode_id}/iterations/{iteration_id}/score")
async def score_iteration(rule_id: str, episode_id: str, iteration_id: int,
                          payload: dict) -> dict:
    """Tag a triggered iteration as correct / incorrect, or clear with null.
    Returns the rule-level scoring summary so the UI can refresh the badge."""
    if not engine.get_rule(rule_id):
        raise HTTPException(404, "rule not found")
    score = payload.get("score") if isinstance(payload, dict) else None
    if score not in (None, "correct", "incorrect"):
        raise HTTPException(400, "score must be 'correct', 'incorrect', or null")
    try:
        scoring = engine.score_iteration_in_episode(rule_id, episode_id, iteration_id, score)
    except FileNotFoundError:
        raise HTTPException(404, "no triggers stored")
    except KeyError:
        raise HTTPException(404, "episode not found")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "scoring": scoring}


@router.delete("/rules/{rule_id}/triggers/{episode_id}/iterations/{iteration_id}")
async def untrigger_iteration(rule_id: str, episode_id: str, iteration_id: int) -> dict:
    """Move a single iteration out of a triggered episode (false-positive
    correction). If the episode has no iterations left, the episode row is
    removed and the trigger count is decremented."""
    if not engine.get_rule(rule_id):
        raise HTTPException(404, "rule not found")
    try:
        result = engine.untrigger_iteration(rule_id, episode_id, iteration_id)
    except FileNotFoundError:
        raise HTTPException(404, "no triggers stored")
    except KeyError:
        raise HTTPException(404, "episode not found")
    except ValueError:
        raise HTTPException(404, "iteration not in episode")
    try:
        result["scoring"] = engine.compute_rule_scoring(rule_id)
    except Exception:
        pass
    return result


@router.delete("/rules/{rule_id}/history")
async def clear_rule_history(rule_id: str) -> dict:
    if not engine.get_rule(rule_id):
        raise HTTPException(404, "rule not found")
    d = engine._rule_dir(rule_id)  # noqa: SLF001
    for name in ("triggers.jsonl", "iterations.jsonl", "scores.json"):
        try:
            (d / name).unlink(missing_ok=True)
        except Exception:
            pass
    try:
        shutil.rmtree(d / "snap", ignore_errors=True)
    except Exception:
        pass
    # Reset the on-rule counters too.
    rule = engine.get_rule(rule_id)
    if rule is not None:
        rule["trigger_count"] = 0
        rule["iteration_count"] = 0
        from ..core.state import state as _state
        _state.save()
    return {"ok": True}


# ============================================================
# Snapshot serving
# ============================================================

@router.get("/rules/{rule_id}/snap/{iteration_id}/{camera}")
async def rule_snapshot(rule_id: str, iteration_id: int, camera: str):
    path: Path = engine.snapshot_path(rule_id, iteration_id, camera)
    if not path.exists():
        raise HTTPException(404, "snapshot not found")
    return FileResponse(path, media_type="image/jpeg")


# ============================================================
# Ollama provider — local vision model config + listing
# ============================================================

@router.get("/ollama/config")
async def ollama_get_config() -> dict:
    return {"url": state.ollama_url or ""}


@router.post("/ollama/config")
async def ollama_set_config(payload: dict) -> dict:
    url = (payload.get("url") or "").strip()
    state.ollama_url = url or None
    state.save()
    health = await ollama_client.health() if state.ollama_url else {"status": "idle", "message": "Not configured"}
    return {"url": state.ollama_url or "", "health": health}


@router.get("/ollama/health")
async def ollama_health() -> dict:
    return await ollama_client.health()


@router.get("/ollama/models")
async def ollama_models_list() -> dict:
    return {"models": await ollama_client.list_models()}


@router.get("/models")
async def list_picker_models() -> dict:
    """Aggregate model picker entries across all configured providers.
    Each entry: {id: "<provider>:<model>", label, provider, configured}."""
    options: list[dict] = []
    # Gemini — always offer the "auto" option so existing rules keep working;
    # the actual model is resolved per-iteration against the configured key.
    options.append({
        "id": "",
        "label": "Gemini · auto (default)",
        "provider": "gemini",
        "model": "auto",
        "configured": bool(state.gemini_api_key),
    })
    # Ollama — list every installed model. Filtering to "vision-capable"
    # would require keeping a list of model families up to date; we let the
    # user pick what they actually pulled.
    if state.ollama_url:
        try:
            mods = await ollama_client.list_models()
        except Exception:
            mods = []
        for m in mods:
            name = m.get("name") or ""
            if not name:
                continue
            options.append({
                "id": f"ollama:{name}",
                "label": f"Ollama · {name}",
                "provider": "ollama",
                "model": name,
                "configured": True,
            })
    return {"options": options}


# ============================================================
# Events WebSocket — shell-level subscribers receive all engine events.
# ============================================================

@router.websocket("/events/ws")
async def events_ws(websocket: WebSocket) -> None:
    await websocket.accept()
    q = engine.subscribe()
    try:
        # Drain forever. The browser doesn't send messages back; we ignore any
        # that arrive (handle them on a side task so we can notice disconnect).
        async def _drain_incoming() -> None:
            try:
                while True:
                    await websocket.receive_text()
            except WebSocketDisconnect:
                raise
            except Exception:
                raise

        drain = asyncio.create_task(_drain_incoming())
        try:
            while True:
                pop_task = asyncio.create_task(q.get())
                done, _pending = await asyncio.wait(
                    {pop_task, drain},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if drain in done:
                    pop_task.cancel()
                    return
                event = pop_task.result()
                try:
                    await websocket.send_text(json.dumps(event))
                except Exception:
                    return
        finally:
            drain.cancel()
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("events_ws fatal")
    finally:
        engine.unsubscribe(q)
        try:
            await websocket.close()
        except Exception:
            pass
