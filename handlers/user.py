from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext

from handlers.common import show_dash
from handlers.user_parts.events import router as events_router
from handlers.user_parts.refill import router as refill_router
from handlers.user_parts.schedule import router as schedule_router
from handlers.user_parts.shifts import router as shifts_router
from handlers.user_parts.utils import ensure_user


router = Router()
router.include_router(refill_router)
router.include_router(events_router)
router.include_router(schedule_router)
router.include_router(shifts_router)


@router.callback_query(F.data == "home")
async def go_home(cb: types.CallbackQuery, state: FSMContext):
    await state.clear()

    user = ensure_user(cb.from_user.id, cb.from_user.first_name)
    if not user:
        await cb.answer("⚠️ Спочатку натисніть /start", show_alert=True)
        return

    await show_dash(cb.message, user[0], user[1])
    await cb.answer()
