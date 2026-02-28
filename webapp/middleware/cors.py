"""CORS middleware for webapp."""

from aiohttp import web


@web.middleware
async def cors_middleware(request: web.Request, handler):
    """Додає CORS-заголовки до всіх відповідей."""
    if request.method == "OPTIONS":
        resp = web.Response(status=204)
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Telegram-Init-Data"
        return resp

    try:
        resp = await handler(request)
    except web.HTTPException as exc:
        resp = exc

    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Telegram-Init-Data"
    return resp
