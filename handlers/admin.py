from aiogram import Router

from handlers.admin_parts.drivers import router as drivers_router
from handlers.admin_parts.fuel import router as fuel_router
from handlers.admin_parts.home import router as home_router
from handlers.admin_parts.maintenance import router as maintenance_router
from handlers.admin_parts.personnel import router as personnel_router
from handlers.admin_parts.reports import router as reports_router
from handlers.admin_parts.schedule import router as schedule_router
from handlers.admin_parts.sheet_mode import router as sheet_mode_router
from handlers.admin_parts.users import router as users_router

router = Router()
router.include_router(home_router)
router.include_router(sheet_mode_router)
router.include_router(personnel_router)
router.include_router(schedule_router)
router.include_router(maintenance_router)
router.include_router(reports_router)
router.include_router(drivers_router)
router.include_router(fuel_router)
router.include_router(users_router)
