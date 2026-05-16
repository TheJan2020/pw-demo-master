"""
JSON-file dummy DB per vertical.

`data/demos/<slug>.json` holds the mutable runtime data. On first
access, if the file is missing we copy from the vertical's checked-in
`seed.json` (at `backend/app/demos/<slug>/seed.json`). Mutations write
back to the runtime file — the seed never changes.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

_DATA_ROOT = Path(__file__).resolve().parents[4] / "data" / "demos"
_DEMOS_ROOT = Path(__file__).resolve().parents[1]
_lock = threading.Lock()


def _slug_to_pkg(slug: str) -> str:
    """URL slug → Python package name (hyphens → underscores)."""
    return slug.replace("-", "_")


def db_path(slug: str) -> Path:
    return _DATA_ROOT / f"{_slug_to_pkg(slug)}.json"


def seed_path(slug: str) -> Path:
    return _DEMOS_ROOT / _slug_to_pkg(slug) / "seed.json"


def load_db(slug: str) -> dict[str, Any]:
    p = db_path(slug)
    if not p.exists():
        seed = seed_path(slug)
        if seed.exists():
            _DATA_ROOT.mkdir(parents=True, exist_ok=True)
            p.write_text(seed.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_db(slug: str, data: dict[str, Any]) -> None:
    with _lock:
        p = db_path(slug)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8",
        )
