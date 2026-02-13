"""Event log viewer.

Display system events with pagination.
"""

from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from datetime import datetime
from typing import Optional

import database.db_api as db
from handlers.user_parts.sheets_shift import shift_pretty
from handlers.user_parts.utils import ensure_user

router = Router()


def _fmt_log_line(
    event_type: str,
    ts: str,
    user_name: Optional[str],
    value: Optional[str],
    driver: Optional[str],
    receipt: Optional[str],
    generator_id: Optional[str],
) -> str:
    """Format log entry as human-readable line.

    Args:
        event_type: Event type code
        ts: Timestamp string 'YYYY-mm-dd HH:MM:SS'
        user_name: User who triggered event
        value: Event value (liters, hours, etc.)
        driver: Driver name for refill events
        receipt: Receipt number for refill events
        generator_id: Generator ID ('main' or 'emergency')

    Returns:
        Formatted string with icon and description
    """
    # ts: 'YYYY-mm-dd HH:MM:SS'
    try:
        dt = datetime.strptime((ts or "").strip(), "%Y-%m-%d %H:%M:%S")
        ts_pretty = dt.strftime("%d.%m %H:%M")
    except Exception:
        ts_pretty = (ts or "").strip()[:16]

    who = (user_name or "").strip()
    
    # Іконка генератора
    gen_icon = ""
    if generator_id == "emergency":
        gen_icon = "⚠️ "
    elif generator_id == "main":
        gen_icon = "🔋 "

    if event_type.endswith("_start"):
        return f"• {ts_pretty} — {gen_icon}▶️ Старт: <b>{shift_pretty(event_type)}</b> ({who})"
    if event_type.endswith("_end"):
        return f"• {ts_pretty} — {gen_icon}⏹ Стоп: <b>{shift_pretty(event_type)}</b> ({who})"

    if event_type == "refill":
        liters = (str(value or "").strip().replace(",", "."))
        extra = []
        if liters:
            extra.append(f"{liters} л")
        if receipt:
            extra.append(f"чек {receipt}")
        if driver:
            extra.append(f"водій {driver}")
        extra_s = ", ".join(extra) if extra else ""
        tail = f" — <b>{extra_s}</b>" if extra_s else ""
        who_tail = f" ({who})" if who else ""
        return f"• {ts_pretty} — ⛽ Прийом палива{tail}{who_tail}"

    if event_type == "auto_close":
        return f"• {ts_pretty} — 🤖 Авто-закриття зміни (System)"

    if event_type == "fuel_ordered":
        return f"• {ts_pretty} — ✅ Паливо замовлено ({who})"

    if event_type == "sheet_force_offline":
        return f"• {ts_pretty} — 🔌 Google Sheets: <b>OFFLINE (примусово)</b> ({who})"

    if event_type == "sheet_force_online":
        return f"• {ts_pretty} — 🌐 Google Sheets: <b>OFFLINE вимкнено</b> ({who})"

    if event_type == "corr_fuel_set":
        val = (value or "").strip()
        tail = f" — <b>{val} л</b>" if val else ""
        who_tail = f" ({who})" if who else ""
        return f"• {ts_pretty} — ⛽ <b>Корекція палива</b>{tail}{who_tail}"

    if event_type == "corr_total_hours_set":
        val = (value or "").strip()
        tail = f" — <b>{val} год</b>" if val else ""
        who_tail = f" ({who})" if who else ""
        return f"• {ts_pretty} — ⏱ <b>Корекція мотогодин</b>{tail}{who_tail}"

    if event_type == "corr_last_oil_set":
        val = (value or "").strip()
        tail = f" — <b>{val} год</b>" if val else ""
        who_tail = f" ({who})" if who else ""
        return f"• {ts_pretty} — 🛢 <b>Корекція: мастило</b>{tail}{who_tail}"

    if event_type == "corr_last_spark_set":
        val = (value or "").strip()
        tail = f" — <b>{val} год</b>" if val else ""
        who_tail = f" ({who})" if who else ""
        return f"• {ts_pretty} — 🕯 <b>Корекція: свічки</b>{tail}{who_tail}"
    
    if event_type == "sync":
        return f"• {ts_pretty} — 🔄 <b>Синхронізація з Google Sheets</b> ({who})"
    
    if event_type == "generator_switch":
        # value містить цільовий генератор
        target = (value or "").strip()
        if target == "main":
            return f"• {ts_pretty} — 🔄 <b>Перемкнуто на ОСНОВНИЙ</b> ({who})"
        elif target == "emergency":
            return f"• {ts_pretty} — ⚠️ <b>Перемкнуто на АВАРІЙНИЙ</b> ({who})"
        else:
            return f"• {ts_pretty} — 🔄 <b>Перемикання генератора</b> ({who})"

    val = (value or "").strip()
    tail = f" — {val}" if val else ""
    who_tail = f" ({who})" if who else ""
    return f"• {ts_pretty} — <b>{event_type}</b>{tail}{who_tail}"


