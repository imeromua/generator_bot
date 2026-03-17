"""Telegram WebApp initData validation helpers."""

import hashlib
import hmac
import json
import logging
from urllib.parse import parse_qs, unquote

from fastapi import Request
import config

logger = logging.getLogger(__name__)


def validate_init_data(init_data: str, bot_token: str) -> dict | None:
    """Перевіряє підпис Telegram WebApp initData.

    Повертає розпарсені дані користувача або ``None`` якщо підпис невалідний.

    Алгоритм: https://core.telegram.org/bots/webapps#validating-data
    """
    if not init_data:
        return None

    parsed = parse_qs(init_data, keep_blank_values=True)
    received_hash = parsed.pop("hash", [None])[0]
    if not received_hash:
        return None

    items = []
    for key in sorted(parsed):
        val = parsed[key][0]
        items.append(f"{key}={val}")
    data_check_string = "\n".join(items)

    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed, received_hash):
        return None

    user_raw = parsed.get("user", [None])[0]
    if user_raw:
        try:
            return json.loads(unquote(user_raw))
        except (json.JSONDecodeError, TypeError):
            pass

    return {}


def _extract_sd_user(token: str) -> dict | None:
    """Validate a ServiceDesk Bearer JWT token and return a compatible user dict.

    Returns a user dict with an ``id`` key (mapped from ``user_id``) so that
    the existing ``is_admin`` and ``get_admin_info`` helpers work unchanged.
    The ``first_name`` key is set to ``full_name`` (or ``username`` as a last
    resort) so that fallback actor-name lookups that reference
    ``user.get("first_name", "Адмін")`` receive a meaningful label when the DB
    lookup inside those helpers unexpectedly returns nothing.
    Returns ``None`` if the token is invalid, the session is not found, or the
    user account is inactive.
    """
    try:
        from database.models import get_connection
        from database.api.auth import get_session_by_token

        with get_connection() as conn:
            session = get_session_by_token(conn, token)
            if not session:
                return None

            row = conn.execute(
                "SELECT user_id, username, full_name, role, is_active "
                "FROM users WHERE user_id = ?",
                (session["user_id"],),
            ).fetchone()

        if not row:
            return None
        user_id, username, full_name, role, is_active = row
        if not is_active:
            return None

        # Map user_id → id so downstream helpers (is_admin, get_admin_info) work
        return {
            "id": user_id,
            "user_id": user_id,
            "username": username,
            "full_name": full_name,
            "first_name": full_name or username or "",
            "role": role,
            "is_active": is_active,
        }
    except Exception as e:
        logger.warning("SD JWT auth failed: %s", e)
        return None


def extract_user(request: Request) -> dict | None:
    """Витягує та валідує користувача з заголовка або query-параметра init_data.

    Supports two authentication methods (checked in order):
    1. SD JWT Bearer token via ``Authorization: Bearer <token>`` header.
    2. Telegram WebApp initData via ``X-Telegram-Init-Data`` header or
       ``init_data`` query parameter.
    """
    # Method 1: SD JWT Bearer token
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        user = _extract_sd_user(token)
        if user is not None:
            return user

    # Method 2: Telegram initData (existing logic)
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    if not init_data:
        init_data = request.query_params.get("init_data", "")
    if not init_data:
        return None
    bot_token = config.BOT_TOKEN or ""
    return validate_init_data(init_data, bot_token)
