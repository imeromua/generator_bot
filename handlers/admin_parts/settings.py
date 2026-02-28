"""Admin settings panel — dynamic configuration management.

Allows admins to change fuel consumption rates and fuel price through
Telegram bot dialogs with validation and confirmation.
"""

import logging
from datetime import datetime

from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

import config
import database.db_api as db
from handlers.admin_parts.utils import actor_name

router = Router()
logger = logging.getLogger(__name__)


class SettingsStates(StatesGroup):
    waiting_fuel_rate = State()
    confirm_fuel_rate = State()
    waiting_fuel_price = State()
    confirm_fuel_price = State()


# ---------------------------------------------------------------------------
# Keyboards
# ---------------------------------------------------------------------------


def _settings_menu_kb() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="🔋 Основний ✏️",
                    callback_data="cfg_edit_rate:main",
                ),
                types.InlineKeyboardButton(
                    text="⚡ Аварійний ✏️",
                    callback_data="cfg_edit_rate:emergency",
                ),
            ],
            [
                types.InlineKeyboardButton(
                    text="💰 Вартість палива ✏️",
                    callback_data="cfg_edit_price",
                ),
            ],
            [
                types.InlineKeyboardButton(
                    text="📜 Історія змін",
                    callback_data="cfg_history",
                ),
            ],
            [
                types.InlineKeyboardButton(text="🔙 Назад", callback_data="admin_home"),
            ],
        ]
    )


def _confirm_kb(confirm_data: str) -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(text="✅ Підтвердити", callback_data=confirm_data),
                types.InlineKeyboardButton(text="❌ Скасувати", callback_data="cfg_cancel"),
            ],
        ]
    )


def _back_to_settings_kb() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="◀️ До налаштувань", callback_data="cfg_settings")],
        ]
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _gen_label(generator_id: str) -> str:
    return "🔋 Основний" if generator_id == "main" else "⚡ Аварійний"


def _settings_text() -> str:
    main_rate = db.get_fuel_consumption_rate_db("main")
    emerg_rate = db.get_fuel_consumption_rate_db("emergency")
    fuel_price = db.get_fuel_price_db()
    return (
        "⚙️ <b>Налаштування системи</b>\n"
        "──────────────────\n\n"
        "🔋 <b>Генератори</b>\n"
        f"├─ Основний: <b>{main_rate:.1f} л/год</b>\n"
        f"└─ Аварійний: <b>{emerg_rate:.1f} л/год</b>\n\n"
        f"💰 <b>Вартість палива:</b> {fuel_price:.0f} грн/л\n"
    )


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "cfg_settings")
async def settings_menu(cb: types.CallbackQuery, state: FSMContext):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    await state.clear()
    txt = _settings_text()
    if cb.message.text:
        await cb.message.edit_text(txt, reply_markup=_settings_menu_kb())
    else:
        await cb.message.delete()
        await cb.message.answer(txt, reply_markup=_settings_menu_kb())
    await cb.answer()


# --- FUEL RATE ---


@router.callback_query(F.data.startswith("cfg_edit_rate:"))
async def cfg_edit_rate_start(cb: types.CallbackQuery, state: FSMContext):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    generator_id = cb.data.split(":", 1)[1]
    if generator_id not in ("main", "emergency"):
        return await cb.answer("❌ Невірний генератор", show_alert=True)

    current = db.get_fuel_consumption_rate_db(generator_id)
    await state.set_state(SettingsStates.waiting_fuel_rate)
    await state.update_data(generator_id=generator_id, current_rate=current)

    from database.api.config import FUEL_CONSUMPTION_MIN, FUEL_CONSUMPTION_MAX

    txt = (
        f"🔧 <b>Зміна витрати палива</b>\n"
        f"Генератор: {_gen_label(generator_id)}\n\n"
        f"Поточне значення: <b>{current:.1f} л/год</b>\n\n"
        f"Введіть нове значення ({FUEL_CONSUMPTION_MIN} — {FUEL_CONSUMPTION_MAX} л/год):"
    )
    kb = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="❌ Скасувати", callback_data="cfg_cancel")],
        ]
    )
    await cb.message.edit_text(txt, reply_markup=kb)
    await cb.answer()


