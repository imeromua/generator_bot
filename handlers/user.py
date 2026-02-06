from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest
from datetime import datetime, timedelta, date

import asyncio
import os
import re

import gspread
from google.oauth2.service_account import Credentials

import config
import database.db_api as db
from keyboards.builders import main_dashboard, drivers_list
from handlers.common import show_dash


router = Router()


class RefillForm(StatesGroup):
    driver = State()
    liters = State()
    receipt = State()


def _ensure_user(user_id: int, first_name: str | None = None):
    """Повертає (user_id, full_name) з БД. Якщо адмін без запису — авто-реєструє."""
    user = db.get_user(user_id)
    if user:
        return user

    if user_id in config.ADMIN_IDS:
        name = f"Admin {first_name or ''}".strip()
        if not name:
            name = f"Admin {user_id}"
        db.register_user(user_id, name)
        return db.get_user(user_id)

    return None


def _get_operator_personnel_name(user_id: int) -> str | None:
    """Повертає ПІБ з 'ПЕРСОНАЛ' для запису у таблицю. Якщо не призначено — None."""
    try:
        return db.get_personnel_for_user(user_id)
    except Exception:
        return None


def format_hours_hhmm(hours_float: float) -> str:
    """Конвертує години (float) у формат ГГ:ХХ."""
    try:
        h = float(hours_float)
    except Exception:
        h = 0.0

    sign = "-" if h < 0 else ""
    h = abs(h)

    total_minutes = int(round(h * 60.0))
    hh = total_minutes // 60
    mm = total_minutes % 60

    return f"{sign}{hh:02d}:{mm:02d}"


def _schedule_to_ranges(schedule: dict) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    start = None
    for h in range(24):
        off = int(schedule.get(h, 0) or 0) == 1
        if off and start is None:
            start = h
        if (not off) and start is not None:
            ranges.append((start, h))
            start = None

    if start is not None:
        ranges.append((start, 24))

    return ranges


def _fmt_range(start_h: int, end_h: int) -> str:
    s = f"{start_h:02d}:00"
    e = "24:00" if end_h == 24 else f"{end_h:02d}:00"
    return f"{s} - {e}"


_SHIFT_COLS = {
    "m": (2, 3),
    "d": (4, 5),
    "e": (6, 7),
    "x": (8, 9),
}


def _shift_pretty(code_or_event: str) -> str:
    code = code_or_event
    if "_" in code_or_event:
        code = code_or_event.split("_", 1)[0]

    # Можемо в майбутньому повністю перейменувати кнопки,
    # але зараз міняємо тільки відображення (тексти).
    return {
        "m": "🟦 Зміна 1",
        "d": "🟩 Зміна 2",
        "e": "🟪 Зміна 3",
        "x": "⚡ Екстра",
    }.get(code, code_or_event)


def _shift_prev_required(code: str) -> str | None:
    return {
        "d": "m",
        "e": "d",
    }.get(code)


def _sheet_name_to_month(sheet_name: str):
    if not sheet_name:
        return None
    name = sheet_name.strip().upper()
    mapping = {
        "СІЧЕНЬ": 1, "ЛЮТИЙ": 2, "БЕРЕЗЕНЬ": 3, "КВІТЕНЬ": 4, "ТРАВЕНЬ": 5, "ЧЕРВЕНЬ": 6,
        "ЛИПЕНЬ": 7, "СЕРПЕНЬ": 8, "ВЕРЕСЕНЬ": 9, "ЖОВТЕНЬ": 10, "ЛИСТОПАД": 11, "ГРУДЕНЬ": 12,
        "ЯНВАРЬ": 1, "ФЕВРАЛЬ": 2, "МАРТ": 3, "АПРЕЛЬ": 4, "МАЙ": 5, "ИЮНЬ": 6,
        "ИЮЛЬ": 7, "АВГУСТ": 8, "СЕНТЯБРЬ": 9, "ОКТЯБРЬ": 10, "НОЯБРЬ": 11, "ДЕКАБРЬ": 12,
        "JANUARY": 1, "FEBRUARY": 2, "MARCH": 3, "APRIL": 4, "MAY": 5, "JUNE": 6,
        "JULY": 7, "AUGUST": 8, "SEPTEMBER": 9, "OCTOBER": 10, "NOVEMBER": 11, "DECEMBER": 12,
    }
    return mapping.get(name)


