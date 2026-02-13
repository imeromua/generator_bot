"""User registration handler.

Handles /start command and user registration flow.
"""

from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

import config
import database.db_api as db
from handlers.common_parts.dash import show_dash


router = Router()


class RegForm(StatesGroup):
    """Registration form states."""
    name = State()


@router.message(Command("start"))
async def cmd_start(msg: types.Message, state: FSMContext) -> None:
    """Handle /start command.

    Auto-registers admins, asks for name if user not registered.

    Args:
        msg: Incoming message
        state: FSM context
    """
    user_id = msg.from_user.id
    await state.clear()

    user = db.get_user(user_id)

    # Авто-реєстрація адміна
    if user_id in config.ADMIN_IDS and not user:
        name = f"Admin {msg.from_user.first_name}"
        db.register_user(user_id, name)
        user = db.get_user(user_id)

    if not user:
        await msg.answer(
            f"👋 Вітаю! Твій ID: <code>{user_id}</code>\n"
            f"Я тебе ще не знаю.\n"
            f"Будь ласка, напиши своє <b>Прізвище та Ім'я</b>:"
        )
        await state.set_state(RegForm.name)
    else:
        await show_dash(msg, user_id, user[1])


@router.message(RegForm.name)
async def process_name(msg: types.Message, state: FSMContext) -> None:
    """Process user name and complete registration.

    Args:
        msg: Message with user's name
        state: FSM context
    """
    db.register_user(msg.from_user.id, msg.text)
    await state.clear()
    await msg.answer(f"✅ Приємно познайомитись, {msg.text}!")
    await show_dash(msg, msg.from_user.id, msg.text)
