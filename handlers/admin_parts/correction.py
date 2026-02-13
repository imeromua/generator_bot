"""Manual corrections handler.

Allows admins to manually adjust generator state values:
- Current fuel level
- Fuel consumption rate
- Total motor hours
- Last oil change hours
- Last spark change hours

Safety:
- Only when generator is OFF
- Transactional updates (FIX #12)
- Single-window UI (FIX #24)
- Logged to system journal
- Dynamic handler factory (FIX #13)
"""

import logging
from typing import Callable, Any

from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

import config
import database.db_api as db
from database.models import get_connection, begin_transaction
from database.api.state import _conn_get_state_value
from handlers.admin_parts.utils import actor_name
from keyboards.builders import correction_menu, back_to_corr

router = Router()
logger = logging.getLogger(__name__)


class CorrectionForm(StatesGroup):
    """FSM states for manual corrections."""
    fuel = State()
    total_hours = State()
    last_oil = State()
    last_spark = State()
    fuel_consumption = State()


def _build_correction_text() -> str:
    """Створює текст зі станом корекцій.

    Returns:
        Formatted text with current state values
    """
    st = db.get_state()
    try:
        fuel_consumption = float(st.get('fuel_consumption', config.FUEL_CONSUMPTION) or config.FUEL_CONSUMPTION)
    except Exception:
        fuel_consumption = config.FUEL_CONSUMPTION

    return (
        "🧩 <b>Корекція</b>\n\n"
        f"⛽️ Поточний залишок палива: <b>{float(st.get('current_fuel', 0.0) or 0.0):.1f} л</b>\n"
        f"⏱ Загальні мотогодини: <b>{float(st.get('total_hours', 0.0) or 0.0):.1f} год</b>\n"
        f"🛢 Годин від заміни мастила: <b>{float(st.get('last_oil_change', 0.0) or 0.0):.1f} год</b>\n"
        f"🕯 Годин від заміни свічок: <b>{float(st.get('last_spark_change', 0.0) or 0.0):.1f} год</b>\n"
        f"📊 Витрата палива: <b>{fuel_consumption:.2f} л/год</b>\n"
    )


@router.callback_query(F.data == "corr_menu")
async def corr_menu(cb: types.CallbackQuery, state: FSMContext) -> None:
    """Display correction menu.

    Args:
        cb: Callback query
        state: FSM context
    """
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    await state.clear()
    await cb.message.edit_text(_build_correction_text(), reply_markup=correction_menu())
    await cb.answer()


# FIX #13: Generic handler for all numeric corrections to reduce code duplication
# FIX #22: Use human-readable Ukrainian labels instead of technical field names
CORRECTION_CONFIGS: dict[str, dict[str, Any]] = {
    "fuel": {
        "state_key": "current_fuel",
        "state_obj": CorrectionForm.fuel,
        "prompt_emoji": "⛽️",
        "prompt_text": "Поточний залишок палива",
        "units": "л",
        "log_event": "corr_fuel_set",
        "log_emoji": "⛽️",
        "min_val": 0.0,
        "max_val": 100000.0,
        "db_setter": lambda v: db.set_state("current_fuel", str(v)),
    },
    "fuel_consumption": {
        "state_key": "fuel_consumption",
        "state_obj": CorrectionForm.fuel_consumption,
        "prompt_emoji": "📊",
        "prompt_text": "Витрата палива",
        "units": "л/год",
        "log_event": "corr_fuel_consumption_set",
        "log_emoji": "📊",
        "min_val": 0.01,
        "max_val": 100.0,
        "db_setter": lambda v: db.set_state("fuel_consumption", str(v)),
        "get_current": lambda st: float(st.get('fuel_consumption', config.FUEL_CONSUMPTION) or config.FUEL_CONSUMPTION),
        "help_text": "\n\n💡 <i>Значення за замовчуванням: {:.2f} л/год (з .env).\nКорекція перевизначає це значення для розрахунку споживання палива.</i>".format(config.FUEL_CONSUMPTION),
    },
    "total_hours": {
        "state_key": "total_hours",
        "state_obj": CorrectionForm.total_hours,
        "prompt_emoji": "⏱",
        "prompt_text": "Загальні мотогодини",
        "units": "год",
        "log_event": "corr_total_hours_set",
        "log_emoji": "⏱",
        "min_val": 0.0,
        "max_val": 100000.0,
        "db_setter": db.set_total_hours,
    },
    "last_oil": {
        "state_key": "last_oil_change",
        "state_obj": CorrectionForm.last_oil,
        "prompt_emoji": "🛢",
        "prompt_text": "Годин від заміни мастила",
        "units": "год",
        "log_event": "corr_last_oil_set",
        "log_emoji": "🛢",
        "min_val": 0.0,
        "max_val": 100000.0,
        "db_setter": lambda v: db.set_state("last_oil_change", str(v)),
    },
    "last_spark": {
        "state_key": "last_spark_change",
        "state_obj": CorrectionForm.last_spark,
        "prompt_emoji": "🕯",
        "prompt_text": "Годин від заміни свічок",
        "units": "год",
        "log_event": "corr_last_spark_set",
        "log_emoji": "🕯",
        "min_val": 0.0,
        "max_val": 100000.0,
        "db_setter": lambda v: db.set_state("last_spark_change", str(v)),
    },
}


