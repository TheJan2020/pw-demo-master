"""
AI-Camera Rules engine.

Owns the long-running per-rule asyncio tasks that drive saved rules — totally
separate from the Playground WebSocket runner in `routers/ai_camera.py`.
Reuses the helpers in that module (snapshot fetch, scan triggers, schema, …)
so the two surfaces share evaluation semantics.

History is written as append-only JSONL under `data/ai_camera/<rule_id>/`:

  triggers.jsonl    — every rule trip (always written)
  iterations.jsonl  — every scan result (only when rule.store_iterations is on)
  snap/<iter>_<cam>.jpg — frame stored alongside the entry that references it

Events are pushed to in-process subscribers via asyncio.Queue; the rules
router exposes a WebSocket that forwards them to any connected browser.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from google import genai
from google.genai import types

from ..core.state import state
from ..routers.ai_camera import (
    _fetch_frigate_snapshot,
    _ha_call_service,
    _resolve_vision_model,
    _build_system_instruction,
    _extract_json_object,
    _VERDICT_SCHEMA,
    _is_motion_active,
    _frigate_new_event_for,
    _ha_entity_state,
)
from . import ollama as ollama_client

logger = logging.getLogger("ai_camera_engine")

_DATA_ROOT = Path(__file__).resolve().parents[3] / "data" / "ai_camera"

# Per-rule asyncio tasks.
_TASKS: dict[str, asyncio.Task] = {}

# Event subscribers (the rules router's WS handler adds/removes its own queue).
_SUBSCRIBERS: list[asyncio.Queue] = []

# Cached vision-capable model — resolved once per API key.
_resolved_model: Optional[str] = None
_resolved_model_key: Optional[str] = None
_resolve_lock = asyncio.Lock()


# ============================================================
# Event bus
# ============================================================

def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    _SUBSCRIBERS.append(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    try:
        _SUBSCRIBERS.remove(q)
    except ValueError:
        pass


def _broadcast(event: dict) -> None:
    for q in list(_SUBSCRIBERS):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            # A subscriber is wedged; drop rather than block the engine.
            pass


# ============================================================
# Rule CRUD (operates on state.ai_camera_rules)
# ============================================================

_DEFAULT_RULE_FIELDS: dict[str, Any] = {
    "name": "Untitled rule",
    "enabled": True,
    "cameras": [],
    "rule": "",
    "scan": {"mode": "periodic", "period_s": 60},
    "action": None,
    "cooldown_s": 60,
    "fire_alarm": False,
    "store_iterations": False,
    "trigger_count": 0,
    "iteration_count": 0,
    # Model selector shaped as "<provider>:<model_id>". Empty / missing means
    # "use Gemini auto-resolved" (back-compat with rules created before
    # multi-provider support landed).
    "model": "",
    # Sustained-trigger duration: the action only fires when the model has
    # said triggered=true continuously for this many seconds. 0 = legacy
    # behaviour (fire on first true verdict).
    "min_duration_s": 0,
}


def _normalize_rule(rule: dict) -> dict:
    """Fill in defaults for any missing fields and clamp period_s."""
    out = dict(_DEFAULT_RULE_FIELDS)
    out.update({k: v for k, v in rule.items() if v is not None or k in ("action",)})
    scan = dict(out.get("scan") or {})
    try:
        period = int(scan.get("period_s") or 60)
    except (TypeError, ValueError):
        period = 60
    scan["period_s"] = max(1, min(300, period))
    scan["mode"] = scan.get("mode") or "periodic"
    out["scan"] = scan
    out["cameras"] = list(out.get("cameras") or [])
    out["enabled"] = bool(out.get("enabled"))
    out["fire_alarm"] = bool(out.get("fire_alarm"))
    out["store_iterations"] = bool(out.get("store_iterations"))
    try:
        out["cooldown_s"] = float(out.get("cooldown_s") or 0)
    except (TypeError, ValueError):
        out["cooldown_s"] = 0.0
    try:
        out["min_duration_s"] = max(0, int(out.get("min_duration_s") or 0))
    except (TypeError, ValueError):
        out["min_duration_s"] = 0
    return out


def list_rules() -> list[dict]:
    out = []
    for r in state.ai_camera_rules:
        copy = dict(r)
        try:
            copy["scoring"] = compute_rule_scoring(copy["id"])
        except Exception:
            pass
        out.append(copy)
    return out


def get_rule(rule_id: str) -> Optional[dict]:
    for r in state.ai_camera_rules:
        if r.get("id") == rule_id:
            return r
    return None


def create_rule(payload: dict) -> dict:
    rule = _normalize_rule(payload)
    rule["id"] = f"rule_{uuid.uuid4().hex[:10]}"
    rule["created_at"] = time.time()
    rule["updated_at"] = rule["created_at"]
    rule["trigger_count"] = 0
    rule["iteration_count"] = 0
    state.ai_camera_rules.append(rule)
    state.save()
    return rule


def update_rule(rule_id: str, patch: dict) -> Optional[dict]:
    rule = get_rule(rule_id)
    if not rule:
        return None
    merged = dict(rule)
    for k, v in patch.items():
        if k in ("id", "created_at", "trigger_count", "iteration_count"):
            continue
        merged[k] = v
    normalized = _normalize_rule(merged)
    normalized["id"] = rule["id"]
    normalized["created_at"] = rule.get("created_at") or time.time()
    normalized["trigger_count"] = rule.get("trigger_count", 0)
    normalized["iteration_count"] = rule.get("iteration_count", 0)
    normalized["updated_at"] = time.time()
    rule.clear()
    rule.update(normalized)
    state.save()
    return rule


def delete_rule(rule_id: str) -> bool:
    before = len(state.ai_camera_rules)
    state.ai_camera_rules[:] = [r for r in state.ai_camera_rules if r.get("id") != rule_id]
    if len(state.ai_camera_rules) == before:
        return False
    state.save()
    return True


# ============================================================
# History storage (JSONL + JPEG snapshots)
# ============================================================

def _rule_dir(rule_id: str) -> Path:
    p = _DATA_ROOT / rule_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def _snap_dir(rule_id: str) -> Path:
    p = _rule_dir(rule_id) / "snap"
    p.mkdir(parents=True, exist_ok=True)
    return p


def snapshot_path(rule_id: str, iteration_id: int, camera: str) -> Path:
    safe_cam = camera.replace("/", "_").replace("..", "_")
    return _snap_dir(rule_id) / f"{iteration_id}_{safe_cam}.jpg"


def _save_snapshots(rule_id: str, iteration_id: int, snapshots: dict[str, bytes]) -> list[str]:
    saved: list[str] = []
    for cam, blob in snapshots.items():
        try:
            snapshot_path(rule_id, iteration_id, cam).write_bytes(blob)
            saved.append(cam)
        except Exception:
            logger.exception("save snapshot failed for %s/%s", rule_id, cam)
    return saved


def _append_jsonl(path: Path, entry: dict) -> None:
    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, separators=(",", ":")) + "\n")
    except Exception:
        logger.exception("append jsonl failed: %s", path)


def _replace_last_jsonl(path: Path, entry: dict) -> None:
    """Replace the last line of a JSONL file with `entry`. Used to grow a
    trigger episode in place as new sustained iterations come in. Atomic via
    a side-by-side rewrite.

    No-op (falls back to append) if the file doesn't yet exist."""
    line = json.dumps(entry, separators=(",", ":")) + "\n"
    if not path.exists():
        try:
            with path.open("w", encoding="utf-8") as f:
                f.write(line)
        except Exception:
            logger.exception("replace_last jsonl create failed: %s", path)
        return
    try:
        with path.open("r", encoding="utf-8") as f:
            lines = f.readlines()
        if not lines:
            lines = [line]
        else:
            lines[-1] = line
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            f.writelines(lines)
        tmp.replace(path)
    except Exception:
        logger.exception("replace_last jsonl failed: %s", path)