def _try_parse_date_from_cell(value: str, sheet_month, sheet_year: int):
    if value is None:
        return None

    s = str(value).strip()
    if not s:
        return None

    if s.upper() in ("ДАТА", "DATE"):
        return None

    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        pass

    try:
        if re.fullmatch(r"\d{1,2}\.\d{1,2}\.\d{4}", s):
            return datetime.strptime(s, "%d.%m.%Y").date()
        if re.fullmatch(r"\d{1,2}\.\d{1,2}\.\d{2}", s):
            return datetime.strptime(s, "%d.%m.%y").date()
    except Exception:
        pass

    try:
        if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", s):
            return datetime.strptime(s, "%d/%m/%Y").date()
    except Exception:
        pass

    try:
        if re.fullmatch(r"\d{1,2}\.\d{1,2}", s):
            dd, mm = s.split(".")
            return date(sheet_year, int(mm), int(dd))
    except Exception:
        pass

    try:
        s_num = s.replace(",", ".")
        if re.fullmatch(r"\d+(\.\d+)?", s_num):
            f = float(s_num)
            if f >= 30000:
                base = date(1899, 12, 30)
                return base + timedelta(days=int(f))
    except Exception:
        pass

    try:
        if re.fullmatch(r"\d{1,2}", s):
            day = int(s)
            if 1 <= day <= 31 and sheet_month:
                return date(sheet_year, sheet_month, day)
    except Exception:
        pass

    return None


def _find_row_by_date_in_column_a(ws, target_date: date, sheet_name: str):
    col_a = ws.col_values(1)
    sheet_month = _sheet_name_to_month(sheet_name)
    sheet_year = target_date.year

    for idx, cell_value in enumerate(col_a, start=1):
        d = _try_parse_date_from_cell(cell_value, sheet_month=sheet_month, sheet_year=sheet_year)
        if d == target_date:
            return idx

    return None


def _open_ws_sync():
    if not config.SHEET_ID:
        return None
    if not os.path.exists("service_account.json"):
        return None

    scopes = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    creds = Credentials.from_service_account_file("service_account.json", scopes=scopes)
    client = gspread.authorize(creds)
    ss = client.open_by_key(config.SHEET_ID)
    return ss.worksheet(config.SHEET_NAME)


def _get_sheet_shift_info_sync():
    """Повертає (sheet_ok, open_shift_code|None, completed_set, start_time_by_shift)."""
    ws = _open_ws_sync()
    if not ws:
        return False, None, set(), {}

    today = datetime.now(config.KYIV).date()
    row = _find_row_by_date_in_column_a(ws, today, config.SHEET_NAME)
    if not row:
        return False, None, set(), {}

    rng = ws.get(f"A{row}:I{row}")
    vals = (rng[0] if rng else [])

    def cell(col: int) -> str:
        idx = col - 1
        if idx < 0:
            return ""
        return (vals[idx] if idx < len(vals) else "").strip()

    completed = set()
    start_times = {}
    open_shift = None

    for code, (c_start, c_end) in _SHIFT_COLS.items():
        s = cell(c_start)
        e = cell(c_end)
        if e:
            completed.add(code)
        if s:
            start_times[code] = s
        if s and not e and open_shift is None:
            open_shift = code

    return True, open_shift, completed, start_times


def _sync_db_from_sheet_open_shift(open_shift_code: str, start_times: dict):
    """Якщо таблиця показує відкриту зміну — синхронізуємо мінімальний стан в БД для блокування."""
    try:
        db.set_state("status", "ON")
        db.set_state("active_shift", f"{open_shift_code}_start")
        st_time = start_times.get(open_shift_code, "")
        if st_time:
            db.set_state("last_start_time", st_time[:5])
            db.set_state("last_start_date", datetime.now(config.KYIV).strftime("%Y-%m-%d"))
    except Exception:
        pass


@router.callback_query(F.data == "schedule_today")
async def schedule_today(cb: types.CallbackQuery):
    now = datetime.now(config.KYIV)
    today_str = now.strftime("%Y-%m-%d")
    schedule = db.get_schedule(today_str)

    ranges = _schedule_to_ranges(schedule)
    total_off = sum((e - s) for s, e in ranges)

    now_status = "🔴 Зараз: <b>відключення</b>" if int(schedule.get(now.hour, 0) or 0) == 1 else "🟢 Зараз: <b>світло є</b>"

    banner = f"📅 <b>Графік відключень на сьогодні</b> ({now.strftime('%d.%m.%Y')})\n\n"

    if not ranges:
        banner += "✅ Відключень не заплановано.\n\n"
    else:
        for s, e in ranges:
            banner += f"🔴 {_fmt_range(s, e)}\n"
        banner += f"\n⏱ Сумарно без світла: <b>{total_off} год</b>\n\n"

    banner += now_status

    user = _ensure_user(cb.from_user.id, cb.from_user.first_name)
    if not user:
        return await cb.answer("⚠️ Спочатку натисніть /start", show_alert=True)

    await show_dash(cb.message, user[0], user[1], banner=banner)
    await cb.answer()