@router.callback_query(F.data.startswith("events_last"))
async def events_last(cb: types.CallbackQuery, state: FSMContext) -> None:
    """Показує системний журнал з пагінацією по 15 записів.

    Формат callback_data:
    - "events_last"         → сторінка 1
    - "events_last:2"       → сторінка 2 і т.д.

    Args:
        cb: Callback query
        state: FSM context
    """
    await state.clear()

    user = ensure_user(cb.from_user.id, cb.from_user.first_name)
    if not user:
        return await cb.answer("⚠️ Спочатку натисніть /start", show_alert=True)

    # Парсинг сторінки
    data = cb.data or "events_last"
    parts = data.split(":")
    try:
        page = int(parts[1]) if len(parts) == 2 else 1
    except Exception:
        page = 1

    if page < 1:
        page = 1

    PAGE_SIZE = 15
    offset = (page - 1) * PAGE_SIZE

    # Беремо на 1 запис більше, щоб зрозуміти, чи є наступна сторінка
    rows = db.get_logs_page(PAGE_SIZE + 1, offset)

    has_next = len(rows) > PAGE_SIZE
    rows = rows[:PAGE_SIZE]

    if not rows:
        if page == 1:
            txt = "🕘 <b>Останні події</b>\n\nПоки немає записів."
        else:
            txt = (
                "🕘 <b>Останні події</b>\n\n"
                f"Для сторінки <b>{page}</b> подій більше немає."
            )
    else:
        lines = []
        for event_type, ts, u_name, value, driver_name, receipt_number, generator_id in rows:
            lines.append(_fmt_log_line(event_type, ts, u_name, value, driver_name, receipt_number, generator_id))

        start_idx = offset + 1
        end_idx = offset + len(rows)
        txt = (
            "🕘 <b>Останні події</b>\n"
            f"Показано записи <b>{start_idx}–{end_idx}</b>.\n\n" + "\n".join(lines)
        )

    # Побудова inline‑клавіатури з пагінацією
    kb_rows: list[list[InlineKeyboardButton]] = []
    nav_row: list[InlineKeyboardButton] = []

    if page > 1:
        nav_row.append(
            InlineKeyboardButton(
                text="◀️ Попередні",
                callback_data=f"events_last:{page - 1}",
            )
        )

    if has_next:
        nav_row.append(
            InlineKeyboardButton(
                text="▶️ Наступні",
                callback_data=f"events_last:{page + 1}",
            )
        )

    if nav_row:
        kb_rows.append(nav_row)

    # Кнопка повернення на дашборд
    kb_rows.append(
        [InlineKeyboardButton(text="🔙 На головну", callback_data="main_menu")]
    )

    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)

    try:
        await cb.message.edit_text(txt, reply_markup=kb)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            raise

    await cb.answer()
