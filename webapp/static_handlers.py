"""Static file handlers for the Mini App frontend."""

from pathlib import Path
from aiohttp import web

_WEBAPP_DIR = Path(__file__).resolve().parent.parent


def register_static_handlers(app: web.Application) -> None:
    """Register static file routes for the Mini App frontend."""
    webapp_dir = _WEBAPP_DIR

    if not webapp_dir.is_dir():
        return

    app.router.add_static("/css/", webapp_dir / "css", name="css")
    app.router.add_static("/js/", webapp_dir / "js", name="js")

    async def index_handler(request: web.Request) -> web.FileResponse:
        return web.FileResponse(webapp_dir / "index.html")

    async def block_handler(request: web.Request) -> web.FileResponse:
        return web.FileResponse(webapp_dir / "block.html")

    async def sw_handler(request: web.Request) -> web.FileResponse:
        return web.FileResponse(
            webapp_dir / "service-worker.js",
            headers={"Content-Type": "application/javascript"},
        )

    app.router.add_get("/", index_handler)
    app.router.add_get("/block.html", block_handler)
    app.router.add_get("/service-worker.js", sw_handler)