@router.message(SettingsStates.waiting_fuel_rate)
async def cfg_edit_rate_input(message: types.Message, state: FSMContext):
    if message.from_user.id not in config.ADMIN_IDS:
        return

    from database.api.config import FUEL_CONSUMPTION_MIN, FUEL_CONSUMPTION_MAX

    data = await state.get_data()
    generator_id = data.get("generator_id", "main")
    current = data.get("current_rate", 0.0)

    text = (message.text or "").strip()
    try:
        new_value = float(text.replace(",", "."))
    except ValueError:
        await message.answer(
            f"❌ Невірне значення. Введіть число від {FUEL_CONSUMPTION_MIN} до {FUEL_CONSUMPTION_MAX}:"
        )
        return

    if not (FUEL_CONSUMPTION_MIN <= new_value <= FUEL_CONSUMPTION_MAX):
        await message.answer(
            f"❌ Значення поза допустимим діапазоном ({FUEL_CONSUMPTION_MIN}–{FUEL_CONSUMPTION_MAX} л/год).\n"
            f"Введіть нове значення:"
        )
        return

    await state.set_state(SettingsStates.confirm_fuel_rate)
    await state.update_data(new_rate=new_value)

    txt = (
        f"✅ <b>Підтвердження</b>\n\n"
        f"Генератор: {_gen_label(generator_id)}\n"
        f"Витрата палива:\n"
        f"  Було: <b>{current:.1f} л/год</b>\n"
        f"  Буде: <b>{new_value:.1f} л/год</b>\n\n"
        f"Зміна вплине на:\n"
        f"• Розрахунки витрати палива\n"
        f"• Прогнозування\n"
        f"• Звіти (з моменту зміни)"
    )
    await message.answer(txt, reply_markup=_confirm_kb("cfg_confirm_rate"))


@router.callback_query(F.data == "cfg_confirm_rate")
async def cfg_confirm_rate(cb: types.CallbackQuery, state: FSMContext):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    data = await state.get_data()
    generator_id = data.get("generator_id", "main")
    old_value = data.get("current_rate", 0.0)
    new_value = data.get("new_rate", 0.0)

    actor = actor_name(cb.from_user.id, first_name=cb.from_user.first_name)
    ok = db.set_generator_param(
        generator_id,
        "fuel_consumption_rate",
        new_value,
        cb.from_user.id,
        actor,
    )
    if not ok:
        await state.clear()
        await cb.message.edit_text("❌ Помилка збереження. Спробуйте ще раз.", reply_markup=_back_to_settings_kb())
        return await cb.answer()

    db.log_admin_action(
        cb.from_user.id,
        actor,
        "config_generator_set",
        f"Змінено fuel_consumption_rate для {generator_id}: {old_value:.1f} → {new_value:.1f} л/год",
        target_entity=f"generator:{generator_id}",
        old_value=old_value,
        new_value=new_value,
    )
    await state.clear()

    now_str = datetime.now(config.KYIV).strftime("%d.%m.%Y %H:%M")
    txt = (
        f"✅ <b>Налаштування збережено!</b>\n\n"
        f"Витрата палива для {_gen_label(generator_id)}\n"
        f"змінено: <b>{old_value:.1f} → {new_value:.1f} л/год</b>\n\n"
        f"Час: {now_str}\n"
        f"Адмін: {actor}"
    )
    await cb.message.edit_text(txt, reply_markup=_back_to_settings_kb())
    await cb.answer("✅ Збережено")


# --- FUEL PRICE ---


@router.callback_query(F.data == "cfg_edit_price")
async def cfg_edit_price_start(cb: types.CallbackQuery, state: FSMContext):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    from database.api.config import FUEL_PRICE_MIN, FUEL_PRICE_MAX

    current = db.get_fuel_price_db()
    await state.set_state(SettingsStates.waiting_fuel_price)
    await state.update_data(current_price=current)

    txt = (
        f"💰 <b>Зміна вартості палива</b>\n\n"
        f"Поточна ціна: <b>{current:.0f} грн/л</b>\n\n"
        f"Введіть нову вартість палива ({FUEL_PRICE_MIN:.0f} — {FUEL_PRICE_MAX:.0f} грн/л):"
    )
    kb = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="❌ Скасувати", callback_data="cfg_cancel")],
        ]
    )
    await cb.message.edit_text(txt, reply_markup=kb)
    await cb.answer()