# --- СТАРТ ---
@router.callback_query(F.data.in_({"m_start", "d_start", "e_start", "x_start"}))
async def gen_start(cb: types.CallbackQuery):
    st = db.get_state()

    operator_personnel = _get_operator_personnel_name(cb.from_user.id)
    if not operator_personnel:
        return await cb.answer("⚠️ Нема прив'язки до персоналу. Адмінка → Персонал.", show_alert=True)

    sheet_ok, open_shift, completed_sheet, start_times = await asyncio.to_thread(_get_sheet_shift_info_sync)
    if sheet_ok and open_shift:
        _sync_db_from_sheet_open_shift(open_shift, start_times)
        return await cb.answer(
            f"⛔ ВЖЕ ПРАЦЮЄ! (Активна зміна: {_shift_pretty(open_shift)})",
            show_alert=True
        )

    shift_code = cb.data.split("_")[0]

    if sheet_ok and shift_code in completed_sheet:
        return await cb.answer("⛔ Ця зміна вже відпрацьована сьогодні!", show_alert=True)

    if st['status'] == 'ON':
        active = st.get('active_shift', 'none')
        return await cb.answer(
            f"⛔ ВЖЕ ПРАЦЮЄ! (Активна зміна: {_shift_pretty(active)})",
            show_alert=True
        )

    completed_db = db.get_today_completed_shifts()
    completed_total = set(completed_db)
    if sheet_ok:
        completed_total |= set(completed_sheet)

    # Черга змін: 1 -> 2 -> 3 (екстра без черги)
    prev_required = _shift_prev_required(shift_code)
    if prev_required and (prev_required not in completed_total):
        return await cb.answer(
            f"⛔ Спочатку закрийте {_shift_pretty(prev_required)}.",
            show_alert=True
        )

    if shift_code in completed_db:
        return await cb.answer("⛔ Ця зміна вже відпрацьована сьогодні!", show_alert=True)

    now = datetime.now(config.KYIV)

    if cb.data != "x_start":
        start_time_limit = datetime.strptime(config.WORK_START_TIME, "%H:%M").time()
        if now.time() < start_time_limit:
            return await cb.answer(f"😴 Ще рано! Робота з {config.WORK_START_TIME}", show_alert=True)

    user = _ensure_user(cb.from_user.id, cb.from_user.first_name)
    if not user:
        return await cb.answer("⚠️ Спочатку натисніть /start", show_alert=True)

    res = db.try_start_shift(cb.data, operator_personnel, now)
    if not res.get("ok"):
        if res.get("reason") == "already_on":
            active = res.get('active_shift', 'none')
            return await cb.answer(
                f"⛔ ВЖЕ ПРАЦЮЄ! (Активна зміна: {_shift_pretty(active)})",
                show_alert=True
            )
        return await cb.answer("❌ Помилка старту. Спробуйте ще раз.", show_alert=True)

    banner = f"✅ <b>{_shift_pretty(cb.data)}</b> відкрито о {now.strftime('%H:%M')}\n👤 {operator_personnel}"
    await show_dash(cb.message, user[0], user[1], banner=banner)
    await cb.answer()


