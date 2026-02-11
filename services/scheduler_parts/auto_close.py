import logging
from datetime import datetime, timedelta, time as dt_time

import config
import database.db_api as db
from utils.time import format_hours_hhmm
from services.scheduler_parts.notify import send_single_window

logger = logging.getLogger(__name__)

# FIX #23: Grace period to avoid race condition with user closing shift
AUTO_CLOSE_GRACE_PERIOD_SECONDS = 60  # Wait 60s before auto-closing


async def maybe_auto_close_shift(
    bot,
    now: datetime,
    close_time: dt_time,
    auto_close_done_today: bool,
) -> tuple[bool, bool]:
    """Авто-закриття зміни після WORK_END_TIME.

    FIX #23: Added grace period to prevent race condition with user.
    FIX #22: Removed duplicate fuel calculation (now in try_stop_shift).
    FIX #24: Log forced_close events for audit trail.

    Returns: (auto_close_done_today, skip_rest_of_loop)
    """
    if now.time() < close_time or auto_close_done_today:
        return auto_close_done_today, False

    # FIX #23: Check if we're past grace period
    close_datetime = datetime.combine(now.date(), close_time).replace(tzinfo=config.KYIV)
    grace_end = close_datetime + timedelta(seconds=AUTO_CLOSE_GRACE_PERIOD_SECONDS)
    
    if now < grace_end:
        # Still within grace period, give user time to close manually
        return auto_close_done_today, False

    state = db.get_state()

    if state.get("status") == "ON":
        logger.info(f"🌙 Час авто-закриття: {config.WORK_END_TIME} (+{AUTO_CLOSE_GRACE_PERIOD_SECONDS}s grace period)")

        active_shift = (state.get("active_shift", "none") or "none").strip()
        code = active_shift.split("_")[0] if ("_" in active_shift) else active_shift
        end_event = f"{code}_end" if code in ("m", "d", "e", "x") else None

        close_ok = False
        close_reason = ""
        forced_close = False

        if end_event:
            try:
                res = db.try_stop_shift(end_event, "System", now)
                close_ok = bool(res.get("ok"))
                close_reason = str(res.get("reason", "") or "")
                
                # FIX #22: Get metrics from try_stop_shift (already calculated there)
                duration_hours = res.get("duration_hours", 0.0)
                fuel_consumed = res.get("fuel_consumed", 0.0)
                
            except Exception as e:
                close_ok = False
                close_reason = f"error:{e}"
                duration_hours = 0.0
                fuel_consumed = 0.0
        else:
            close_ok = False
            close_reason = "no_end_event"
            duration_hours = 0.0
            fuel_consumed = 0.0

        if not close_ok:
            if close_reason == "already_off":
                logger.info("🤖 Auto-close: зміна вже закрита, пропускаємо")
                return True, True

            if close_reason == "wrong_shift":
                logger.warning(
                    f"⚠️ Auto-close: wrong_shift (active_shift={active_shift}). "
                    f"Не робимо forced OFF, потрібна ручна перевірка."
                )

                admin_txt = (
                    f"⚠️ <b>Авто-закриття НЕ виконано</b>\n\n"
                    f"Причина: <b>wrong_shift</b>\n"
                    f"Активна зміна в state: <b>{active_shift}</b>\n\n"
                    f"Перевірте і закрийте зміну вручну (СТОП)."
                )

                for admin_id in config.ADMIN_IDS:
                    await send_single_window(bot, int(admin_id), admin_txt)

                return True, True

            # FIX #24: Log forced close with reason for audit trail
            forced_close = True
            db.set_state("status", "OFF")
            db.set_state("active_shift", "none")
            
            ts = now.strftime("%Y-%m-%d %H:%M:%S")
            try:
                db.add_log("forced_close", "System", val=close_reason, ts=ts)
                logger.info(f"📝 Logged forced_close event with reason: {close_reason}")
            except Exception as e:
                logger.error(f"❌ Failed to log forced_close: {e}")
            
            logger.warning(
                f"⚠️ Auto-close fallback: forced OFF (reason={close_reason}, active_shift={active_shift})"
            )

        # FIX #22: No need to manually update fuel/hours - try_stop_shift does it atomically
        # Just get current state for display
        try:
            st_fresh = db.get_state()
            remaining_fuel = float(st_fresh.get('current_fuel', 0.0) or 0.0)
        except Exception:
            remaining_fuel = None

        logger.info(
            f"🤖 Авто-закриття: shift={active_shift}, end_event={end_event}, "
            f"ok={close_ok}, forced={forced_close}, dur={duration_hours:.2f}h, fuel={fuel_consumed:.1f}l"
        )

        # Сповіщення адмінів (single-window)
        dur_hhmm = format_hours_hhmm(duration_hours)
        rem_line = f"\n⛽ Залишок: <b>{remaining_fuel:.1f} л</b>" if (remaining_fuel is not None) else ""
        warn_line = "\n⚠️ <b>Fallback</b>: закрито примусово" if forced_close else ""

        admin_txt = (
            f"🤖 <b>Авто-закриття зміни</b>\n\n"
            f"🧩 Зміна: <b>{active_shift}</b>\n"
            f"⏱ Працював: <b>{dur_hhmm}</b>\n"
            f"📉 Використано: <b>{fuel_consumed:.1f} л</b>"
            f"{rem_line}"
            f"{warn_line}\n"
            f"🕐 Час закриття: {now.strftime('%H:%M')}"
        )

        for admin_id in config.ADMIN_IDS:
            await send_single_window(bot, int(admin_id), admin_txt)

    else:
        logger.info(f"ℹ️ Час {config.WORK_END_TIME}: зміна вже закрита")

    return True, False
