"""User router aggregator.

This module only composes user-facing routers from handlers.user_parts.
"""

from aiogram import Router

from handlers.user_parts.events import router as events_router
from handlers.user_parts.home import router as home_router
from handlers.user_parts.refill import router as refill_router
from handlers.user_parts.schedule import router as schedule_router
from handlers.user_parts.shifts import router as shifts_router


router = Router()
router.include_router(home_router)
router.include_router(refill_router)
router.include_router(events_router)
router.include_router(schedule_router)
router.include_router(shifts_router)
