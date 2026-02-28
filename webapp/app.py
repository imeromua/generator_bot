"""Application factory for the Telegram Mini App web server.

This module provides ``create_app`` which builds and returns the
fully-configured aiohttp Application with all routes and middleware.
"""

# Re-export create_app so both entry points work:
#   from webapp.app import create_app
#   from webapp_server import create_app
from webapp_server import create_app  # noqa: F401

__all__ = ["create_app"]