# --- СТОП ---
@router.callback_query(F.data.in_({"m_end", "d_end", "e_end", "x_end"}))
async def gen_stop(cb: types.CallbackQuery):
    st = db.get_state()

    operator_personnel = _get_operator_personnel_name(cb.from_user.id)
    if not operator_personnel:
        return await cb.answer("⚠️ Нема прив'язки до персоналу. Адмінка → Персонал.", show_alert=True)

    expected_start = cb.data.replace("_end", "_start")
    expected_code = expected_start.split("_")[0]

    sheet_ok, open_shift, completed_sheet, start_times = await asyncio.to_thread(_get_sheet_shift_info_sync)

    # Якщо в таблиці вже закрито — кнопкою СТОП нічого не пишемо, тільки синхронізуємо стан
    if sheet_ok and expected_code in completed_sheet:
        db.set_state('status', 'OFF')
        db.set_state('active_shift', 'none')

        user = _ensure_user(cb.from_user.id, cb.from_user.first_name)
        if not user:
            return await cb.answer("⚠️ Спочатку натисніть /start", show_alert=True)

        banner = f"ℹ️ {_shift_pretty(expected_code)} вже закрито в таблиці. Стан оновлено."
        await show_dash(cb.message, user[0], user[1], banner=banner)
        await cb.answer()
        return

    # Якщо таблиця каже, що відкрита інша зміна
    if sheet_ok and open_shift and open_shift != expected_code:
        return await cb.answer(
            f"⛔ Помилка! Зараз активний {_shift_pretty(open_shift)}.\nНатисніть відповідну кнопку СТОП.",
            show_alert=True
        )

    # Якщо в таблиці НІЧОГО не відкрите, але бот думає, що ON — це саме кейс "закрили на ПК"
    if sheet_ok and (not open_shift) and st['status'] == 'ON':
        db.set_state('status', 'OFF')
        db.set_state('active_shift', 'none')

        user = _ensure_user(cb.from_user.id, cb.from_user.first_name)
        if not user:
            return await cb.answer("⚠️ Спочатку натисніть /start", show_alert=True)

        banner = "ℹ️ У таблиці немає відкритої зміни. Стан бота синхронізовано."
        await show_dash(cb.message, user[0], user[1], banner=banner)
        await cb.answer()
        return

    # Якщо таблиця недоступна/не знайшли рядок — працюємо по локальному стану
    if (not sheet_ok) and st['status'] == 'OFF':
        return await cb.answer("⛔ Вже вимкнено.", show_alert=True)

    # Якщо таблиця доступна і там теж OFF
    if sheet_ok and (not open_shift) and st['status'] == 'OFF':
        return await cb.answer("⛔ Вже вимкнено.", show_alert=True)

    now = datetime.now(config.KYIV)

    try:
        start_date_str = st.get('start_date', '')
        start_time_str = st['start_time']

        if start_date_str:
            start_dt = datetime.strptime(f"{start_date_str} {start_time_str}", "%Y-%m-%d %H:%M")
        else:
            start_dt = datetime.strptime(f"{now.date()} {start_time_str}", "%Y-%m-%d %H:%M")
            if now.time() < datetime.strptime(start_time_str, "%H:%M").time():
                start_dt = start_dt - timedelta(days=1)

        start_dt = config.KYIV.localize(start_dt.replace(tzinfo=None))
        dur = (now - start_dt).total_seconds() / 3600.0

        if dur < 0 or dur > 24:
            dur = 0.0

    except Exception:
        dur = 0.0

    user = _ensure_user(cb.from_user.id, cb.from_user.first_name)
    if not user:
        return await cb.answer("⚠️ Спочатку натисніть /start", show_alert=True)

    res = db.try_stop_shift(cb.data, operator_personnel, now)
    if not res.get("ok"):
        if res.get("reason") == "already_off":
            return await cb.answer("⛔ Вже вимкнено.", show_alert=True)
        if res.get("reason") == "wrong_shift":
            active = res.get("active_shift", "none")
            return await cb.answer(
                f"⛔ Помилка! Зараз активний {_shift_pretty(active)}.\nНатисніть відповідну кнопку СТОП.",
                show_alert=True
            )
        return await cb.answer("❌ Помилка закриття. Спробуйте ще раз.", show_alert=True)

    fuel_consumed = dur * config.FUEL_CONSUMPTION
    try:
        canonical_fuel = float(st.get('current_fuel', 0.0) or 0.0)
    except Exception:
        canonical_fuel = 0.0
    remaining_est = canonical_fuel - fuel_consumed

    db.set_state('status', 'OFF')
    db.set_state('active_shift', 'none')

    dur_hhmm = format_hours_hhmm(dur)

    banner = (
        f"🏁 <b>{_shift_pretty(expected_code)} закрито!</b>\n"
        f"⏱️ Працював: <b>{dur_hhmm}</b>\n"
        f"📉 Використано (розрах.): <b>{fuel_consumed:.1f} л</b>\n"
        f"⛽️ Залишок (за таблицею - розрах.): <b>{remaining_est:.1f} л</b>\n"
        f"👤 {operator_personnel}"
    )

    await show_dash(cb.message, user[0], user[1], banner=banner)
    await cb.answer()