def _read_jsonl_desc(path: Path, offset: int, limit: int) -> tuple[list[dict], int]:
    """Return (slice_desc, total) — newest first. Demo-scale read."""
    if not path.exists():
        return [], 0
    rows: list[dict] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        logger.exception("read jsonl failed: %s", path)
        return [], 0
    total = len(rows)
    rows.reverse()
    return rows[offset:offset + limit], total


def _scores_path(rule_id: str) -> Path:
    return _rule_dir(rule_id) / "scores.json"


def _load_scores(rule_id: str) -> dict[int, str]:
    """Read the canonical {iteration_id -> "correct"|"incorrect"} map for a
    rule. On first call, migrates any inline `score` fields previously
    written into the JSONL files."""
    p = _scores_path(rule_id)
    if p.exists():
        try:
            raw = json.loads(p.read_text())
            return {int(k): v for k, v in raw.items() if v in ("correct", "incorrect")}
        except Exception:
            logger.exception("scores.json read failed: %s", p)
            return {}
    # Backfill from any inline scores that the previous storage layout left
    # behind. Read both files; first occurrence wins on conflict.
    migrated: dict[int, str] = {}
    for path, inside_episodes in (
        (_rule_dir(rule_id) / "triggers.jsonl", True),
        (_rule_dir(rule_id) / "iterations.jsonl", False),
    ):
        if not path.exists():
            continue
        try:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except Exception:
                        continue
                    if inside_episodes:
                        for it in (row.get("sequence") or []):
                            s = it.get("score")
                            iid = it.get("iteration_id")
                            if s in ("correct", "incorrect") and iid is not None:
                                migrated.setdefault(int(iid), s)
                    else:
                        s = row.get("score")
                        iid = row.get("iteration_id")
                        if s in ("correct", "incorrect") and iid is not None:
                            migrated.setdefault(int(iid), s)
        except Exception:
            logger.exception("scores backfill read failed: %s", path)
    if migrated:
        _save_scores(rule_id, migrated)
    return migrated


def _save_scores(rule_id: str, scores: dict[int, str]) -> None:
    p = _scores_path(rule_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps({str(k): v for k, v in scores.items()}))
        tmp.replace(p)
    except Exception:
        logger.exception("scores.json write failed: %s", p)
        try: tmp.unlink(missing_ok=True)
        except Exception: pass


def _inject_scores_into_triggers(rule_id: str, rows: list[dict]) -> None:
    scores = _load_scores(rule_id)
    if not scores:
        return
    for ep in rows:
        for it in (ep.get("sequence") or []):
            iid = it.get("iteration_id")
            if iid is None: continue
            s = scores.get(int(iid))
            if s: it["score"] = s
            elif "score" in it and int(iid) not in scores:
                # Old inline value lingering after migration — strip it so the
                # canonical map is the only thing the UI ever sees.
                it.pop("score", None)


def _inject_scores_into_iterations(rule_id: str, rows: list[dict]) -> None:
    scores = _load_scores(rule_id)
    if not scores:
        return
    for row in rows:
        iid = row.get("iteration_id")
        if iid is None: continue
        s = scores.get(int(iid))
        if s: row["score"] = s
        elif "score" in row and int(iid) not in scores:
            row.pop("score", None)


def list_triggers(rule_id: str, offset: int, limit: int) -> tuple[list[dict], int]:
    rows, total = _read_jsonl_desc(_rule_dir(rule_id) / "triggers.jsonl", offset, limit)
    _inject_scores_into_triggers(rule_id, rows)
    return rows, total


def list_iterations(rule_id: str, offset: int, limit: int) -> tuple[list[dict], int]:
    rows, total = _read_jsonl_desc(_rule_dir(rule_id) / "iterations.jsonl", offset, limit)
    _inject_scores_into_iterations(rule_id, rows)
    return rows, total


