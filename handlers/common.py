"""Common router aggregator.

This module composes common (user-neutral) handlers and re-exports show_dash.
"""

from aiogram import Router

from handlers.common_parts.dash import show_dash, router as dash_router
from handlers.common_parts.help import router as help_router
from handlers.common_parts.registration import router as registration_router
from handlers.common_parts.messages import router as messages_router  # FIX #25

router = Router()
router.include_router(registration_router)
router.include_router(help_router)
router.include_router(dash_router)  # FIX #25: main_menu callback
router.include_router(messages_router)  # FIX #25: message history

__all__ = ["router", "show_dash"]
