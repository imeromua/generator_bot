from datetime import datetime

from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

import config
import database.db_api as db
from handlers.common_parts.dash import show_dash

router = Router()


class RegForm(StatesGroup):
    name = State()


@router.message(Command("start"))
async def cmd_start(msg: types.Message, state: FSMContext):
    user_id = msg.from_user.id
    await state.clear()

    bot_status = (config.BOT_STATUS or "ON").strip().upper()

    if bot_status == "OFF":
        await msg.answer("🚫 Бот тимчасово недоступний.")
        return

    user = db.get_user(user_id)

    # Auto-registration when bot is ON or user is admin
    if not user:
        # Determine role: admins always get admin role regardless of BOT_STATUS
        is_admin_user = user_id in config.ADMIN_IDS
        if bot_status == "ON" or is_admin_user:
            db.create_user(
                user_id=user_id,
                username=msg.from_user.username,
                first_name=msg.from_user.first_name,
                last_name=msg.from_user.last_name,
                role="admin" if is_admin_user else "user",
                is_active=True,
                registered_at=datetime.now(),
            )
            user = db.get_user(user_id)
            if user and not is_admin_user:
                await msg.answer("✅ Вітаємо! Ви успішно зареєстровані.")

    if not user:
        await msg.answer(
            f"👋 Вітаю! Твій ID: <code>{user_id}</code>\n"
            f"Бот наразі не приймає нових користувачів.\n"
            f"Зверніться до адміністратора."
        )
        return

    # Check if user is blocked
    user_dict = _user_row_to_dict(user)
    if not user_dict.get("is_active", True):
        await msg.answer("🚫 Ваш акаунт заблоковано. Зверніться до адміністратора.")
        return

    # Maintenance mode — only admins and superadmins
    if bot_status == "MAINTENANCE":
        role = user_dict.get("role", "user")
        if role not in ("admin", "superadmin"):
            await msg.answer("🛠️ Бот на технічному обслуговуванні. Спробуйте пізніше.")
            return

    # Update last activity
    db.update_last_activity(user_id)

    full_name = user_dict.get("full_name") or user_dict.get("first_name") or str(user_id)
    await show_dash(msg, user_id, full_name)


@router.message(RegForm.name)
async def process_name(msg: types.Message, state: FSMContext):
    db.register_user(msg.from_user.id, msg.text)
    await state.clear()
    await msg.answer(f"✅ Приємно познайомитись, {msg.text}!")
    await show_dash(msg, msg.from_user.id, msg.text)


def _user_row_to_dict(row) -> dict:
    """Convert a user DB row to dict, handling both old and new schema."""
    if row is None:
        return {}
    if isinstance(row, dict):
        d = dict(row)
    else:
        # Build dict from row tuple; new schema has more columns than old
        keys = ["user_id", "full_name", "username", "first_name", "last_name",
                "role", "is_active", "registered_at", "last_activity",
                "blocked_at", "blocked_by", "block_reason", "deleted_at"]
        d = {}
        for i, k in enumerate(keys):
            if i < len(row):
                d[k] = row[i]
    d["is_active"] = bool(d.get("is_active", 1))
    return d