def list_incorrect(rule_id: str, offset: int, limit: int) -> tuple[list[dict], int]:
    """Return paginated iterations the user has tagged as `incorrect`,
    deduped across both files (iterations.jsonl wins when both exist),
    newest first. Each row carries: iteration_id, ts, trigger_reason,
    verdict_reason, cameras, snap_cams, bbox, score, source ("trigger"|"iter").
    """
    scores = _load_scores(rule_id)
    bad_ids = {iid for iid, s in scores.items() if s == "incorrect"}
    if not bad_ids:
        return [], 0
    # Collect raw rows from both files. Build a dict keyed by iteration_id so
    # iterations that appear in both files only show once.
    rows_by_id: dict[int, dict] = {}

    iter_path = _rule_dir(rule_id) / "iterations.jsonl"
    if iter_path.exists():
        try:
            with iter_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except Exception:
                        continue
                    iid = row.get("iteration_id")
                    if iid is None or int(iid) not in bad_ids:
                        continue
                    rows_by_id[int(iid)] = {
                        "iteration_id":   int(iid),
                        "ts":             row.get("ts"),
                        "trigger_reason": row.get("trigger_reason") or "",
                        "verdict_reason": row.get("verdict_reason") or (
                            (row.get("parsed") or {}).get("reason")
                            if isinstance(row.get("parsed"), dict) else ""
                        ),
                        "cameras":        row.get("cameras") or [],
                        "snap_cams":      row.get("snap_cams") or row.get("cameras") or [],
                        "bbox":           row.get("bbox") or (
                            (row.get("parsed") or {}).get("bbox")
                            if isinstance(row.get("parsed"), dict) else None
                        ),
                        "triggered":      bool(row.get("triggered")),
                        "source":         "iter",
                    }
        except Exception:
            logger.exception("list_incorrect (iterations) failed: %s", iter_path)

    trig_path = _rule_dir(rule_id) / "triggers.jsonl"
    if trig_path.exists():
        try:
            with trig_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ep = json.loads(line)
                    except Exception:
                        continue
                    for it in (ep.get("sequence") or []):
                        iid = it.get("iteration_id")
                        if iid is None or int(iid) not in bad_ids:
                            continue
                        if int(iid) in rows_by_id:
                            continue   # iterations.jsonl already populated this one
                        rows_by_id[int(iid)] = {
                            "iteration_id":   int(iid),
                            "ts":             it.get("ts"),
                            "trigger_reason": it.get("trigger_reason") or "",
                            "verdict_reason": it.get("verdict_reason") or "",
                            "cameras":        it.get("cameras") or [],
                            "snap_cams":      it.get("snap_cams") or it.get("cameras") or [],
                            "bbox":           it.get("bbox"),
                            "triggered":      True,
                            "episode_id":     ep.get("episode_id"),
                            "source":         "trigger",
                        }
        except Exception:
            logger.exception("list_incorrect (triggers) failed: %s", trig_path)

    # Stamp scores (currently always 'incorrect' but explicit so the UI can
    # render the buttons in their correct state).
    for r in rows_by_id.values():
        r["score"] = "incorrect"

    ordered = sorted(rows_by_id.values(),
                     key=lambda r: (r.get("ts") or 0), reverse=True)
    total = len(ordered)
    return ordered[offset:offset + limit], total


def _collect_iteration_ids(rule_id: str) -> set[int]:
    """Distinct iteration_ids that exist anywhere on disk for this rule."""
    ids: set[int] = set()
    for path, inside_episodes in (
        (_rule_dir(rule_id) / "triggers.jsonl", True),
        (_rule_dir(rule_id) / "iterations.jsonl", False),
    ):
        if not path.exists():
            continue
        try:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except Exception:
                        continue
                    if inside_episodes:
                        for it in (row.get("sequence") or []):
                            iid = it.get("iteration_id")
                            if iid is not None:
                                ids.add(int(iid))
                    else:
                        iid = row.get("iteration_id")
                        if iid is not None:
                            ids.add(int(iid))
        except Exception:
            logger.exception("collect iteration_ids failed: %s", path)
    return ids


def compute_rule_scoring(rule_id: str) -> dict:
    """Aggregate scoring from the canonical scores.json, anchored against
    the distinct iteration_ids that actually exist on disk. Returns:
        {total, scored, unscored, correct, incorrect, accuracy_pct|null}
    """
    iter_ids = _collect_iteration_ids(rule_id)
    scores = _load_scores(rule_id)
    # Only count scores for iterations that still exist (orphans from removed
    # episodes/iterations are ignored without bothering to delete them).
    scored_ids = iter_ids & set(scores.keys())
    correct = sum(1 for iid in scored_ids if scores[iid] == "correct")
    incorrect = sum(1 for iid in scored_ids if scores[iid] == "incorrect")
    total = len(iter_ids)
    scored = len(scored_ids)
    accuracy = round(100.0 * correct / scored, 1) if scored else None
    return {
        "total":         total,
        "scored":        scored,
        "unscored":      total - scored,
        "correct":       correct,
        "incorrect":     incorrect,
        "accuracy_pct":  accuracy,
    }


def set_iteration_score(rule_id: str, iteration_id: int,
                        score: Optional[str]) -> dict:
    """Tag (or untag) an iteration with a review verdict. Stored in the
    canonical scores.json keyed by iteration_id, so both the Triggers and
    All Iterations views read the same value.

    Raises KeyError if the iteration isn't found anywhere on disk.
    Returns the updated rule-level scoring summary.
    """
    if score not in (None, "correct", "incorrect"):
        raise ValueError("invalid score")
    iid = int(iteration_id)
    if iid not in _collect_iteration_ids(rule_id):
        raise KeyError("iteration not found")
    scores = _load_scores(rule_id)
    if score is None:
        scores.pop(iid, None)
    else:
        scores[iid] = score
    _save_scores(rule_id, scores)
    return compute_rule_scoring(rule_id)


def score_iteration_in_episode(
    rule_id: str, episode_id: str, iteration_id: int, score: Optional[str],
) -> dict:
    """Compatibility shim — kept for the PUT endpoint that takes episode_id
    in its path. Episode lookup is informational only; the score is keyed by
    iteration_id alone."""
    return set_iteration_score(rule_id, iteration_id, score)


