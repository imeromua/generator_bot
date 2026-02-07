import logging
from datetime import datetime, timedelta, time as dt_time

import config
import database.db_api as db
from utils.time import format_hours_hhmm

logger = logging.getLogger(__name__)


async def maybe_auto_close_shift(
    bot,
    now: datetime,
    close_time: dt_time,
    auto_close_done_today: bool,
) -> tuple[bool, bool]:
    """Авто-закриття зміни після WORK_END_TIME.

    Returns: (auto_close_done_today, skip_rest_of_loop)
    """
    if now.time() < close_time or auto_close_done_today:
        return auto_close_done_today, False

    state = db.get_state()

    # Перевіряємо чи зміна активна
    if state.get("status") == "ON":
        logger.info(f"🌙 Час авто-закриття: {config.WORK_END_TIME}")

        active_shift = (state.get("active_shift", "none") or "none").strip()
        code = active_shift.split("_")[0] if ("_" in active_shift) else active_shift
        end_event = f"{code}_end" if code in ("m", "d", "e", "x") else None

        # Розрахунок тривалості (для повідомлення/обліку OFFLINE)
        try:
            start_date_str = state.get("start_date", "")
            start_time_str = state.get("start_time", "")

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

        except Exception as e:
            logger.error(f"Помилка розрахунку тривалості: {e}")
            dur = 0.0

        fuel_consumed = dur * config.FUEL_CONSUMPTION

        close_ok = False
        close_reason = ""
        forced_close = False

        if end_event:
            try:
                res = db.try_stop_shift(end_event, "System", now)
                close_ok = bool(res.get("ok"))
                close_reason = str(res.get("reason", "") or "")
            except Exception as e:
                close_ok = False
                close_reason = f"error:{e}"
        else:
            close_ok = False
            close_reason = "no_end_event"

        if not close_ok:
            # якщо вже закрито кимось іншим — не дублюємо логи/облік
            if close_reason == "already_off":
                logger.info("🤖 Auto-close: зміна вже закрита, пропускаємо")
                return True, True

            # fallback: щоб не лишати генератор у ON при поламаному state
            forced_close = True
            db.set_state("status", "OFF")
            db.set_state("active_shift", "none")
            logger.warning(
                f"⚠️ Auto-close fallback: forced OFF (reason={close_reason}, active_shift={active_shift})"
            )

        # OFFLINE: локально обліковуємо паливо/години тільки якщо ми реально закрили
        remaining_fuel = None
        try:
            if db.sheet_is_offline() and (close_ok or forced_close):
                db.update_hours(dur)
                remaining_fuel = db.update_fuel(-fuel_consumed)
        except Exception:
            pass

        # Технічний лог auto_close
        ts = now.strftime("%Y-%m-%d %H:%M:%S")
        try:
            if close_ok or forced_close:
                db.add_log("auto_close", "System", ts=ts)
        except Exception:
            pass

        logger.info(
            f"🤖 Авто-закриття: shift={active_shift}, end_event={end_event}, "
            f"ok={close_ok}, forced={forced_close}, dur={dur:.2f}h, fuel={fuel_consumed:.1f}l"
        )

        # Сповіщення адмінів
        dur_hhmm = format_hours_hhmm(dur)
        rem_line = f"\n⛽ Залишок: <b>{remaining_fuel:.1f} л</b>" if (remaining_fuel is not None) else ""
        warn_line = "\n⚠️ <b>Fallback</b>: закрито примусово" if forced_close else ""

        admin_txt = (
            f"🤖 <b>Авто-закриття зміни</b>\n\n"
            f"🧩 Зміна: <b>{active_shift}</b>\n"
            f"⏱ Працював: <b>{dur_hhmm}</b>\n"
            f"📉 Використано (розрах.): <b>{fuel_consumed:.1f} л</b>"
            f"{rem_line}"
            f"{warn_line}\n"
            f"🕐 Час закриття: {now.strftime('%H:%M')}"
        )

        for admin_id in config.ADMIN_IDS:
            try:
                await bot.send_message(admin_id, admin_txt)
            except Exception as e:
                logger.warning(f"⚠️ Не вдалося надіслати адміну {admin_id}: {e}")

    else:
        logger.info(f"ℹ️ Час {config.WORK_END_TIME}: зміна вже закрита")

    return True, False
