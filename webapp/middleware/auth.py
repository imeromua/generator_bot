"""Telegram auth validation middleware."""

from aiohttp import web
from webapp.utils.validation import extract_user


@web.middleware
async def auth_middleware(request: web.Request, handler):
    """Attach validated user to request for downstream handlers."""
    request["user"] = extract_user(request)
    return await handler(request)