def promote_iteration_to_triggered(rule_id: str, iteration_id: int) -> dict:
    """Convert a non-triggered standalone iteration into a brand-new
    triggered episode (one iteration in the sequence). Used to correct
    a false-negative from the All Iterations tab.

    Returns {"episode": <new episode>, "scoring": <updated summary>}.
    Raises KeyError if the iteration isn't in iterations.jsonl, or
    ValueError if it's already part of a triggered episode.
    """
    iter_path = _rule_dir(rule_id) / "iterations.jsonl"
    if not iter_path.exists():
        raise KeyError("no iterations stored")

    # Locate the source row.
    src: Optional[dict] = None
    rows: list[dict] = []
    try:
        with iter_path.open("r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                try:
                    row = json.loads(s)
                except Exception:
                    continue
                if int(row.get("iteration_id", -1)) == int(iteration_id):
                    src = row
                rows.append(row)
    except Exception:
        logger.exception("promote: read iterations failed: %s", iter_path)
        raise
    if src is None:
        raise KeyError("iteration not found")

    # Refuse if this iteration already lives in some triggered episode.
    trig_path = _rule_dir(rule_id) / "triggers.jsonl"
    episodes: list[dict] = []
    if trig_path.exists():
        try:
            with trig_path.open("r", encoding="utf-8") as f:
                for line in f:
                    s = line.strip()
                    if not s:
                        continue
                    try:
                        ep = json.loads(s)
                    except Exception:
                        continue
                    for it in (ep.get("sequence") or []):
                        if int(it.get("iteration_id", -1)) == int(iteration_id):
                            raise ValueError("iteration already in a triggered episode")
                    episodes.append(ep)
        except ValueError:
            raise
        except Exception:
            logger.exception("promote: read triggers failed: %s", trig_path)
            raise

    # Build the new single-iteration episode. Mirror the shape produced by the
    # live engine so the UI renders it identically.
    new_iter_entry = {
        "iteration_id":   int(iteration_id),
        "ts":             src.get("ts") or time.time(),
        "trigger_reason": src.get("trigger_reason") or "",
        "verdict_reason": src.get("verdict_reason") or (
            (src.get("parsed") or {}).get("reason") if isinstance(src.get("parsed"), dict) else ""
        ),
        "cameras":        src.get("cameras") or [],
        "snap_cams":      src.get("snap_cams") or src.get("cameras") or [],
        "bbox":           src.get("bbox") or (
            (src.get("parsed") or {}).get("bbox") if isinstance(src.get("parsed"), dict) else None
        ),
    }
    # Carry over an existing score so promotion doesn't silently clear it.
    if src.get("score"):
        new_iter_entry["score"] = src["score"]

    new_ep = {
        "episode_id":      f"ep_promoted_{int(time.time()*1000)}_{int(iteration_id)}",
        "rule_id":         rule_id,
        "rule_name":       (get_rule(rule_id) or {}).get("name") or rule_id,
        "started_ts":      new_iter_entry["ts"],
        "fired_ts":        new_iter_entry["ts"],
        "last_ts":         new_iter_entry["ts"],
        "iteration_id":    int(iteration_id),
        "trigger_reason":  new_iter_entry["trigger_reason"],
        "verdict_reason":  new_iter_entry["verdict_reason"],
        "cameras":         new_iter_entry["cameras"],
        "snap_cams":       new_iter_entry["snap_cams"],
        "bbox":            new_iter_entry["bbox"],
        "min_duration_s":  0,
        "provider":        src.get("provider"),
        "model":           src.get("model"),
        "sequence":        [new_iter_entry],
        "promoted":        True,   # marker so we know this came from a manual promote
    }

    _append_jsonl(trig_path, new_ep)

    # Flip the standalone iteration's `triggered` field so the All Iterations
    # view reflects the correction next time it's loaded.
    if src.get("triggered") is not True:
        src["triggered"] = True
        tmp = iter_path.with_suffix(iter_path.suffix + ".tmp")
        try:
            with tmp.open("w", encoding="utf-8") as f:
                for r in rows:
                    f.write(json.dumps(r, separators=(",", ":")) + "\n")
            tmp.replace(iter_path)
        except Exception:
            logger.exception("promote: rewrite iterations failed: %s", iter_path)

    rule = get_rule(rule_id)
    if rule is not None:
        rule["trigger_count"] = int(rule.get("trigger_count", 0)) + 1
        state.save()

    return {"episode": new_ep, "scoring": compute_rule_scoring(rule_id)}


def untrigger_iteration(rule_id: str, episode_id: str, iteration_id: int) -> dict:
    """Remove one iteration from a triggered episode in triggers.jsonl.
    If the episode's sequence becomes empty, the episode row is removed and
    the rule's `trigger_count` decremented.

    Returns:
      {"removed": True, "episode_removed": bool, "episode": <updated or None>}
      or raises FileNotFoundError / KeyError / ValueError as appropriate.
    """
    path = _rule_dir(rule_id) / "triggers.jsonl"
    if not path.exists():
        raise FileNotFoundError("no triggers")
    try:
        with path.open("r", encoding="utf-8") as f:
            raw_lines = f.readlines()
    except Exception:
        logger.exception("untrigger: read failed: %s", path)
        raise
    episodes: list[dict] = []
    for line in raw_lines:
        s = line.strip()
        if not s:
            continue
        try:
            episodes.append(json.loads(s))
        except Exception:
            continue

    target_idx = next(
        (i for i, ep in enumerate(episodes) if ep.get("episode_id") == episode_id),
        -1,
    )
    if target_idx < 0:
        raise KeyError("episode not found")

    ep = episodes[target_idx]
    seq = list(ep.get("sequence") or [])
    before = len(seq)
    seq = [it for it in seq if int(it.get("iteration_id", -1)) != int(iteration_id)]
    if len(seq) == before:
        raise ValueError("iteration not in episode")

    episode_removed = False
    updated_ep: dict | None = None
    if not seq:
        episodes.pop(target_idx)
        episode_removed = True
        rule = get_rule(rule_id)
        if rule is not None:
            rule["trigger_count"] = max(0, int(rule.get("trigger_count", 0)) - 1)
            state.save()
    else:
        ep["sequence"] = seq
        # Refresh top-level summary fields from the trailing iteration so the
        # episode card keeps showing accurate "last" metadata after removal.
        last = seq[-1]
        ep["last_ts"]        = last.get("ts", ep.get("last_ts"))
        ep["iteration_id"]   = last.get("iteration_id", ep.get("iteration_id"))
        ep["verdict_reason"] = last.get("verdict_reason", ep.get("verdict_reason"))
        ep["cameras"]        = last.get("cameras", ep.get("cameras"))
        ep["snap_cams"]      = last.get("snap_cams", ep.get("snap_cams"))
        if last.get("bbox"):
            ep["bbox"]       = last["bbox"]
        updated_ep = ep

    # Atomic rewrite.
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            for e in episodes:
                f.write(json.dumps(e, separators=(",", ":")) + "\n")
        tmp.replace(path)
    except Exception:
        logger.exception("untrigger: rewrite failed: %s", path)
        try: tmp.unlink(missing_ok=True)
        except Exception: pass
        raise

    # Best-effort: drop the snapshots for that iteration so the disk doesn't
    # keep growing with false-positive frames.
    try:
        snap_dir = _snap_dir(rule_id)
        if snap_dir.exists():
            for f in snap_dir.glob(f"{int(iteration_id)}_*.jpg"):
                try: f.unlink()
                except Exception: pass
    except Exception:
        pass

    return {"removed": True, "episode_removed": episode_removed, "episode": updated_ep}


# ============================================================
# Gemini iteration runner (engine version — no WS plumbing)
# ============================================================

async def _resolve_model_for_engine(client: genai.Client) -> str:
    global _resolved_model, _resolved_model_key
    async with _resolve_lock:
        if _resolved_model and _resolved_model_key == state.gemini_api_key:
            return _resolved_model
        model, _candidates = await _resolve_vision_model(client)
        _resolved_model = model
        _resolved_model_key = state.gemini_api_key
        return model


def _parse_model_selector(selector: str) -> tuple[str, str]:
    """Split a `<provider>:<model>` selector into ('gemini'|'ollama', model_id).
    Empty selector → ('gemini', '') meaning "use auto-resolved default"."""
    s = (selector or "").strip()
    if not s:
        return "gemini", ""
    if ":" not in s:
        return "gemini", s  # tolerate bare model names — assume Gemini
    provider, _, model = s.partition(":")
    provider = provider.strip().lower()
    model = model.strip()
    if provider not in ("gemini", "ollama"):
        return "gemini", model
    return provider, model


async def _run_gemini_iteration(
    client: genai.Client,
    model: str,
    rule_text: str,
    snapshots: dict[str, bytes],
) -> dict:
    parts: list[types.Part] = []
    for cam, img in snapshots.items():
        parts.append(types.Part(inline_data=types.Blob(data=img, mime_type="image/jpeg")))
        parts.append(types.Part(text=f"(frame above is from camera: {cam})"))
    parts.append(types.Part(text="Apply the rule and reply now with the JSON verdict."))

    gen_config = types.GenerateContentConfig(
        system_instruction=_build_system_instruction(rule_text),
        response_mime_type="application/json",
        response_schema=_VERDICT_SCHEMA,
        temperature=0.1,
    )
    try:
        response = await client.aio.models.generate_content(
            model=model,
            contents=[types.Content(role="user", parts=parts)],
            config=gen_config,
        )
    except Exception as e:
        logger.warning("gemini generate_content failed: %s", e)
        return {"triggered": False, "parsed": {"error": True, "message": str(e)},
                "response_text": f"error: {type(e).__name__}: {e}"}
    text_buf = (response.text or "").strip()
    parsed = _extract_json_object(text_buf) or {}
    triggered = bool(parsed.get("triggered")) if isinstance(parsed, dict) else False
    return {"triggered": triggered, "parsed": parsed, "response_text": text_buf}


async def _run_ollama_iteration(
    model: str,
    rule_text: str,
    snapshots: dict[str, bytes],
) -> dict:
    # Camera-label prompt: Ollama doesn't accept interleaved text/images the
    # way Gemini does, so we put the labels in a single user prompt that
    # references the images in order.
    cam_list = ", ".join(snapshots.keys())
    user_prompt = (
        f"Frames provided in order: {cam_list}.\n"
        "Apply the rule and reply now with the JSON verdict."
    )
    result = await ollama_client.generate_verdict(
        model=model,
        system_instruction=_build_system_instruction(rule_text),
        user_prompt=user_prompt,
        images=list(snapshots.values()),
    )
    if not result.get("ok"):
        msg = result.get("error") or "unknown ollama error"
        return {"triggered": False, "parsed": {"error": True, "message": msg},
                "response_text": f"error: {msg}"}
    text_buf = (result.get("text") or "").strip()
    parsed = _extract_json_object(text_buf) or {}
    triggered = bool(parsed.get("triggered")) if isinstance(parsed, dict) else False
    return {"triggered": triggered, "parsed": parsed, "response_text": text_buf}


async def _run_engine_iteration(
    client: genai.Client,
    gemini_default_model: str,
    rule_text: str,
    cameras: list[str],
    model_selector: str,
) -> dict:
    """Pull snapshots, dispatch to the configured provider, return verdict."""
    snapshots: dict[str, bytes] = {}
    for cam in cameras:
        img = await _fetch_frigate_snapshot(cam)
        if img:
            snapshots[cam] = img

    started_at = time.time()
    if not snapshots:
        return {
            "started_at": started_at,
            "finished_at": time.time(),
            "snapshots": {},
            "triggered": False,
            "parsed": {"error": True, "message": "no snapshots"},
            "response_text": "",
            "provider": None,
            "model": None,
        }

    provider, model_id = _parse_model_selector(model_selector)
    if provider == "ollama":
        if not ollama_client.is_configured():
            return {
                "started_at": started_at,
                "finished_at": time.time(),
                "snapshots": snapshots,
                "triggered": False,
                "parsed": {"error": True, "message": "Ollama URL not configured"},
                "response_text": "error: Ollama URL not configured",
                "provider": "ollama",
                "model": model_id,
            }
        out = await _run_ollama_iteration(model_id, rule_text, snapshots)
        used_model = model_id
    else:
        used_model = model_id or gemini_default_model
        out = await _run_gemini_iteration(client, used_model, rule_text, snapshots)
        provider = "gemini"

    return {
        "started_at": started_at,
        "finished_at": time.time(),
        "snapshots": snapshots,
        "triggered": out["triggered"],
        "parsed": out["parsed"],
        "response_text": out["response_text"],
        "provider": provider,
        "model": used_model,
    }


# ============================================================
# Scan state machine (rules engine)
#
# Distinct from the Playground's `_RunContext` because the Rules engine
# implements a different `periodic_motion` semantic that the user asked for:
#
#   paused:  no countdown running; waiting for motion. On motion ON → fire an
#            iteration immediately and switch to active.
#   active:  wall-clock countdown ticks regardless of mid-countdown motion.
#            When it reaches 0, fire an iteration. If motion is still ON at
#            that moment, restart the countdown (stay active). If motion is
#            OFF, switch back to paused.
#
# The Playground keeps its accumulated-motion-time semantics — see CLAUDE.md.
# ============================================================

class _RulesRunContext:
    def __init__(self, scan: dict, cameras: list[str]) -> None:
        self.scan = scan
        self.cameras = list(cameras or [])
        self.mode = (scan.get("mode") or "periodic").lower()
        self.period_s = max(1, int(scan.get("period_s") or 30))
        # Faster scan rate used while a sustained candidate is in flight, so
        # we don't miss the moment the condition flips back off and we don't
        # take ages to confirm continuity.
        self.quick_period_s = max(2, min(5, self.period_s))
        # Flipped on by _rule_session whenever the sustained-state machine has
        # an open candidate. _rules_trigger_stream reads this on each tick.
        self.sustained_candidate: bool = False

        # periodic
        self.last_scan_monotonic: Optional[float] = None

        # periodic_motion (new semantics)
        self.pm_active: bool = False
        self.pm_countdown_started: Optional[float] = None
        self.motion_active: bool = False

    def on_motion_change(self, active: bool) -> None:
        self.motion_active = active

    def countdown(self) -> Optional[dict]:
        if self.mode == "periodic":
            if self.last_scan_monotonic is None:
                return {"mode": "periodic", "total_s": self.period_s,
                        "remaining_s": 0, "paused": False, "waiting_for_motion": False}
            elapsed = time.monotonic() - self.last_scan_monotonic
            return {"mode": "periodic", "total_s": self.period_s,
                    "remaining_s": max(0, int(round(self.period_s - elapsed))),
                    "paused": False, "waiting_for_motion": False}
        if self.mode == "periodic_motion":
            if not self.pm_active:
                return {"mode": "periodic_motion", "total_s": self.period_s,
                        "remaining_s": self.period_s,
                        "paused": True, "waiting_for_motion": True}
            elapsed = time.monotonic() - (self.pm_countdown_started or time.monotonic())
            return {"mode": "periodic_motion", "total_s": self.period_s,
                    "remaining_s": max(0, int(round(self.period_s - elapsed))),
                    "paused": False, "waiting_for_motion": False}
        return None


async def _rules_trigger_stream(ctx: _RulesRunContext):
    if ctx.mode == "periodic":
        ctx.last_scan_monotonic = time.monotonic()
        yield "initial"
        while True:
            # Sleep in 0.5s slices so a sustained candidate can shorten the
            # next iteration without waiting out the original full period.
            sleep_until = time.monotonic() + (
                ctx.quick_period_s if ctx.sustained_candidate else ctx.period_s
            )
            while time.monotonic() < sleep_until:
                await asyncio.sleep(0.5)
                # If a candidate just opened/closed, recompute the deadline.
                target = ctx.quick_period_s if ctx.sustained_candidate else ctx.period_s
                new_deadline = (ctx.last_scan_monotonic or time.monotonic()) + target
                if new_deadline < sleep_until:
                    sleep_until = new_deadline
            ctx.last_scan_monotonic = time.monotonic()
            yield "periodic"
        return

    if ctx.mode == "motion":
        last_ts = time.time()
        while True:
            await asyncio.sleep(2)
            if await _is_motion_active(ctx.cameras) or await _frigate_new_event_for(ctx.cameras, last_ts):
                last_ts = time.time()
                yield "motion"
        return

    if ctx.mode == "periodic_motion":
        # State machine described in the comment block above.
        while True:
            current = await _is_motion_active(ctx.cameras)
            ctx.on_motion_change(current)

            if not ctx.pm_active:
                if current:
                    # Fire immediately on the motion edge, then arm the countdown
                    # once the iteration completes (see code after `yield`).
                    yield "motion_initial"
                    ctx.pm_active = True
                    ctx.pm_countdown_started = time.monotonic()
            else:
                elapsed = time.monotonic() - (ctx.pm_countdown_started or time.monotonic())
                if elapsed >= ctx.period_s:
                    yield "periodic_motion"
                    # Re-sample motion *after* the iteration ran — that's the
                    # state that decides whether we stay armed or pause.
                    now_motion = await _is_motion_active(ctx.cameras)
                    ctx.on_motion_change(now_motion)
                    if now_motion:
                        ctx.pm_countdown_started = time.monotonic()
                    else:
                        ctx.pm_active = False
                        ctx.pm_countdown_started = None

            await asyncio.sleep(0.5)
        return

    if ctx.mode == "entity_state":
        entity_id = ctx.scan.get("entity_id")
        target = str(ctx.scan.get("target_state") or "")
        if not entity_id or not target:
            while True:
                await asyncio.sleep(60)
        prev_match = False
        while True:
            await asyncio.sleep(2)
            curr = await _ha_entity_state(entity_id)
            now_match = curr == target
            if now_match and not prev_match:
                yield "entity_state"
            prev_match = now_match
        return

    # Unknown mode → behave like periodic.
    ctx.last_scan_monotonic = time.monotonic()
    yield "initial"
    while True:
        await asyncio.sleep(ctx.period_s)
        ctx.last_scan_monotonic = time.monotonic()
        yield "periodic"


# ============================================================
# Per-rule task
# ============================================================

async def _rule_session(rule_id: str) -> None:
    """One full run of a rule: build context, iterate forever, write history.
    Crashes are caught at the caller, which sleeps and restarts."""
    rule = get_rule(rule_id)
    if not rule:
        return
    if not state.gemini_api_key:
        logger.info("rule %s skipped — Gemini API key not configured", rule_id)
        await asyncio.sleep(30)
        return

    cameras = list(rule.get("cameras") or [])
    rule_text = rule.get("rule") or ""
    scan = dict(rule.get("scan") or {"mode": "periodic", "period_s": 60})
    if not cameras or not rule_text:
        logger.info("rule %s skipped — missing cameras or rule text", rule_id)
        await asyncio.sleep(30)
        return

    client = genai.Client(api_key=state.gemini_api_key)
    try:
        model = await _resolve_model_for_engine(client)
    except Exception:
        logger.exception("vision model resolve failed for rule %s", rule_id)
        await asyncio.sleep(30)
        return

    ctx = _RulesRunContext(scan, cameras)
    iter_id = _next_iteration_id(rule_id)
    last_action_ts = 0.0

    # Sustained-trigger state machine.
    #   triggered_since: monotonic when the *current run* of true verdicts began
    #   sustained_fired: True once the action has fired for this run (prevents
    #                    re-firing every subsequent confirming scan).
    #   current_episode: while triggered=true continues, buffer the per-
    #                    iteration metadata here. The trigger row in
    #                    triggers.jsonl is the same dict; we rewrite its
    #                    tail line as the episode grows so reload-from-disk
    #                    matches what the live UI sees.
    # A single triggered=false verdict resets all three.
    triggered_since: Optional[float] = None
    sustained_fired: bool = False
    current_episode: Optional[dict] = None

    countdown_task = asyncio.create_task(
        _emit_countdown_loop(rule_id, ctx),
        name=f"ai_rule_countdown:{rule_id}",
    )

    gen = _rules_trigger_stream(ctx)
    try:
        async for reason in gen:
            # Re-read the rule each iteration so toggles to store_iterations
            # / fire_alarm / action take effect without a task restart.
            rule = get_rule(rule_id)
            if not rule or not rule.get("enabled"):
                return

            result = await _run_engine_iteration(
                client, model, rule_text, cameras, rule.get("model") or "",
            )

            # If Frigate returned no frames at all, no model call happened —
            # don't count this as an iteration, don't write history. Surface
            # the skip so the UI can show a meaningful message.
            if not result["snapshots"]:
                _broadcast({
                    "type": "iteration_skipped",
                    "rule_id": rule_id,
                    "rule_name": rule.get("name") or rule_id,
                    "trigger_reason": reason,
                    "reason": "no snapshots from Frigate",
                    "ts": result["finished_at"],
                })
                continue

            iter_id += 1
            triggered = result["triggered"]
            parsed = result.get("parsed") or {}
            verdict_reason = (parsed.get("reason") or "")[:200] if isinstance(parsed, dict) else ""

            saved_cams = _save_snapshots(rule_id, iter_id, result["snapshots"])

            entry = {
                "iteration_id": iter_id,
                "ts": result["finished_at"],
                "started_at": result["started_at"],
                "finished_at": result["finished_at"],
                "trigger_reason": reason,
                "verdict_reason": verdict_reason,
                "cameras": list(result["snapshots"].keys()),
                "snap_cams": saved_cams,
                "triggered": triggered,
                "parsed": parsed,
                "response_text": result.get("response_text", "")[:2000],
                "provider": result.get("provider"),
                "model": result.get("model"),
            }

            if rule.get("store_iterations"):
                _append_jsonl(_rule_dir(rule_id) / "iterations.jsonl", entry)

            rule["iteration_count"] = int(rule.get("iteration_count", 0)) + 1
            state.save()

            _broadcast({
                "type": "iteration",
                "rule_id": rule_id,
                "rule_name": rule.get("name") or rule_id,
                "iteration_id": iter_id,
                "iteration_count": rule["iteration_count"],
                "triggered": triggered,
                "trigger_reason": reason,
                "verdict_reason": verdict_reason,
                "ts": entry["ts"],
            })

            # ----- Sustained-trigger state machine -----------------------
            # Pull min_duration_s live so changes via the API take effect on
            # the very next iteration without restarting the task.
            try:
                min_duration_s = max(0, int(rule.get("min_duration_s") or 0))
            except (TypeError, ValueError):
                min_duration_s = 0

            now_m = time.monotonic()

            if triggered:
                if triggered_since is None:
                    triggered_since = now_m
                    sustained_fired = False
                elapsed = now_m - triggered_since
                # We treat the rule as "sustained" the moment we've seen the
                # condition true for min_duration_s of monotonic time. With
                # min_duration_s == 0 this is true on the first hit, matching
                # legacy behaviour.
                is_sustained = elapsed >= min_duration_s
                # Open a candidate when we need confirmation; close it the
                # moment we've fired so the scan rate can relax.
                ctx.sustained_candidate = (min_duration_s > 0) and not is_sustained
            else:
                triggered_since = None
                sustained_fired = False
                ctx.sustained_candidate = False
                is_sustained = False

            # Broadcast per-iteration progress so the UI can show "candidate
            # detected, sustaining for Ns / Ms".
            if triggered and min_duration_s > 0 and triggered_since is not None:
                _broadcast({
                    "type": "sustained_progress",
                    "rule_id": rule_id,
                    "rule_name": rule.get("name") or rule_id,
                    "iteration_id": iter_id,
                    "min_duration_s": min_duration_s,
                    "elapsed_s": int(round(now_m - triggered_since)),
                    "remaining_s": max(0, int(round(min_duration_s - (now_m - triggered_since)))),
                    "sustained": bool(is_sustained),
                    "ts": entry["ts"],
                })
            elif not triggered and triggered_since is None and min_duration_s > 0:
                # Explicit "reset" event lets the UI clear any candidate chip.
                _broadcast({
                    "type": "sustained_reset",
                    "rule_id": rule_id,
                    "ts": entry["ts"],
                })

            # ----- Trigger episode (one row per continuous run of trues) ---
            triggers_path = _rule_dir(rule_id) / "triggers.jsonl"

            # Per-iteration record we attach to the episode. Includes the
            # bbox the model returned (if any) so the UI can draw it later.
            parsed_bbox = parsed.get("bbox") if isinstance(parsed, dict) else None
            iter_entry = {
                "iteration_id": iter_id,
                "ts": entry["ts"],
                "trigger_reason": reason,
                "verdict_reason": verdict_reason,
                "cameras": entry["cameras"],
                "snap_cams": saved_cams,
                "bbox": parsed_bbox,
            }

            if not triggered:
                # Run ended (or was never started). Reset episode state so the
                # next true verdict starts a fresh row.
                if current_episode is not None:
                    _broadcast({
                        "type": "trigger_complete",
                        "rule_id": rule_id,
                        "episode_id": current_episode["episode_id"],
                        "iterations": len(current_episode.get("sequence") or []),
                        "ts": entry["ts"],
                    })
                current_episode = None
            elif not is_sustained:
                # Candidate phase — model says true but we haven't crossed
                # min_duration_s yet. Don't write a trigger row yet, just
                # buffer the iteration so it becomes part of the row when we
                # do cross the threshold.
                if current_episode is None:
                    current_episode = {
                        "episode_id": f"ep_{int(time.time()*1000)}_{iter_id}",
                        "rule_id": rule_id,
                        "rule_name": rule.get("name") or rule_id,
                        "started_ts": entry["ts"],
                        "trigger_reason": reason,
                        "verdict_reason": verdict_reason,
                        "min_duration_s": min_duration_s,
                        "provider": result.get("provider"),
                        "model": result.get("model"),
                        "sequence": [],
                    }
                current_episode["sequence"].append(iter_entry)
            elif is_sustained and not sustained_fired:
                # Threshold reached — write the trigger row for the first time
                # (with the full candidate sequence already inside), fire the
                # action, broadcast the trigger event.
                sustained_fired = True
                if current_episode is None:
                    # min_duration_s == 0 path: episode begins and fires in
                    # the same iteration.
                    current_episode = {
                        "episode_id": f"ep_{int(time.time()*1000)}_{iter_id}",
                        "rule_id": rule_id,
                        "rule_name": rule.get("name") or rule_id,
                        "started_ts": entry["ts"],
                        "trigger_reason": reason,
                        "verdict_reason": verdict_reason,
                        "min_duration_s": min_duration_s,
                        "provider": result.get("provider"),
                        "model": result.get("model"),
                        "sequence": [],
                    }
                current_episode["sequence"].append(iter_entry)
                # Fields kept up to date on every confirming iteration so the
                # most recent reason / iteration_id is always at the top level.
                current_episode["fired_ts"]      = entry["ts"]
                current_episode["last_ts"]       = entry["ts"]
                current_episode["iteration_id"]  = iter_id
                current_episode["verdict_reason"] = verdict_reason
                current_episode["cameras"]       = entry["cameras"]
                current_episode["snap_cams"]     = saved_cams
                current_episode["bbox"]          = parsed_bbox

                _append_jsonl(triggers_path, current_episode)
                rule["trigger_count"] = int(rule.get("trigger_count", 0)) + 1
                state.save()

                _broadcast({
                    "type": "trigger",
                    "rule_id": rule_id,
                    "rule_name": rule.get("name") or rule_id,
                    "fire_alarm": bool(rule.get("fire_alarm")),
                    "episode_id": current_episode["episode_id"],
                    "iteration_id": iter_id,
                    "trigger_reason": reason,
                    "verdict_reason": verdict_reason,
                    "cameras": entry["cameras"],
                    "snap_cams": saved_cams,
                    "ts": entry["ts"],
                    "min_duration_s": min_duration_s,
                    "sequence": current_episode["sequence"],
                })

                action = rule.get("action")
                cooldown_s = float(rule.get("cooldown_s") or 0)
                if action:
                    now = time.time()
                    if cooldown_s and (now - last_action_ts) < cooldown_s:
                        logger.info("rule %s action skipped (cooldown)", rule_id)
                    else:
                        last_action_ts = now
                        try:
                            await _ha_call_service(action)
                            logger.info("rule %s action fired", rule_id)
                        except Exception:
                            logger.exception("rule %s action failed", rule_id)
            else:
                # Already-fired episode that's still going. Append this
                # iteration to the sequence and grow the row in place.
                if current_episode is not None:
                    current_episode["sequence"].append(iter_entry)
                    current_episode["last_ts"]      = entry["ts"]
                    current_episode["iteration_id"] = iter_id
                    current_episode["verdict_reason"] = verdict_reason
                    current_episode["cameras"]      = entry["cameras"]
                    current_episode["snap_cams"]    = saved_cams
                    if parsed_bbox:
                        current_episode["bbox"] = parsed_bbox

                    _replace_last_jsonl(triggers_path, current_episode)

                    _broadcast({
                        "type": "trigger_update",
                        "rule_id": rule_id,
                        "episode_id": current_episode["episode_id"],
                        "iteration": iter_entry,
                        "ts": entry["ts"],
                    })
    finally:
        countdown_task.cancel()
        try:
            await countdown_task
        except (asyncio.CancelledError, Exception):
            pass
        try:
            await gen.aclose()
        except Exception:
            pass


async def _emit_countdown_loop(rule_id: str, ctx: _RulesRunContext) -> None:
    """Broadcast `countdown` events for this rule once per second.
    Only meaningful for periodic / periodic_motion modes — `ctx.countdown()`
    returns None for the other modes and we just skip the emit.

    Gated on `_SUBSCRIBERS`: when nobody is listening, we still tick but
    don't enqueue anything, so the engine doesn't spend cycles on dead UI."""
    while True:
        try:
            await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            raise
        if not _SUBSCRIBERS:
            continue
        cd = ctx.countdown()
        if cd is None:
            continue
        rule = get_rule(rule_id)
        _broadcast({
            "type": "countdown",
            "rule_id": rule_id,
            "rule_name": (rule or {}).get("name") or rule_id,
            **cd,
        })


def _next_iteration_id(rule_id: str) -> int:
    """Look at saved files to figure out where to resume iteration IDs.
    Keeps snapshot filenames monotonic across restarts."""
    snap = _snap_dir(rule_id)
    best = 0
    try:
        for p in snap.iterdir():
            name = p.stem  # "<iter>_<cam>"
            head = name.split("_", 1)[0]
            try:
                n = int(head)
                if n > best:
                    best = n
            except ValueError:
                continue
    except FileNotFoundError:
        return 0
    return best


async def _rule_task(rule_id: str) -> None:
    backoff = 5
    while True:
        rule = get_rule(rule_id)
        if not rule or not rule.get("enabled"):
            return
        try:
            await _rule_session(rule_id)
            # Session returned cleanly (rule disabled or deleted) — exit.
            return
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("rule %s session crashed; retrying in %ds", rule_id, backoff)
            try:
                await asyncio.sleep(backoff)
            except asyncio.CancelledError:
                raise
            backoff = min(backoff * 2, 60)


# ============================================================
# Engine lifecycle
# ============================================================

async def start_engine() -> None:
    """Spin up tasks for every enabled rule. Idempotent."""
    for rule in state.ai_camera_rules:
        rid = rule.get("id")
        if not rid or not rule.get("enabled"):
            continue
        if rid in _TASKS and not _TASKS[rid].done():
            continue
        _TASKS[rid] = asyncio.create_task(_rule_task(rid), name=f"ai_rule:{rid}")


async def stop_engine() -> None:
    tasks = list(_TASKS.values())
    _TASKS.clear()
    for t in tasks:
        t.cancel()
    for t in tasks:
        try:
            await t
        except (asyncio.CancelledError, Exception):
            pass


async def apply_rule_change(rule_id: str) -> None:
    """Stop the rule's task and restart it if the rule still exists and is enabled."""
    old = _TASKS.pop(rule_id, None)
    if old:
        old.cancel()
        try:
            await old
        except (asyncio.CancelledError, Exception):
            pass
    rule = get_rule(rule_id)
    if rule and rule.get("enabled"):
        _TASKS[rule_id] = asyncio.create_task(_rule_task(rule_id), name=f"ai_rule:{rule_id}")
    _broadcast({"type": "rule_updated", "rule_id": rule_id})


async def apply_rule_delete(rule_id: str) -> None:
    old = _TASKS.pop(rule_id, None)
    if old:
        old.cancel()
        try:
            await old
        except (asyncio.CancelledError, Exception):
            pass
    _broadcast({"type": "rule_deleted", "rule_id": rule_id})