# --- ЗАПРАВКА ---
@router.callback_query(F.data == "refill_init")
async def refill_start(cb: types.CallbackQuery, state: FSMContext):
    operator_personnel = _get_operator_personnel_name(cb.from_user.id)
    if not operator_personnel:
        return await cb.answer("⚠️ Нема прив'язки до персоналу. Адмінка → Персонал.", show_alert=True)

    drivers = db.get_drivers()
    if not drivers:
        return await cb.answer("⚠️ Спочатку додайте водіїв в адмін-панелі", show_alert=True)

    # запам'ятовуємо повідомлення "вікна"
    await state.update_data(ui_chat_id=cb.message.chat.id, ui_message_id=cb.message.message_id)

    await cb.message.edit_text("🚛 Хто привіз паливо?", reply_markup=drivers_list(drivers))
    await state.set_state(RefillForm.driver)
    await cb.answer()


@router.callback_query(RefillForm.driver, F.data.startswith("drv_"))
async def refill_driver(cb: types.CallbackQuery, state: FSMContext):
    driver_name = cb.data.split("_", 1)[1]
    await state.update_data(driver=driver_name)
    await cb.message.edit_text(
        f"Водій: <b>{driver_name}</b>\n🔢 Скільки літрів прийнято? (Напишіть цифру)",
        reply_markup=main_dashboard('admin' if cb.from_user.id in config.ADMIN_IDS else 'manager', db.get_state().get('active_shift', 'none'), db.get_today_completed_shifts())
    )
    await state.set_state(RefillForm.liters)
    await cb.answer()


@router.message(RefillForm.liters)
async def refill_ask_receipt(msg: types.Message, state: FSMContext):
    data = await state.get_data()
    chat_id = int(data.get("ui_chat_id", msg.chat.id))
    message_id = int(data.get("ui_message_id", 0))

    try:
        liters_text = (msg.text or "").replace(",", ".").strip()
        liters = float(liters_text)

        if liters <= 0 or liters > 500:
            raise ValueError

        await state.update_data(liters=liters)

        if message_id:
            try:
                await msg.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text="🧾 Введіть <b>номер чека</b>:",
                    reply_markup=main_dashboard('admin' if msg.from_user.id in config.ADMIN_IDS else 'manager', db.get_state().get('active_shift', 'none'), db.get_today_completed_shifts())
                )
            except TelegramBadRequest as e:
                if "message is not modified" not in str(e).lower():
                    raise

        await state.set_state(RefillForm.receipt)

    except Exception:
        if message_id:
            try:
                await msg.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text="❌ Введіть кількість літрів числом (1..500).",
                    reply_markup=main_dashboard('admin' if msg.from_user.id in config.ADMIN_IDS else 'manager', db.get_state().get('active_shift', 'none'), db.get_today_completed_shifts())
                )
            except Exception:
                pass


@router.message(RefillForm.receipt)
async def refill_save(msg: types.Message, state: FSMContext):
    receipt_num = (msg.text or "").strip()
    if not receipt_num or len(receipt_num) > 50:
        return

    data = await state.get_data()
    liters = data.get('liters')
    driver = data.get('driver')

    user = _ensure_user(msg.from_user.id, msg.from_user.first_name)
    if not user:
        await state.clear()
        return

    operator_personnel = _get_operator_personnel_name(msg.from_user.id)
    if not operator_personnel:
        await state.clear()
        return

    log_val = f"{liters}|{receipt_num}"
    db.add_log("refill", operator_personnel, log_val, driver)

    await state.clear()

    banner = (
        f"✅ <b>Паливо прийнято</b>\n"
        f"🛢 Літри: <b>{float(liters):.1f}</b>\n"
        f"🧾 Чек: <b>{receipt_num}</b>\n"
        f"🚛 Водій: <b>{driver}</b>\n"
        f"👤 Відповідальний: <b>{operator_personnel}</b>"
    )

    await show_dash(msg, user[0], user[1], banner=banner)


@router.callback_query(F.data == "home")
async def go_home(cb: types.CallbackQuery, state: FSMContext):
    await state.clear()

    user = _ensure_user(cb.from_user.id, cb.from_user.first_name)
    if not user:
        await cb.answer("⚠️ Спочатку натисніть /start", show_alert=True)
        return

    await show_dash(cb.message, user[0], user[1])
    await cb.answer()
