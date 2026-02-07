import asyncio
from datetime import datetime, timedelta

from aiogram import Router, F, types

import config
import database.db_api as db
from handlers.common import show_dash
from handlers.user_parts.sheets_shift import (
    get_sheet_shift_info_sync,
    shift_pretty,
    shift_prev_required,
    sync_db_from_sheet_open_shift,
)
from handlers.user_parts.utils import ensure_user, get_operator_personnel_name
from utils.time import format_hours_hhmm, now_kiev


router = Router()


def _within_work_window(now_t, start_t, end_t) -> bool:
    """True if now_t is inside [start_t, end_t) window.

    Works for windows that do NOT cross midnight (start<=end) and windows that DO cross midnight.
    """
    if start_t <= end_t:
        return start_t <= now_t < end_t
    # crosses midnight, e.g. 22:00-06:00
    return now_t >= start_t or now_t < end_t


# --- СТАРТ ---
@router.callback_query(F.data.in_({"m_start", "d_start", "e_start", "x_start"}))
async def gen_start(cb: types.CallbackQuery):
    st = db.get_state()

    operator_personnel = get_operator_personnel_name(cb.from_user.id)
    if not operator_personnel:
        return await cb.answer("⚠️ Нема прив'язки до персоналу. Адмінка → Персонал.", show_alert=True)

    offline = db.sheet_is_offline()
    sheet_ok, open_shift, completed_sheet, start_times = (False, None, set(), {})

    if not offline:
        try:
            sheet_ok, open_shift, completed_sheet, start_times = await asyncio.to_thread(get_sheet_shift_info_sync)
            if sheet_ok:
                db.sheet_mark_ok()
            else:
                db.sheet_mark_fail()
                db.sheet_check_offline()
        except Exception:
            db.sheet_mark_fail()
            db.sheet_check_offline()

    if sheet_ok and open_shift:
        sync_db_from_sheet_open_shift(open_shift, start_times)
        return await cb.answer(
            f"⛔ ВЖЕ ПРАЦЮЄ! (Активна зміна: {shift_pretty(open_shift)})",
            show_alert=True
        )

    shift_code = cb.data.split("_", 1)[0]

    if sheet_ok and shift_code in completed_sheet:
        return await cb.answer("⛔ Ця зміна вже відпрацьована сьогодні!", show_alert=True)

    if st['status'] == 'ON':
        active = st.get('active_shift', 'none')
        return await cb.answer(
            f"⛔ ВЖЕ ПРАЦЮЄ! (Активна зміна: {shift_pretty(active)})",
            show_alert=True
        )

    completed_db = db.get_today_completed_shifts()
    completed_total = set(completed_db)
    if sheet_ok:
        completed_total |= set(completed_sheet)

    # Черга змін: 1 -> 2 -> 3 (екстра без черги)
    prev_required = shift_prev_required(shift_code)
    if prev_required and (prev_required not in completed_total):
        return await cb.answer(
            f"⛔ Спочатку закрийте {shift_pretty(prev_required)}.",
            show_alert=True
        )

    if shift_code in completed_db:
        return await cb.answer("⛔ Ця зміна вже відпрацьована сьогодні!", show_alert=True)

    now = now_kiev()

    # 🔒 Забороняємо відкриття змін поза робочим часом (комендантська година)
    try:
        start_t = datetime.strptime(config.WORK_START_TIME, "%H:%M").time()
        end_t = datetime.strptime(config.WORK_END_TIME, "%H:%M").time()
        if not _within_work_window(now.time(), start_t, end_t):
            return await cb.answer(
                f"⛔ Заборонено відкривати зміни поза робочим часом ({config.WORK_START_TIME}-{config.WORK_END_TIME}).\n"
                f"Зараз: {now.strftime('%H:%M')}",
                show_alert=True,
            )
    except Exception:
        # якщо конфіг часу некоректний — не блокуємо, але це має бути видно в логах (в іншому місці)
        pass

    user = ensure_user(cb.from_user.id, cb.from_user.first_name)
    if not user:
        return await cb.answer("⚠️ Спочатку натисніть /start", show_alert=True)

    res = db.try_start_shift(cb.data, operator_personnel, now)
    if not res.get("ok"):
        if res.get("reason") == "already_on":
            active = res.get('active_shift', 'none')
            return await cb.answer(
                f"⛔ ВЖЕ ПРАЦЮЄ! (Активна зміна: {shift_pretty(active)})",
                show_alert=True
            )
        return await cb.answer("❌ Помилка старту. Спробуйте ще раз.", show_alert=True)

    banner = f"✅ <b>{shift_pretty(cb.data)}</b> відкрито о {now.strftime('%H:%M')}\n👤 {operator_personnel}"
    await show_dash(cb.message, user[0], user[1], banner=banner)
    await cb.answer()


