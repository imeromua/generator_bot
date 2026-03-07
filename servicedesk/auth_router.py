"""FastAPI router for ServiceDesk authentication.

Prefix: ``/api/sd/auth``

Endpoints
---------
POST /login          — login with web_login + password
POST /logout         — invalidate the current access token
POST /refresh        — issue a new access token using a refresh token
GET  /me             — return the current user's profile
POST /change-password — change the authenticated user's password
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import config
from database.models import get_connection
from database.api.auth import (
    get_user_by_web_login,
    verify_user_password,
    create_web_session,
    get_session_by_token,
    get_session_by_refresh_token,
    refresh_web_session,
    invalidate_session,
    set_user_password,
)
from servicedesk.auth_middleware import get_current_sd_user, oauth2_scheme

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sd/auth", tags=["sd-auth"])

_ACCESS_TOKEN_TTL: int = getattr(config, "SD_ACCESS_TOKEN_TTL", 3600)


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    login: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _user_dict(user: dict) -> dict[str, Any]:
    """Return a safe public representation of a user record."""
    return {
        "user_id": user.get("user_id"),
        "login": user.get("web_login") or user.get("username") or "",
        "role": user.get("role", "user"),
        "full_name": user.get("full_name", ""),
        "email": user.get("email") or "",
    }


# ---------------------------------------------------------------------------
# POST /login
# ---------------------------------------------------------------------------


@router.post("/login")
async def sd_login(body: LoginRequest, request: Request) -> JSONResponse:
    """Authenticate with *login* + *password* and return JWT tokens.

    Returns 401 if credentials are invalid or the account is inactive.
    """
    try:
        with get_connection() as conn:
            user = get_user_by_web_login(conn, body.login)
            if user is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Невірний логін або пароль",
                )
            if not user.get("is_active"):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Обліковий запис заблоковано",
                )
            if not verify_user_password(conn, user["user_id"], body.password):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Невірний логін або пароль",
                )

            ip = request.client.host if request.client else ""
            user_agent = request.headers.get("user-agent", "")
            session = create_web_session(conn, user["user_id"], ip, user_agent)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"sd_login error: {exc}")
        raise HTTPException(status_code=500, detail="Внутрішня помилка сервера")

    if not session:
        raise HTTPException(status_code=500, detail="Не вдалося створити сесію")

    access_ttl = _ACCESS_TOKEN_TTL
    return JSONResponse(
        {
            "access_token": session["token"],
            "refresh_token": session["refresh_token"],
            "expires_in": access_ttl,
            "user": _user_dict(user),
        }
    )


# ---------------------------------------------------------------------------
# POST /logout
# ---------------------------------------------------------------------------


@router.post("/logout")
async def sd_logout(token: str | None = Depends(oauth2_scheme)) -> JSONResponse:
    """Invalidate the current Bearer token."""
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Токен відсутній",
        )
    try:
        with get_connection() as conn:
            invalidate_session(conn, token)
    except Exception as exc:
        logger.error(f"sd_logout error: {exc}")
        raise HTTPException(status_code=500, detail="Внутрішня помилка сервера")

    return JSONResponse({"ok": True})


# ---------------------------------------------------------------------------
# POST /refresh
# ---------------------------------------------------------------------------


@router.post("/refresh")
async def sd_refresh(body: RefreshRequest) -> JSONResponse:
    """Issue a new access token using a valid *refresh_token*."""
    try:
        with get_connection() as conn:
            result = refresh_web_session(conn, body.refresh_token)
    except Exception as exc:
        logger.error(f"sd_refresh error: {exc}")
        raise HTTPException(status_code=500, detail="Внутрішня помилка сервера")

    if not result:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh-токен недійсний або закінчився",
        )

    return JSONResponse(
        {
            "access_token": result["token"],
            "expires_in": _ACCESS_TOKEN_TTL,
        }
    )


# ---------------------------------------------------------------------------
# GET /me
# ---------------------------------------------------------------------------


@router.get("/me")
async def sd_me(user: dict = Depends(get_current_sd_user)) -> JSONResponse:
    """Return the profile of the currently authenticated user."""
    return JSONResponse(_user_dict(user))


# ---------------------------------------------------------------------------
# POST /change-password
# ---------------------------------------------------------------------------


@router.post("/change-password")
async def sd_change_password(
    body: ChangePasswordRequest,
    user: dict = Depends(get_current_sd_user),
) -> JSONResponse:
    """Change the password for the authenticated user.

    Returns 400 if *old_password* does not match the stored hash.
    """
    user_id = user["user_id"]
    try:
        with get_connection() as conn:
            if not verify_user_password(conn, user_id, body.old_password):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Поточний пароль невірний",
                )
            if not set_user_password(conn, user_id, body.new_password):
                raise HTTPException(
                    status_code=500,
                    detail="Не вдалося оновити пароль",
                )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"sd_change_password error for user {user_id}: {exc}")
        raise HTTPException(status_code=500, detail="Внутрішня помилка сервера")

    return JSONResponse({"ok": True})
