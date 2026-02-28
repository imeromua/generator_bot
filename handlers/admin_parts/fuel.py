import html
import logging
from datetime import datetime

from aiogram import Router, F, types
from aiogram.exceptions import TelegramBadRequest

import config
import database.db_api as db
from handlers.admin_parts.utils import actor_name

router = Router()
logger = logging.getLogger(__name__)


# --- ПАЛИВО: замовлено ---
@router.callback_query(F.data == "fuel_ordered")
async def fuel_ordered(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    now = datetime.now(config.KYIV)
    today_str = now.strftime("%Y-%m-%d")

    db.set_state("fuel_ordered_date", today_str)
    db.set_state("fuel_alert_last_sent_ts", now.strftime("%Y-%m-%d %H:%M:%S"))

    actor = actor_name(cb.from_user.id, first_name=cb.from_user.first_name)
    try:
        db.add_log("fuel_ordered", actor, ts=now.strftime("%Y-%m-%d %H:%M:%S"))
    except Exception:
        pass

    # Оновлюємо повідомлення (якщо можемо)
    try:
        orig = getattr(cb.message, "html_text", None) or getattr(cb.message, "text", "") or ""
        note = "\n\n✅ <b>Паливо замовлено.</b> Нагадування вимкнено до заправки (поки паливо знову не стане ≥ порогу)."
        new_text = (orig + note).strip() if orig else note.strip()

        # прибираємо кнопку, залишаємо лише "На головну" для зручності
        kb = types.InlineKeyboardMarkup(
            inline_keyboard=[[types.InlineKeyboardButton(text="🏠 Дашборд", callback_data="home")]]
        )

        await cb.message.edit_text(new_text, reply_markup=kb)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.warning(f"fuel_ordered edit failed: {e}")
    except Exception as e:
        logger.warning(f"fuel_ordered edit failed: {e}")

    await cb.answer("✅ Прийнято", show_alert=True)


# --- ПАЛИВО: створити замовлення (з fuel_order_check) ---
@router.callback_query(F.data.startswith("fuel_order:create:"))
async def fuel_order_create(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    try:
        liters = float(cb.data.split(":")[-1])
    except (ValueError, IndexError):
        return await cb.answer("❌ Невірні дані", show_alert=True)

    from database.api.fuel_orders import create_order

    now = datetime.now(config.KYIV)

    try:
        order_id = create_order(
            created_at=now.strftime("%Y-%m-%d %H:%M:%S"),
            amount_liters=liters,
            requested_by=cb.from_user.id,
        )
    except Exception as e:
        logger.warning(f"fuel_order_create db failed: {e}")
        return await cb.answer("❌ Помилка створення замовлення", show_alert=True)

    orig = getattr(cb.message, "html_text", None) or getattr(cb.message, "text", "") or ""
    note = f"\n\n✅ <b>Замовлення #{order_id} створено</b> ({liters:.0f} л)"
    updated_text = (orig + note).strip()

    kb = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="📄 Переглянути замовлення", url="https://generator-016.pp.ua/?tab=fuel-orders"
                )
            ]
        ]
    )

    try:
        await cb.message.edit_text(updated_text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.warning(f"fuel_order_create edit failed: {e}")
    except Exception as e:
        logger.warning(f"fuel_order_create edit failed: {e}")

    await cb.answer("✅ Замовлення створено", show_alert=True)


# --- ПАЛИВО: відкласти замовлення (з fuel_order_check) ---
@router.callback_query(F.data == "fuel_order:skip")
async def fuel_order_skip(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    orig = getattr(cb.message, "html_text", None) or getattr(cb.message, "text", "") or ""
    note = f"\n\n❌ <i>Відкладено</i> ({html.escape(cb.from_user.first_name or '')})"
    updated_text = (orig + note).strip()

    try:
        await cb.message.edit_text(updated_text, reply_markup=None, parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.warning(f"fuel_order_skip edit failed: {e}")
    except Exception as e:
        logger.warning(f"fuel_order_skip edit failed: {e}")

    await cb.answer("❌ Відкладено")
