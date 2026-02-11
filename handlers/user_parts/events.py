from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest
from datetime import datetime

import database.db_api as db
from handlers.user_parts.sheets_shift import shift_pretty
from handlers.user_parts.utils import ensure_user
from keyboards.builders import back_to_main

router = Router()


def _fmt_log_line(
    event_type: str,
    ts: str,
    user_name: str | None,
    value: str | None,
    driver: str | None,
    receipt: str | None,
) -> str:
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

    val = (value or "").strip()
    tail = f" — {val}" if val else ""
    who_tail = f" ({who})" if who else ""
    return f"• {ts_pretty} — <b>{event_type}</b>{tail}{who_tail}"


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
        for event_type, ts, u_name, value, driver_name, receipt_number in rows:
            lines.append(_fmt_log_line(event_type, ts, u_name, value, driver_name, receipt_number))

        txt = "🕘 <b>Останні події</b> (15)\n\n" + "\n".join(lines)

    kb = back_to_main()

    try:
        await cb.message.edit_text(txt, reply_markup=kb)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            raise

    await cb.answer()
