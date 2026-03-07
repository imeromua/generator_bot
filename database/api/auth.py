"""Web authentication utilities.

Provides password hashing/verification, web session management and
password-reset token helpers for the independent web-auth system
(SD-1).  Works alongside the existing Telegram-based auth without
breaking it.
"""

import logging
import secrets
from datetime import datetime, timedelta, timezone

try:
    from passlib.context import CryptContext

    _pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
except Exception:  # pragma: no cover
    _pwd_context = None

try:
    import jwt as _jwt
except Exception:  # pragma: no cover
    _jwt = None

from database.models import get_connection

logger = logging.getLogger(__name__)

# Token lifetimes — overridden by config if available
try:
    import config as _config

    _ACCESS_TOKEN_TTL_SECONDS = int(getattr(_config, "SD_ACCESS_TOKEN_TTL", 3600) or 3600)
    _REFRESH_TOKEN_TTL_SECONDS = int(getattr(_config, "SD_REFRESH_TOKEN_TTL", 2592000) or 2592000)
    _ACCESS_TOKEN_MINUTES = _ACCESS_TOKEN_TTL_SECONDS // 60
    _REFRESH_TOKEN_DAYS = _REFRESH_TOKEN_TTL_SECONDS // 86400
except Exception:
    _ACCESS_TOKEN_TTL_SECONDS = 3600
    _REFRESH_TOKEN_TTL_SECONDS = 2592000
    _ACCESS_TOKEN_MINUTES = 60
    _REFRESH_TOKEN_DAYS = 30

# Password-reset token lifetime (fixed at 30 minutes)
_RESET_TOKEN_MINUTES = 30

# Secret key for JWT signing – override via environment / config
try:
    import config as _config

    _JWT_SECRET = getattr(_config, "JWT_SECRET", None) or ""
    if not _JWT_SECRET:
        _JWT_SECRET = secrets.token_hex(32)
        logger.warning(
            "JWT_SECRET / SD_SECRET_KEY is not configured — using a random secret. "
            "All existing sessions will be invalidated on restart. "
            "Set SD_SECRET_KEY in your config or environment to persist sessions."
        )
except Exception:
    _JWT_SECRET = secrets.token_hex(32)

_JWT_ALGORITHM = "HS256"


# ---------------------------------------------------------------------------
# Password helpers
# ---------------------------------------------------------------------------


def set_user_password(conn, user_id: int, password: str) -> bool:
    """Hash *password* with bcrypt and persist it for *user_id*.

    Returns ``True`` on success, ``False`` on failure.
    """
    if _pwd_context is None:
        logger.error("passlib is not installed; cannot hash password")
        return False
    try:
        hashed = _pwd_context.hash(password)
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE user_id = ?",
            (hashed, user_id),
        )
        return True
    except Exception as e:
        logger.error(f"set_user_password failed for user {user_id}: {e}")
        return False


def verify_user_password(conn, user_id: int, password: str) -> bool:
    """Return ``True`` if *password* matches the stored hash for *user_id*."""
    if _pwd_context is None:
        logger.error("passlib is not installed; cannot verify password")
        return False
    try:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        if not row or not row[0]:
            return False
        return _pwd_context.verify(password, row[0])
    except Exception as e:
        logger.error(f"verify_user_password failed for user {user_id}: {e}")
        return False


# ---------------------------------------------------------------------------
# User lookup
# ---------------------------------------------------------------------------


def get_user_by_web_login(conn, web_login: str) -> dict | None:
    """Return the user row as a dict for the given *web_login*, or ``None``."""
    try:
        row = conn.execute(
            "SELECT user_id, full_name, username, role, is_active, web_login, email "
            "FROM users WHERE web_login = ?",
            (web_login,),
        ).fetchone()
        if row is None:
            return None
        keys = ["user_id", "full_name", "username", "role", "is_active", "web_login", "email"]
        return dict(zip(keys, row))
    except Exception as e:
        logger.error(f"get_user_by_web_login failed for login '{web_login}': {e}")
        return None


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------


def _make_access_token(user_id: int, expires_at: str) -> str:
    """Create a signed JWT access token."""
    if _jwt is None:
        # Fallback: opaque token stored entirely in DB
        return secrets.token_urlsafe(48)
    payload = {
        "sub": str(user_id),
        "exp": datetime.fromisoformat(expires_at).replace(tzinfo=timezone.utc),
        "iat": datetime.now(timezone.utc),
    }
    return _jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGORITHM)


