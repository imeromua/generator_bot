import asyncio
from datetime import datetime, timedelta

from aiogram import types
from aiogram.exceptions import TelegramBadRequest

import config
import database.db_api as db
from keyboards.builders import main_dashboard
from utils.time import format_hours_hhmm


def _fmt_state_ts(ts_raw: str | None) -> str:
    s = (ts_raw or "").strip()
    if not s:
        return ""
    try:
        dt = datetime.fromtimestamp(int(float(s)), tz=config.KYIV)
        return dt.strftime("%d.%m %H:%M")
    except Exception:
        return ""


def _calc_run_hours(st: dict, now: datetime) -> float:
    """Best-effort runtime hours from state start_date/start_time.

    Returns duration in hours clamped to [0, 24].
    """
    try:
        start_date_str = (st.get("start_date", "") or "").strip()
        start_time_str = (st.get("start_time", "") or "").strip()
        if not start_time_str:
            return 0.0

        if start_date_str:
            start_dt = datetime.strptime(f"{start_date_str} {start_time_str}", "%Y-%m-%d %H:%M")
        else:
            # fallback: assume today's date, but adjust if time is "in the future" (cross-midnight)
            start_dt = datetime.strptime(f"{now.date()} {start_time_str}", "%Y-%m-%d %H:%M")
            if now.time() < datetime.strptime(start_time_str, "%H:%M").time():
                start_dt = start_dt - timedelta(days=1)

        start_dt = start_dt.replace(tzinfo=config.KYIV)
        dur = (now - start_dt).total_seconds() / 3600.0
        if dur < 0 or dur > 24:
            return 0.0
        return float(dur)
    except Exception:
        return 0.0


def _build_dash_text(user_id: int, user_name: str, banner: str | None = None) -> tuple[str, types.InlineKeyboardMarkup]:
    st = db.get_state()
    role = 'admin' if user_id in config.ADMIN_IDS else 'manager'

    completed = db.get_today_completed_shifts()

    status_icon = "🟢 ПРАЦЮЄ" if st['status'] == 'ON' else "💤 ВИМКНЕНО"

    to_service = config.MAINTENANCE_LIMIT - (st['total_hours'] - st['last_oil'])
    to_service_hhmm = format_hours_hhmm(to_service)

    # --- Паливо: відображення ---
    # DB зберігає "канонічне" current_fuel (події/корекції), а під час роботи показуємо оцінку "на льоту"
    # без мутації БД: current_fuel_est = current_fuel - elapsed_hours * FUEL_RATE.
    try:
        current_fuel_raw = float(st.get('current_fuel', 0.0) or 0.0)
    except Exception:
        current_fuel_raw = 0.0

    now = datetime.now(config.KYIV)
    current_fuel = current_fuel_raw
    fuel_mark = ""

    try:
        if st.get('status') == 'ON' and float(config.FUEL_CONSUMPTION or 0.0) > 0:
            dur_h = _calc_run_hours(st, now)
            if dur_h > 0:
                current_fuel = max(0.0, current_fuel_raw - (dur_h * float(config.FUEL_CONSUMPTION)))
                fuel_mark = " (оцінка)"
    except Exception:
        # якщо щось не так — показуємо канонічне
        current_fuel = current_fuel_raw
        fuel_mark = ""

    hours_left = current_fuel / config.FUEL_CONSUMPTION if config.FUEL_CONSUMPTION > 0 else 0
    hours_left_hhmm = format_hours_hhmm(hours_left)

    mode_mark = ""
    try:
        if bool(getattr(config, "IS_TEST_MODE", False)):
            mode_mark = "🧪 <b>ТЕСТОВИЙ РЕЖИМ</b>\n➖➖➖➖➖➖\n"
    except Exception:
        pass

    # REMOVED: OFFLINE mode message - not relevant for manual sync workflow (SHEETS_RUNTIME_ENABLED=0)
    # Users now manually import/export data via admin commands

    txt = (
        f"{mode_mark}"
        f"🔋 <b>Генератор:</b> {status_icon}\n"
        f"⛽ Залишок палива{fuel_mark}: <b>{current_fuel:.1f} л</b>\n"
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


async def show_dash(msg: types.Message, user_id: int, user_name: str, banner: str | None = None):
    # Раніше тут була runtime-синхронізація з Sheets; зараз модуль services.google_sync — no-op.
    try:
        from services.google_sync import sync_canonical_state_once
        await sync_canonical_state_once()
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
