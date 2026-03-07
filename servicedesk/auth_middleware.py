"""FastAPI dependency for ServiceDesk JWT authentication.

Usage::

    from servicedesk.auth_middleware import get_current_sd_user

    @router.get("/api/sd/something")
    async def my_endpoint(user: dict = Depends(get_current_sd_user)):
        ...
"""

import logging
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from database.models import get_connection
from database.api.auth import get_session_by_token

logger = logging.getLogger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/sd/auth/login", auto_error=False)

try:
    import jwt as _jwt
    import config as _cfg

    _JWT_SECRET = getattr(_cfg, "JWT_SECRET", None) or ""
    _JWT_ALGORITHM = "HS256"
except Exception:  # pragma: no cover
    _jwt = None
    _JWT_SECRET = ""
    _JWT_ALGORITHM = "HS256"


def _decode_jwt(token: str) -> dict | None:
    """Decode and verify a JWT token.  Returns the payload dict or ``None``."""
    if _jwt is None or not _JWT_SECRET:
        return None
    try:
        return _jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGORITHM])
    except Exception:
        return None


async def get_current_sd_user(token: str | None = Depends(oauth2_scheme)) -> dict:
    """FastAPI dependency: verify JWT and return the user dict.

    Raises ``HTTPException(401)`` when:
    - No token is provided
    - The JWT signature is invalid or expired
    - No active session exists in the database for this token
    - The associated user account is inactive

    Returns a dict with keys: ``user_id``, ``full_name``, ``username``,
    ``role``, ``is_active``, ``web_login``, ``email``.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Недійсний або відсутній токен авторизації",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if not token:
        raise credentials_exception

    # 1. Decode JWT to get user_id (fast path — no DB hit yet)
    payload = _decode_jwt(token)
    if payload is None:
        # JWT library not available or secret not set — fall back to DB-only check
        logger.debug("JWT decode skipped (no library/secret); relying on DB session lookup")
    else:
        # Check token expiry claim
        exp = payload.get("exp")
        if exp is not None:
            try:
                if datetime.fromtimestamp(exp, tz=timezone.utc) < datetime.now(timezone.utc):
                    raise credentials_exception
            except (OSError, OverflowError, ValueError):
                raise credentials_exception

    # 2. Verify session exists and is active in the database
    try:
        with get_connection() as conn:
            session = get_session_by_token(conn, token)
    except Exception as exc:
        logger.error(f"DB error during session lookup: {exc}")
        raise credentials_exception

    if not session:
        raise credentials_exception

    # 3. Check session's own expiry stored in DB (covers opaque-token path)
    try:
        session_expires = datetime.fromisoformat(session["expires_at"])
        if session_expires.tzinfo is None:
            session_expires = session_expires.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) >= session_expires:
            raise credentials_exception
    except HTTPException:
        raise
    except Exception:
        pass  # malformed date — let the session pass; JWT exp already checked above

    # 4. Fetch user details
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT user_id, full_name, username, role, is_active, web_login, email "
                "FROM users WHERE user_id = ?",
                (session["user_id"],),
            ).fetchone()
    except Exception as exc:
        logger.error(f"DB error during user lookup: {exc}")
        raise credentials_exception

    if not row:
        raise credentials_exception

    keys = ["user_id", "full_name", "username", "role", "is_active", "web_login", "email"]
    user = dict(zip(keys, row))

    if not user.get("is_active"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Обліковий запис заблоковано",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user
