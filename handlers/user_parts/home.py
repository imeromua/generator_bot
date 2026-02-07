from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext

from handlers.common import show_dash
from handlers.user_parts.utils import ensure_user


router = Router()


@router.callback_query(F.data == "home")
async def go_home(cb: types.CallbackQuery, state: FSMContext):
    await state.clear()

    user = ensure_user(cb.from_user.id, cb.from_user.first_name)
    if not user:
        await cb.answer("⚠️ Спочатку натисніть /start", show_alert=True)
        return

    await show_dash(cb.message, user[0], user[1])
    await cb.answer()
