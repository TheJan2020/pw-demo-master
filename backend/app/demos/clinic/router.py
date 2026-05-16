"""Clinic demo backend — login, current-user, logout. Mock data
endpoints come later; for now the SPA's hardcoded mocks fill the UI."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from . import config
from ..auth import (
    clear_session,
    issue_session,
    require_session,
)

logger = logging.getLogger("demo_clinic")
router = APIRouter()

_SLUG = config.SLUG


class LoginIn(BaseModel):
    username: str
    password: str


@router.post("/login")
async def login(body: LoginIn, response: Response) -> dict:
    if body.username == config.DEMO_USERNAME and body.password == config.DEMO_PASSWORD:
        issue_session(response, _SLUG, body.username)
        return {"ok": True, "user": {"username": body.username,
                                     "display_name": config.DISPLAY_NAME}}
    raise HTTPException(401, "Invalid credentials")


@router.get("/me")
async def me(request: Request) -> dict:
    sess = require_session(request, _SLUG)
    return {"username": sess["username"], "display_name": config.DISPLAY_NAME}


@router.post("/logout")
async def logout(request: Request, response: Response) -> dict:
    clear_session(request, response, _SLUG)
    return {"ok": True}
