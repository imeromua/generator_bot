"""Common router aggregator.

This module composes common (user-neutral) handlers and re-exports show_dash.
"""

from aiogram import Router

from handlers.common_parts.dash import show_dash
from handlers.common_parts.help import router as help_router
from handlers.common_parts.registration import router as registration_router


router = Router()
router.include_router(registration_router)
router.include_router(help_router)

__all__ = ["router", "show_dash"]
