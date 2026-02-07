from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest

import asyncio
from datetime import datetime

import database.db_api as db
import config
from keyboards.builders import main_dashboard
from utils.time import format_hours_hhmm

router = Router()


class RegForm(StatesGroup):
    name = State()


def _fmt_state_ts(ts_raw: str | None) -> str:
    s = (ts_raw or "").strip()
    if not s:
        return ""
    try:
        dt = datetime.fromtimestamp(int(float(s)), tz=config.KYIV)
        return dt.strftime("%d.%m %H:%M")
    except Exception:
        return ""


def _build_dash_text(user_id: int, user_name: str, banner: str | None = None) -> tuple[str, types.InlineKeyboardMarkup]:
    st = db.get_state()
    role = 'admin' if user_id in config.ADMIN_IDS else 'manager'

    completed = db.get_today_completed_shifts()

    status_icon = "🟢 ПРАЦЮЄ" if st['status'] == 'ON' else "💤 ВИМКНЕНО"

    to_service = config.MAINTENANCE_LIMIT - (st['total_hours'] - st['last_oil'])
    to_service_hhmm = format_hours_hhmm(to_service)

    current_fuel = st['current_fuel']
    hours_left = current_fuel / config.FUEL_CONSUMPTION if config.FUEL_CONSUMPTION > 0 else 0
    hours_left_hhmm = format_hours_hhmm(hours_left)

    mode_mark = ""
    try:
        if bool(getattr(config, "IS_TEST_MODE", False)):
            mode_mark = "🧪 <b>ТЕСТОВИЙ РЕЖИМ</b>\n➖➖➖➖➖➖\n"
    except Exception:
        pass

    offline_mark = ""
    try:
        if db.sheet_is_offline():
            try:
                forced_offline = bool(db.sheet_is_forced_offline())
            except Exception:
                forced_offline = False

            since_s = _fmt_state_ts(db.get_state_value("sheet_offline_since_ts", ""))
            last_ok_s = _fmt_state_ts(db.get_state_value("sheet_last_ok_ts", ""))

            if forced_offline:
                offline_mark = "🔌 <b>OFFLINE (примусово)</b> — синхронізацію з Google Sheets вимкнено адміном.\n"
                if last_ok_s:
                    offline_mark += f"Останній успішний доступ: <b>{last_ok_s}</b>\n"
                if since_s:
                    offline_mark += f"OFFLINE з: <b>{since_s}</b>\n"
                offline_mark += "Дані накопичуються локально; синхронізація відновиться після вимкнення OFFLINE в адмінці.\n"
                offline_mark += "➖➖➖➖➖➖\n"
            else:
                if since_s:
                    offline_mark = (
                        f"🔌 <b>OFFLINE (авто)</b> — немає доступу до Google Sheets з {since_s}.\n"
                        f"Дані накопичуються локально; синхронізація відбудеться після відновлення доступу.\n"
                        f"➖➖➖➖➖➖\n"
                    )
                else:
                    offline_mark = (
                        "🔌 <b>OFFLINE (авто)</b> — немає доступу до Google Sheets.\n"
                        "Дані накопичуються локально; синхронізація відбудеться після відновлення доступу.\n"
                        "➖➖➖➖➖➖\n"
                    )

    except Exception:
        pass

    txt = (
        f"{mode_mark}{offline_mark}"
        f"🔋 <b>Генератор:</b> {status_icon}\n"
        f"⛽ Залишок палива: <b>{current_fuel:.1f} л</b>\n"
        f"⏳ Вистачить на: <b>~{hours_left_hhmm}</b>\n\n"
        f"👤 <b>Ви:</b> {user_name}\n"
        f"🛢 До ТО: <b>{to_service_hhmm}</b>"
    )

    if st['status'] == 'ON':
        txt += f"\n⏱ Старт був о: {st['start_time']}"

    if banner:
        txt = f"{banner}\n\n" + txt

    markup = main_dashboard(role, st.get('active_shift', 'none'), completed)

    return txt, markup