def create_web_session(conn, user_id: int, ip: str, user_agent: str) -> dict:
    """Create a new web session for *user_id*.

    The DB row's ``expires_at`` reflects the refresh-token lifetime (30 days)
    so the session stays queryable until the user must fully re-authenticate.
    The returned ``expires_at`` is the *access-token* expiration (60 minutes)
    so the client knows when to call the refresh endpoint.

    Returns a dict with keys ``token``, ``refresh_token``, ``expires_at``.
    """
    now = datetime.now(timezone.utc)
    expires_at = (now + timedelta(minutes=_ACCESS_TOKEN_MINUTES)).isoformat()
    refresh_expires_at = (now + timedelta(days=_REFRESH_TOKEN_DAYS)).isoformat()
    created_at = now.isoformat()

    token = _make_access_token(user_id, expires_at)
    refresh_token = secrets.token_urlsafe(48)

    try:
        conn.execute(
            """
            INSERT INTO web_sessions
                (user_id, token, refresh_token, created_at, expires_at, ip_address, user_agent, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (user_id, token, refresh_token, created_at, refresh_expires_at, ip, user_agent),
        )
        return {"token": token, "refresh_token": refresh_token, "expires_at": expires_at}
    except Exception as e:
        logger.error(f"create_web_session failed for user {user_id}: {e}")
        return {}


def get_session_by_token(conn, token: str) -> dict | None:
    """Return the active session row as a dict, or ``None`` if not found / inactive."""
    try:
        row = conn.execute(
            """
            SELECT id, user_id, token, refresh_token, created_at, expires_at,
                   ip_address, user_agent, is_active
            FROM web_sessions
            WHERE token = ? AND is_active = 1
            """,
            (token,),
        ).fetchone()
        if row is None:
            return None
        keys = ["id", "user_id", "token", "refresh_token", "created_at", "expires_at",
                "ip_address", "user_agent", "is_active"]
        return dict(zip(keys, row))
    except Exception as e:
        logger.error(f"get_session_by_token failed: {e}")
        return None


def get_session_by_refresh_token(conn, refresh_token: str) -> dict | None:
    """Return the active session row as a dict for *refresh_token*, or ``None``."""
    try:
        row = conn.execute(
            """
            SELECT id, user_id, token, refresh_token, created_at, expires_at,
                   ip_address, user_agent, is_active
            FROM web_sessions
            WHERE refresh_token = ? AND is_active = 1
            """,
            (refresh_token,),
        ).fetchone()
        if row is None:
            return None
        keys = ["id", "user_id", "token", "refresh_token", "created_at", "expires_at",
                "ip_address", "user_agent", "is_active"]
        return dict(zip(keys, row))
    except Exception as e:
        logger.error(f"get_session_by_refresh_token failed: {e}")
        return None


def refresh_web_session(conn, refresh_token: str) -> dict | None:
    """Issue a new access token for an existing session identified by *refresh_token*.

    The refresh token itself remains valid until the session ``expires_at``
    (which was set to the refresh-token lifetime when the session was created).
    Returns a dict with keys ``token`` and ``expires_at`` on success, or
    ``None`` on failure / invalid / expired refresh token.
    """
    session = get_session_by_refresh_token(conn, refresh_token)
    if not session:
        return None

    now = datetime.now(timezone.utc)
    # Check if the session's overall expiry (= refresh-token expiry) has passed
    try:
        session_expires = datetime.fromisoformat(session["expires_at"])
        if session_expires.tzinfo is None:
            session_expires = session_expires.replace(tzinfo=timezone.utc)
        if now >= session_expires:
            return None
    except Exception:
        return None

    new_expires_at = (now + timedelta(seconds=_ACCESS_TOKEN_TTL_SECONDS)).isoformat()
    new_token = _make_access_token(session["user_id"], new_expires_at)

    try:
        conn.execute(
            "UPDATE web_sessions SET token = ? WHERE id = ?",
            (new_token, session["id"]),
        )
        return {"token": new_token, "expires_at": new_expires_at}
    except Exception as e:
        logger.error(f"refresh_web_session failed: {e}")
        return None


def invalidate_session(conn, token: str) -> bool:
    """Mark a session as inactive (logout).

    Returns ``True`` if the session was found and deactivated.
    """
    try:
        conn.execute(
            "UPDATE web_sessions SET is_active = 0 WHERE token = ?",
            (token,),
        )
        return True
    except Exception as e:
        logger.error(f"invalidate_session failed: {e}")
        return False


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------


def create_password_reset_token(conn, user_id: int) -> str:
    """Generate a single-use password-reset token for *user_id*.

    Any previously unused tokens for this user are invalidated first.
    Returns the new reset token string.
    """
    now = datetime.now(timezone.utc)
    expires_at = (now + timedelta(minutes=_RESET_TOKEN_MINUTES)).isoformat()
    created_at = now.isoformat()
    reset_token = secrets.token_urlsafe(48)

    try:
        # Invalidate old tokens for this user
        conn.execute(
            "UPDATE web_password_reset SET used = 1 WHERE user_id = ? AND used = 0",
            (user_id,),
        )
        conn.execute(
            """
            INSERT INTO web_password_reset (user_id, reset_token, created_at, expires_at, used)
            VALUES (?, ?, ?, ?, 0)
            """,
            (user_id, reset_token, created_at, expires_at),
        )
        return reset_token
    except Exception as e:
        logger.error(f"create_password_reset_token failed for user {user_id}: {e}")
        return ""


def validate_reset_token(conn, token: str) -> int | None:
    """Validate a password-reset token.

    Returns the ``user_id`` if the token exists, is unused and has not expired.
    Returns ``None`` otherwise.  Marks the token as used upon successful validation.
    """
    try:
        now = datetime.now(timezone.utc).isoformat()
        row = conn.execute(
            """
            SELECT id, user_id, expires_at
            FROM web_password_reset
            WHERE reset_token = ? AND used = 0 AND expires_at > ?
            """,
            (token, now),
        ).fetchone()
        if row is None:
            return None
        record_id, user_id, _ = row
        conn.execute(
            "UPDATE web_password_reset SET used = 1 WHERE id = ?",
            (record_id,),
        )
        return user_id
    except Exception as e:
        logger.error(f"validate_reset_token failed: {e}")
        return None
