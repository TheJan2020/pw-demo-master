"""
Per-vertical demo session auth — intentionally minimal.

Each demo gets its own session cookie scoped to its URL path so logging
into Clinic doesn't authenticate you on Restaurant. The token is just a
random opaque string kept in an in-memory dict — tokens reset on
backend restart, which is fine for a demo product. No hashing, no
rotation, no expiry — see DEMOSITEMAP.md for the deliberate non-goals.
"""
from __future__ import annotations

import secrets
import time
from typing import Optional

from fastapi import HTTPException, Request, Response

# token -> {slug, username, created_at}
_tokens: dict[str, dict] = {}


def _cookie_name(slug: str) -> str:
    """Per-vertical cookie name so Clinic and Restaurant can be logged in
    simultaneously in the same browser without one clobbering the other."""
    return f"pw_demo_{slug}"


def issue_session(response: Response, slug: str, username: str) -> str:
    token = secrets.token_urlsafe(32)
    _tokens[token] = {
        "slug": slug,
        "username": username,
        "created_at": time.time(),
    }
    # Cookie path is `/` because the SPA lives at /demo/<slug>/* and the
    # API at /api/demo/<slug>/* — no common ancestor below `/`. We rely on
    # the per-slug cookie name to keep verticals isolated.
    response.set_cookie(
        key=_cookie_name(slug),
        value=token,
        path="/",
        httponly=True,
        samesite="lax",
    )
    return token


def get_session(request: Request, slug: str) -> Optional[dict]:
    token = request.cookies.get(_cookie_name(slug))
    if not token:
        return None
    sess = _tokens.get(token)
    if not sess or sess.get("slug") != slug:
        return None
    return sess


def require_session(request: Request, slug: str) -> dict:
    sess = get_session(request, slug)
    if not sess:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return sess


def clear_session(request: Request, response: Response, slug: str) -> None:
    token = request.cookies.get(_cookie_name(slug))
    if token:
        _tokens.pop(token, None)
    response.delete_cookie(_cookie_name(slug), path="/")