def _nav_kb(user_id: int) -> types.InlineKeyboardMarkup:
    kb = [[types.InlineKeyboardButton(text="🏠 Дашборд", callback_data="home")]]
    if user_id in config.ADMIN_IDS:
        kb.insert(0, [types.InlineKeyboardButton(text="⚙️ Адмін панель", callback_data="admin_home")])
    return types.InlineKeyboardMarkup(inline_keyboard=kb)


@router.message(Command("start"))
async def cmd_start(msg: types.Message, state: FSMContext):
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


@router.message(Command("help"))
async def cmd_help(msg: types.Message):
    """Вбудована довідка."""
    txt = (
        "ℹ️ <b>Допомога</b>\n\n"
        "Цей бот веде облік роботи генератора: зміни (СТАРТ/СТОП), графік відключень і прийом палива.\n\n"
        "<b>Як працювати</b>\n"
        "1) Натисніть СТАРТ доступної зміни (порядок: Зміна 1 → Зміна 2 → Зміна 3; Екстра після них).\n"
        "2) Після вимкнення генератора натисніть СТОП — це закриває зміну в боті.\n"
        "3) Якщо привезли паливо — натисніть «📥 ПРИЙОМ ПАЛИВА» і внесіть літри/чек/водія.\n"
        "4) «📅 Графік відключень» показує план на сьогодні.\n\n"
        "<b>Корисно знати</b>\n"
        "- Адмінам приходять нагадування (паливо/СТОП).\n"
        "- Якщо бачите блокування «Нема прив'язки до персоналу» — попросіть адміна: Адмінка → Персонал → призначити ПІБ.\n\n"
        "Політика приватності: /privacy"
    )

    await msg.answer(txt, reply_markup=_nav_kb(msg.from_user.id))


@router.message(Command("privacy"))
async def cmd_privacy(msg: types.Message):
    """Коротка політика приватності."""
    txt = (
        "🔒 <b>Приватність</b>\n\n"
        "Бот зберігає мінімум даних для обліку роботи генератора:\n"
        "- ваш Telegram ID і ПІБ (яке ви вказали при реєстрації);\n"
        "- прив'язку до ПІБ із колонки «ПЕРСОНАЛ» (якщо адмін призначив);\n"
        "- журнали подій: старт/стоп змін, прийом палива (літри, номер чека, водій), ТО, технічні події.\n\n"
        "Ці дані використовуються тільки для внутрішнього обліку та синхронізації з таблицею (Google Sheets) у вашій організації.\n\n"
        "Щоб видалити ваш запис/виправити ПІБ — напишіть адмінам, вони можуть відредагувати або очистити дані в БД."
    )

    await msg.answer(txt, reply_markup=_nav_kb(msg.from_user.id))


@router.message(RegForm.name)
async def process_name(msg: types.Message, state: FSMContext):
    db.register_user(msg.from_user.id, msg.text)
    await state.clear()
    await msg.answer(f"✅ Приємно познайомитись, {msg.text}!")
    await show_dash(msg, msg.from_user.id, msg.text)


async def show_dash(msg: types.Message, user_id: int, user_name: str, banner: str | None = None):
    # Тягнемо еталонний залишок палива з таблиці, щоб дашборд показував актуальне
    try:
        from services.google_sync import sync_canonical_state_once
        await asyncio.to_thread(sync_canonical_state_once)
    except Exception:
        pass

    txt, markup = _build_dash_text(user_id, user_name, banner=banner)

    # 1) Якщо це bot message (callback/екран) — редагуємо його
    try:
        await msg.edit_text(txt, reply_markup=markup)
        try:
            db.set_ui_message(user_id, msg.chat.id, msg.message_id)
        except Exception:
            pass
        return
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            return
    except Exception:
        pass

    # 2) Якщо редагувати не можна (наприклад /start) — видаляємо попередній дашборд та надсилаємо новий
    try:
        prev = db.get_ui_message(user_id)
        if prev:
            prev_chat_id, prev_msg_id = prev
            try:
                await msg.bot.delete_message(chat_id=prev_chat_id, message_id=prev_msg_id)
            except Exception:
                pass
    except Exception:
        pass

    sent = await msg.answer(txt, reply_markup=markup)
    try:
        db.set_ui_message(user_id, sent.chat.id, sent.message_id)
    except Exception:
        pass