def _create_correction_handler(corr_type: str, config_dict: dict[str, Any]) -> tuple[Callable, Callable]:
    """FIX #13: Factory function to create correction handlers dynamically.

    Args:
        corr_type: Correction type key
        config_dict: Configuration dictionary

    Returns:
        Tuple of (set_handler, save_handler)
    """

    async def set_handler(cb: types.CallbackQuery, state: FSMContext) -> None:
        """Start correction process.

        Args:
            cb: Callback query
            state: FSM context
        """
        if cb.from_user.id not in config.ADMIN_IDS:
            return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

        # FIX #12: Check status inside a read transaction (not perfect but better)
        # For true transactional check, we'd need to defer to save_handler
        st = db.get_state()
        if st.get("status") == "ON":
            return await cb.answer("⛔ Корекції заборонені під час активної зміни. Спочатку натисніть СТОП.", show_alert=True)

        get_current = config_dict.get("get_current", lambda st: float(st.get(config_dict["state_key"], 0.0) or 0.0))
        cur = get_current(st)

        # FIX #22: Add optional help text for specific fields (e.g., fuel_consumption)
        help_text = config_dict.get("help_text", "")

        await cb.message.edit_text(
            f"{config_dict['prompt_emoji']} {config_dict['prompt_text']}: <b>{cur:.1f} {config_dict['units']}</b>\nВведіть нове значення ({config_dict['units']}):{help_text}",
            reply_markup=back_to_corr(),
        )
        await state.set_state(config_dict["state_obj"])
        await cb.answer()

    async def save_handler(msg: types.Message, state: FSMContext) -> None:
        """Save corrected value.

        Args:
            msg: Message with new value
            state: FSM context
        """
        if msg.from_user.id not in config.ADMIN_IDS:
            await state.clear()
            # FIX #24: Delete user message to maintain single-window UI
            try:
                await msg.delete()
            except Exception:
                pass
            return

        # FIX #24: Get UI message ID for single-window editing
        ui_msg = db.get_ui_message(msg.from_user.id)
        if not ui_msg:
            # Fallback: if no UI message tracked, use old behavior
            await state.clear()
            await msg.answer("⛔ Помилка: втрачено зв'язок з UI. Поверніться в меню.")
            return

        ui_chat_id, ui_msg_id = ui_msg

        # FIX #12: Transactional status check at write time
        conn = get_connection()
        try:
            begin_transaction(conn)

            # Check status atomically within transaction
            current_status = _conn_get_state_value(conn, "status", "OFF")
            if current_status == "ON":
                conn.rollback()
                await state.clear()

                # FIX #24: Edit UI message and delete user message
                try:
                    await msg.delete()
                except Exception:
                    pass

                try:
                    await msg.bot.edit_message_text(
                        chat_id=ui_chat_id,
                        message_id=ui_msg_id,
                        text="⛔ Корекції заборонені під час активної зміни.\n\n" + _build_correction_text(),
                        reply_markup=correction_menu(),
                    )
                except Exception:
                    pass
                return

            # Validate and parse input
            try:
                val_text = (msg.text or "").replace(",", ".").strip()
                val = float(val_text)

                if val < config_dict["min_val"]:
                    conn.rollback()

                    # FIX #24: Edit UI message and delete user message
                    try:
                        await msg.delete()
                    except Exception:
                        pass

                    try:
                        await msg.bot.edit_message_text(
                            chat_id=ui_chat_id,
                            message_id=ui_msg_id,
                            text=f"❌ Значення не може бути менше {config_dict['min_val']}.\n\n{config_dict['prompt_emoji']} {config_dict['prompt_text']}: введіть коректне значення.",
                            reply_markup=back_to_corr(),
                        )
                    except Exception:
                        pass
                    return

                if val > config_dict["max_val"]:
                    conn.rollback()

                    # FIX #24: Edit UI message and delete user message
                    try:
                        await msg.delete()
                    except Exception:
                        pass

                    try:
                        await msg.bot.edit_message_text(
                            chat_id=ui_chat_id,
                            message_id=ui_msg_id,
                            text=f"❌ Значення занадто велике (максимум {config_dict['max_val']}).\n\n{config_dict['prompt_emoji']} {config_dict['prompt_text']}: введіть коректне значення.",
                            reply_markup=back_to_corr(),
                        )
                    except Exception:
                        pass
                    return

                # Apply the change
                config_dict["db_setter"](val)

                # Log the correction
                actor = actor_name(msg.from_user.id, first_name=msg.from_user.first_name)
                db.add_log(config_dict["log_event"], actor, val=str(val), conn=conn)
                logger.info(f"{config_dict['log_emoji']} {actor} встановив {config_dict['state_key']}: {val}")

                conn.commit()

                await state.clear()

                # FIX #24: Edit UI message and delete user message
                try:
                    await msg.delete()
                except Exception:
                    pass

                txt = "✅ Збережено.\n\n" + _build_correction_text()
                try:
                    await msg.bot.edit_message_text(
                        chat_id=ui_chat_id,
                        message_id=ui_msg_id,
                        text=txt,
                        reply_markup=correction_menu(),
                    )
                except Exception:
                    pass

            except ValueError:
                conn.rollback()

                # FIX #24: Edit UI message and delete user message
                try:
                    await msg.delete()
                except Exception:
                    pass

                try:
                    await msg.bot.edit_message_text(
                        chat_id=ui_chat_id,
                        message_id=ui_msg_id,
                        text=f"❌ Введіть число (наприклад 171.0).\n\n{config_dict['prompt_emoji']} {config_dict['prompt_text']}: введіть коректне значення.",
                        reply_markup=back_to_corr(),
                    )
                except Exception:
                    pass

        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.error(f"Помилка корекції {corr_type}: {e}", exc_info=True)
            await state.clear()

            # FIX #24: Edit UI message and delete user message
            try:
                await msg.delete()
            except Exception:
                pass

            try:
                await msg.bot.edit_message_text(
                    chat_id=ui_chat_id,
                    message_id=ui_msg_id,
                    text=f"❌ Помилка: {e}\n\n" + _build_correction_text(),
                    reply_markup=correction_menu(),
                )
            except Exception:
                pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

    return set_handler, save_handler


# Register all handlers dynamically
for corr_type, cfg in CORRECTION_CONFIGS.items():
    set_h, save_h = _create_correction_handler(corr_type, cfg)
    router.callback_query.register(set_h, F.data == f"corr_{corr_type}_set")
    router.message.register(save_h, cfg["state_obj"])
