"""Telegram WebApp initData validation helpers."""

import hashlib
import hmac
import json
from urllib.parse import parse_qs, unquote

from aiohttp import web
import config


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


def extract_user(request: web.Request) -> dict | None:
    """Витягує та валідує користувача з заголовка або query-параметра init_data."""
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    if not init_data:
        init_data = request.query.get("init_data", "")
    if not init_data:
        return None
    bot_token = config.BOT_TOKEN or ""
    return validate_init_data(init_data, bot_token)