@router.message(SettingsStates.waiting_fuel_price)
async def cfg_edit_price_input(message: types.Message, state: FSMContext):
    if message.from_user.id not in config.ADMIN_IDS:
        return

    from database.api.config import FUEL_PRICE_MIN, FUEL_PRICE_MAX

    data = await state.get_data()
    current = data.get("current_price", 0.0)

    text = (message.text or "").strip()
    try:
        new_value = float(text.replace(",", "."))
    except ValueError:
        await message.answer(f"❌ Невірне значення. Введіть число від {FUEL_PRICE_MIN:.0f} до {FUEL_PRICE_MAX:.0f}:")
        return

    if not (FUEL_PRICE_MIN <= new_value <= FUEL_PRICE_MAX):
        await message.answer(
            f"❌ Значення поза допустимим діапазоном ({FUEL_PRICE_MIN:.0f}–{FUEL_PRICE_MAX:.0f} грн/л).\n"
            f"Введіть нову вартість:"
        )
        return

    await state.set_state(SettingsStates.confirm_fuel_price)
    await state.update_data(new_price=new_value)

    txt = (
        f"✅ <b>Підтвердження</b>\n\n"
        f"💰 Вартість палива:\n"
        f"  Було: <b>{current:.0f} грн/л</b>\n"
        f"  Буде: <b>{new_value:.0f} грн/л</b>"
    )
    await message.answer(txt, reply_markup=_confirm_kb("cfg_confirm_price"))


@router.callback_query(F.data == "cfg_confirm_price")
async def cfg_confirm_price(cb: types.CallbackQuery, state: FSMContext):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    data = await state.get_data()
    old_value = data.get("current_price", 0.0)
    new_value = data.get("new_price", 0.0)

    actor = actor_name(cb.from_user.id, first_name=cb.from_user.first_name)
    ok = db.set_global_param("fuel_price", new_value, cb.from_user.id, actor)
    if not ok:
        await state.clear()
        await cb.message.edit_text("❌ Помилка збереження. Спробуйте ще раз.", reply_markup=_back_to_settings_kb())
        return await cb.answer()

    db.log_admin_action(
        cb.from_user.id,
        actor,
        "config_global_set",
        f"Змінено fuel_price: {old_value:.0f} → {new_value:.0f} грн/л",
        target_entity="global:fuel_price",
        old_value=old_value,
        new_value=new_value,
    )
    await state.clear()

    now_str = datetime.now(config.KYIV).strftime("%d.%m.%Y %H:%M")
    txt = (
        f"✅ <b>Налаштування збережено!</b>\n\n"
        f"💰 Вартість палива змінено: "
        f"<b>{old_value:.0f} → {new_value:.0f} грн/л</b>\n\n"
        f"Час: {now_str}\n"
        f"Адмін: {actor}"
    )
    await cb.message.edit_text(txt, reply_markup=_back_to_settings_kb())
    await cb.answer("✅ Збережено")


# --- HISTORY ---


@router.callback_query(F.data == "cfg_history")
async def cfg_history(cb: types.CallbackQuery, state: FSMContext):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    await state.clear()
    history = db.get_config_history(limit=10)

    if not history:
        txt = "📊 <b>Історія змін налаштувань</b>\n\nЗмін ще не було."
    else:
        lines = ["📊 <b>Історія змін налаштувань</b>\n"]
        for h in history:
            dt_str = h["changed_at"][:16] if h["changed_at"] else "—"
            actor = h["changed_by_name"] or "—"
            param = h["param_name"]
            old_v = h["old_value"]
            new_v = h["new_value"]
            entity = h["entity_id"] or ""

            if h["config_type"] == "generator":
                gen_label = "🔋 Осн." if entity == "main" else "⚡ Авар."
                label = f"Витрата ({gen_label})"
                unit = "л/год"
                old_str = f"{old_v:.1f}" if old_v is not None else "—"
                new_str = f"{new_v:.1f}"
            else:
                label = "💰 Паливо"
                unit = "грн/л"
                old_str = f"{old_v:.0f}" if old_v is not None else "—"
                new_str = f"{new_v:.0f}"

            lines.append(f"<code>{dt_str}</code> | {actor}\n" f"  {label}: {old_str} → {new_str} {unit}\n")
        txt = "\n".join(lines)

    kb = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="◀️ До налаштувань", callback_data="cfg_settings")],
        ]
    )
    await cb.message.edit_text(txt, reply_markup=kb)
    await cb.answer()


# --- CANCEL ---


@router.callback_query(F.data == "cfg_cancel")
async def cfg_cancel(cb: types.CallbackQuery, state: FSMContext):
    await state.clear()
    txt = _settings_text()
    await cb.message.edit_text(txt, reply_markup=_settings_menu_kb())
    await cb.answer("Скасовано")
