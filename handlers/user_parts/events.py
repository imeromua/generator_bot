from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest
from datetime import datetime

import database.db_api as db
from handlers.user_parts.sheets_shift import shift_pretty
from handlers.user_parts.utils import ensure_user

router = Router()


def _fmt_log_line(event_type: str, ts: str, user_name: str | None, value: str | None, driver: str | None) -> str:
    # ts: 'YYYY-mm-dd HH:MM:SS'
    try:
        dt = datetime.strptime((ts or "").strip(), "%Y-%m-%d %H:%M:%S")
        ts_pretty = dt.strftime("%d.%m %H:%M")
    except Exception:
        ts_pretty = (ts or "").strip()[:16]

    who = (user_name or "").strip()

    if event_type.endswith("_start"):
        return f"• {ts_pretty} — ▶️ Старт: <b>{shift_pretty(event_type)}</b> ({who})"
    if event_type.endswith("_end"):
        return f"• {ts_pretty} — ⏹ Стоп: <b>{shift_pretty(event_type)}</b> ({who})"

    if event_type == "refill":
        liters = ""
        receipt = ""
        try:
            parts = (value or "").split("|", 1)
            liters = parts[0].strip() if len(parts) > 0 else ""
            receipt = parts[1].strip() if len(parts) > 1 else ""
        except Exception:
            pass
        extra = []
        if liters:
            extra.append(f"{liters} л")
        if receipt:
            extra.append(f"чек {receipt}")
        if driver:
            extra.append(f"водій {driver}")
        extra_s = ", ".join(extra) if extra else (value or "").strip()
        return f"• {ts_pretty} — ⛽ Прийом палива: <b>{extra_s}</b> ({who})"

    if event_type == "auto_close":
        return f"• {ts_pretty} — 🤖 Авто-закриття зміни (System)"

    if event_type == "fuel_ordered":
        return f"• {ts_pretty} — ✅ Паливо замовлено ({who})"

    if event_type == "sheet_force_offline":
        return f"• {ts_pretty} — 🔌 Google Sheets: <b>OFFLINE (примусово)</b> ({who})"

    if event_type == "sheet_force_online":
        return f"• {ts_pretty} — 🌐 Google Sheets: <b>OFFLINE вимкнено</b> ({who})"

    val = (value or "").strip()
    tail = f" — {val}" if val else ""
    return f"• {ts_pretty} — <b>{event_type}</b>{tail} ({who})"


@router.callback_query(F.data == "events_last")
async def events_last(cb: types.CallbackQuery, state: FSMContext):
    await state.clear()

    user = ensure_user(cb.from_user.id, cb.from_user.first_name)
    if not user:
        return await cb.answer("⚠️ Спочатку натисніть /start", show_alert=True)

    rows = db.get_last_logs(15)

    if not rows:
        txt = "🕘 <b>Останні події</b>\n\nПоки немає записів."
    else:
        lines = []
        for event_type, ts, u_name, value, driver_name in rows:
            lines.append(_fmt_log_line(event_type, ts, u_name, value, driver_name))

        txt = "🕘 <b>Останні події</b> (15)\n\n" + "\n".join(lines)

    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🏠 Дашборд", callback_data="home")]
    ])

    try:
        await cb.message.edit_text(txt, reply_markup=kb)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            raise

    await cb.answer()