# --- СТОП ---
@router.callback_query(F.data.in_({"m_end", "d_end", "e_end", "x_end"}))
async def gen_stop(cb: types.CallbackQuery):
    st = db.get_state()

    operator_personnel = get_operator_personnel_name(cb.from_user.id)
    if not operator_personnel:
        return await cb.answer("⚠️ Нема прив'язки до персоналу. Адмінка → Персонал.", show_alert=True)

    expected_start = cb.data.replace("_end", "_start")
    expected_code = expected_start.split("_", 1)[0]

    offline = db.sheet_is_offline()
    sheet_ok, open_shift, completed_sheet, start_times = (False, None, set(), {})

    if not offline:
        try:
            sheet_ok, open_shift, completed_sheet, start_times = await asyncio.to_thread(get_sheet_shift_info_sync)
            if sheet_ok:
                db.sheet_mark_ok()
            else:
                db.sheet_mark_fail()
                db.sheet_check_offline()
        except Exception:
            db.sheet_mark_fail()
            db.sheet_check_offline()

    # Якщо в таблиці вже закрито — кнопкою СТОП нічого не пишемо, тільки синхронізуємо стан
    if sheet_ok and expected_code in completed_sheet:
        db.set_state('status', 'OFF')
        db.set_state('active_shift', 'none')

        user = ensure_user(cb.from_user.id, cb.from_user.first_name)
        if not user:
            return await cb.answer("⚠️ Спочатку натисніть /start", show_alert=True)

        banner = f"ℹ️ {shift_pretty(expected_code)} вже закрито в таблиці. Стан оновлено."
        await show_dash(cb.message, user[0], user[1], banner=banner)
        await cb.answer()
        return

    # Якщо таблиця каже, що відкрита інша зміна
    if sheet_ok and open_shift and open_shift != expected_code:
        return await cb.answer(
            f"⛔ Помилка! Зараз активний {shift_pretty(open_shift)}.\nНатисніть відповідну кнопку СТОП.",
            show_alert=True
        )

    # Якщо в таблиці НІЧОГО не відкрите, але бот думає, що ON — це саме кейс "закрили на ПК"
    if sheet_ok and (not open_shift) and st['status'] == 'ON':
        db.set_state('status', 'OFF')
        db.set_state('active_shift', 'none')

        user = ensure_user(cb.from_user.id, cb.from_user.first_name)
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

    now = now_kiev()

    try:
        start_date_str = st.get('start_date', '')
        start_time_str = st.get('start_time', '')

        if start_time_str:
            if start_date_str:
                start_dt = datetime.strptime(f"{start_date_str} {start_time_str}", "%Y-%m-%d %H:%M")
            else:
                start_dt = datetime.strptime(f"{now.date()} {start_time_str}", "%Y-%m-%d %H:%M")
                if now.time() < datetime.strptime(start_time_str, "%H:%M").time():
                    start_dt = start_dt - timedelta(days=1)

            start_dt = config.KYIV.localize(start_dt.replace(tzinfo=None))
            dur = (now - start_dt).total_seconds() / 3600.0
        else:
            dur = 0.0

        if dur < 0 or dur > 24:
            dur = 0.0

    except Exception:
        dur = 0.0

    user = ensure_user(cb.from_user.id, cb.from_user.first_name)
    if not user:
        return await cb.answer("⚠️ Спочатку натисніть /start", show_alert=True)

    res = db.try_stop_shift(cb.data, operator_personnel, now)
    if not res.get("ok"):
        if res.get("reason") == "already_off":
            return await cb.answer("⛔ Вже вимкнено.", show_alert=True)
        if res.get("reason") == "wrong_shift":
            active = res.get("active_shift", "none")
            return await cb.answer(
                f"⛔ Помилка! Зараз активний {shift_pretty(active)}.\nНатисніть відповідну кнопку СТОП.",
                show_alert=True
            )
        return await cb.answer("❌ Помилка закриття. Спробуйте ще раз.", show_alert=True)

    # FIX #7: Витрати палива обчислюються з логів при експорті/імпорті
    # В handler НІКОЛИ не треба міняти current_fuel вручну!
    # Обчислюємо тільки для відображення
    try:
        fuel_consumption_rate = float(st.get('fuel_consumption', config.FUEL_CONSUMPTION) or config.FUEL_CONSUMPTION)
    except Exception:
        fuel_consumption_rate = config.FUEL_CONSUMPTION
    
    fuel_consumed = dur * fuel_consumption_rate

    # Оновлюємо мотогодини (це правильно, бо вони не обчислюються з логів)
    try:
        db.update_hours(float(dur or 0.0))
    except Exception:
        pass

    # Оновлюємо стан після закриття
    try:
        st = db.get_state()
    except Exception:
        st = {}

    try:
        canonical_fuel = float(st.get('current_fuel', 0.0) or 0.0)
    except Exception:
        canonical_fuel = 0.0

    # Відображаємо очікуваний залишок (тільки для UI)
    remaining_est = canonical_fuel - fuel_consumed

    dur_hhmm = format_hours_hhmm(dur)

    banner = (
        f"🏁 <b>{shift_pretty(expected_code)} закрито!</b>\n"
        f"⏱️ Працював: <b>{dur_hhmm}</b>\n"
        f"📉 Використано (розрах.): <b>{fuel_consumed:.1f} л</b>\n"
        f"⛽️ Залишок (за таблицею - розрах.): <b>{remaining_est:.1f} л</b>\n"
        f"👤 {operator_personnel}"
    )

    await show_dash(cb.message, user[0], user[1], banner=banner)
    await cb.answer()
