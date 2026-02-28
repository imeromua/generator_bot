"""FastAPI entry point with lifespan-based lifecycle management.

Start with::

    uvicorn app.main:app --host 0.0.0.0 --port 8080

The existing ``webapp_server.create_app()`` is reused so there is
no duplication of route definitions.
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI

import config

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """FastAPI native lifespan — replaces on_startup / on_shutdown handlers.

    Startup:
        * Initialise the database (creates tables if they don't exist).
        * Initialise the DI container and store it on ``app.state``.

    Shutdown:
        * Close the PostgreSQL connection pool (no-op for SQLite).
    """
    import database.models as db_models
    from database.models import close_postgres_pool
    from app.container import Container

    logger.info("🚀 [lifespan] Starting up …")

    # --- DB init ---
    try:
        db_models.init_db()
        logger.info("✅ [lifespan] Database initialised (%s)", db_models.db_target_info())
    except Exception:
        logger.exception("❌ [lifespan] Database init failed")
        raise

    # --- DI container ---
    app.state.container = Container()
    logger.info("✅ [lifespan] DI container ready")

    yield  # application runs here

    # --- Graceful shutdown ---
    logger.info("🛑 [lifespan] Shutting down …")
    try:
        close_postgres_pool()
        logger.info("✅ [lifespan] DB pool closed")
    except Exception:
        logger.warning("⚠️  [lifespan] Error closing DB pool (ignored)")


def create_app() -> FastAPI:
    """Build and return the production FastAPI application.

    Delegates route registration to ``webapp_server.create_app`` and
    attaches the lifespan handler so lifecycle is managed in one place.
    """
    from webapp_server import create_app as _create_webapp_app

    # Build the app from the existing factory (all routes + middleware)
    app = _create_webapp_app()

    # Replace the default (empty) lifespan with our production one
    app.router.lifespan_context = lifespan

    return app


# Module-level ``app`` so uvicorn can reference it directly:
#   uvicorn app.main:app
app = create_app()
