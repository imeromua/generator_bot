import asyncio
import logging
from datetime import datetime, time, timedelta

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

import config
import database.db_api as db
from utils.time import format_hours_hhmm

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _schedule_to_ranges(schedule: dict) -> list[tuple[int, int]]:
    """Перетворює schedule{hour->0/1} у список діапазонів (start_h, end_h), де end_h не включно."""
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


def _yesterday_shifts_summary(now: datetime) -> str:
    y = (now - timedelta(days=1)).date()
    y_str = y.strftime("%Y-%m-%d")

    logs = db.get_logs_for_period(y_str, y_str)

    shifts = {"m": {}, "d": {}, "e": {}, "x": {}}

    for event_type, ts, user_name, value, driver_name in logs:
        if event_type in ("m_start", "m_end", "d_start", "d_end", "e_start", "e_end", "x_start", "x_end"):
            code = event_type.split("_")[0]
            act = event_type.split("_")[1]
            try:
                hhmm = ts.split(" ")[1][:5]
            except Exception:
                hhmm = ""
            if code in shifts and hhmm:
                shifts[code][act] = hhmm

    names = {"m": "🌅 Ранок", "d": "☀️ День", "e": "🌙 Вечір", "x": "⚡ Екстра"}

    lines = []
    any_data = False
    for code in ("m", "d", "e", "x"):
        s = shifts[code].get("start")
        e = shifts[code].get("end")

        if s or e:
            any_data = True

        if s and e:
            lines.append(f"{names[code]}: <b>{s}–{e}</b>")
        elif s and not e:
            lines.append(f"{names[code]}: <b>{s}</b> (не закрито)")
        elif (not s) and e:
            lines.append(f"{names[code]}: (є закриття <b>{e}</b>, старт не знайдено)")
        else:
            lines.append(f"{names[code]}: —")

    if not any_data:
        return "—"

    return "\n".join(lines)


def _parse_state_dt(value: str) -> datetime | None:
    if not value:
        return None

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            dt = datetime.strptime(value.strip(), fmt)
            return config.KYIV.localize(dt.replace(tzinfo=None))
        except Exception:
            continue

    return None


async def scheduler_loop(bot):
    """
    Фоновий процес для автоматичних нагадувань та перевірок.
    - Щоранковий брифінг строго о 07:30 (вікно 2 хв), тільки для юзерів (не адмінів)
    - Авто-закриття зміни о WORK_END_TIME
    - Алерти по паливу (адмінам) + кнопка "Паливо замовлено"
    - Нагадування "натисніть СТОП" за N хв до WORK_END_TIME
    """
    logger.info("⏰ Scheduler запущено")

    brief_sent_today = False
    auto_close_done_today = False
    last_check_date = None

    brief_window_seconds = 120  # 2 хв

    while True:
        try:
            now = datetime.now(config.KYIV)
            current_date = now.date()
            today_str = current_date.strftime("%Y-%m-%d")

            # Скидаємо прапорці на початку нового дня
            if last_check_date != current_date:
                brief_sent_today = False
                auto_close_done_today = False
                last_check_date = current_date
                logger.info(f"📅 Новий день: {current_date}")

            # === 1. РАНКОВИЙ БРИФІНГ ===
            try:
                brief_time = datetime.strptime(config.MORNING_BRIEF_TIME, "%H:%M").time()
            except Exception:
                logger.error(f"❌ Неправильний формат MORNING_BRIEF_TIME: {getattr(config, 'MORNING_BRIEF_TIME', None)}")
                brief_time = time(7, 30)

            target_dt = config.KYIV.localize(datetime.combine(current_date, brief_time).replace(tzinfo=None))
            diff_s = (now - target_dt).total_seconds()

            # Якщо бот запустили/перезапустили вже після вікна — брифінг за цей день пропускаємо
            if (diff_s >= brief_window_seconds) and (not brief_sent_today):
                brief_sent_today = True

            if (0 <= diff_s < brief_window_seconds) and (not brief_sent_today):
                logger.info(f"📢 Час ранкового брифінгу: {brief_time.strftime('%H:%M')}")

                schedule = db.get_schedule(today_str)
                ranges = _schedule_to_ranges(schedule)
                total_off = sum((e - s) for s, e in ranges)

                st = db.get_state()
                try:
                    current_fuel = float(st.get("current_fuel", 0.0) or 0.0)
                except Exception:
                    current_fuel = 0.0

                hours_left = current_fuel / config.FUEL_CONSUMPTION if config.FUEL_CONSUMPTION > 0 else 0
                hours_left_hhmm = format_hours_hhmm(hours_left)

                to_service = config.MAINTENANCE_LIMIT - (st["total_hours"] - st["last_oil"])
                to_service_hhmm = format_hours_hhmm(to_service)

                now_h = now.hour
                now_status = "🔴 Зараз: <b>відключення</b>" if int(schedule.get(now_h, 0) or 0) == 1 else "🟢 Зараз: <b>світло є</b>"

                txt = (
                    f"☀️ <b>Ранковий брифінг</b> ({now.strftime('%d.%m.%Y')})\n\n"
                    f"📅 <b>Графік відключень (сьогодні)</b>\n"
                )

                if not ranges:
                    txt += "✅ Відключень не заплановано.\n"
                else:
                    for s, e in ranges:
                        txt += f"🔴 {_fmt_range(s, e)}\n"
                    txt += f"\n⏱ Сумарно без світла: <b>{total_off} год</b>\n"

                txt += f"{now_status}\n\n"

                txt += (
                    f"⛽ Паливо (за таблицею): <b>{current_fuel:.1f} л</b>\n"
                    f"⏳ Вистачить на: <b>~{hours_left_hhmm}</b>\n"
                    f"🛢 До ТО: <b>{to_service_hhmm}</b>\n\n"
                )

                txt += "📌 <b>Вчорашні зміни</b>\n"
                txt += _yesterday_shifts_summary(now)
                txt += "\n\n"

                # Нагадування
                reminders = []
                if current_fuel < config.FUEL_ALERT_THRESHOLD_L:
                    reminders.append(f"⚠️ Низький рівень палива: <b>{current_fuel:.1f} л</b>")
                if to_service <= 0:
                    reminders.append(f"⚠️ ТО прострочене: <b>{to_service_hhmm}</b>")
                elif to_service < 20:
                    reminders.append(f"⏳ До ТО залишилось: <b>{to_service_hhmm}</b>")

                if reminders:
                    txt += "🔔 <b>Нагадування</b>\n" + "\n".join(reminders)

                users = db.get_all_users()

                if not users:
                    logger.warning("⚠️ Немає користувачів для розсилки")
                else:
                    success_count = 0
                    fail_count = 0

                    for user_id, user_name in users:
                        # Брифінг тільки юзерам (не адмінам)
                        if user_id in config.ADMIN_IDS:
                            continue

                        try:
                            await bot.send_message(user_id, txt)
                            success_count += 1
                            await asyncio.sleep(0.05)
                        except Exception as e:
                            fail_count += 1
                            logger.warning(f"⚠️ Не вдалося надіслати {user_name} (ID: {user_id}): {e}")

                    logger.info(f"✅ Брифінг надіслано: {success_count} успішно, {fail_count} помилок")

                brief_sent_today = True

            # === 2. АВТО-ЗАКРИТТЯ ЗМІНИ ===
            try:
                close_time = datetime.strptime(config.WORK_END_TIME, "%H:%M").time()
            except ValueError:
                logger.error(f"❌ Неправильний формат WORK_END_TIME: {config.WORK_END_TIME}")
                close_time = time(20, 30)

            if now.time() >= close_time and not auto_close_done_today:
                state = db.get_state()

                # Перевіряємо чи зміна активна
                if state.get('status') == 'ON':
                    logger.info(f"🌙 Час авто-закриття: {config.WORK_END_TIME}")

                    active_shift = (state.get('active_shift', 'none') or 'none').strip()
                    code = active_shift.split('_')[0] if ('_' in active_shift) else active_shift
                    end_event = None
                    if code in ("m", "d", "e", "x"):
                        end_event = f"{code}_end"

                    # Розрахунок тривалості
                    try:
                        start_date_str = state.get('start_date', '')
                        start_time_str = state.get('start_time', '')

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

                    # OFFLINE: локально обліковуємо паливо/години (як у user handler)
                    remaining_fuel = None
                    try:
                        if db.sheet_is_offline():
                            db.update_hours(dur)
                            remaining_fuel = db.update_fuel(-fuel_consumed)
                    except Exception:
                        pass

                    # Скидання статусу
                    db.set_state('status', 'OFF')
                    db.set_state('active_shift', 'none')

                    # Логування: закриваємо саме активну зміну, а також пишемо технічний auto_close
                    ts = now.strftime("%Y-%m-%d %H:%M:%S")
                    try:
                        if end_event:
                            db.add_log(end_event, 'System', ts=ts)
                    except Exception:
                        pass

                    try:
                        db.add_log('auto_close', 'System', ts=ts)
                    except Exception:
                        pass

                    logger.info(f"🤖 Авто-закриття виконано: shift={active_shift}, {dur:.2f} год, витрачено {fuel_consumed:.1f}л")

                    # Сповіщення адмінів
                    dur_hhmm = format_hours_hhmm(dur)
                    rem_line = f"\n⛽ Залишок: <b>{remaining_fuel:.1f} л</b>" if (remaining_fuel is not None) else ""
                    admin_txt = (
                        f"🤖 <b>Авто-закриття зміни</b>\n\n"
                        f"🧩 Зміна: <b>{active_shift}</b>\n"
                        f"⏱ Працював: <b>{dur_hhmm}</b>\n"
                        f"📉 Використано (розрах.): <b>{fuel_consumed:.1f} л</b>"
                        f"{rem_line}\n"
                        f"🕐 Час закриття: {now.strftime('%H:%M')}"
                    )

                    for admin_id in config.ADMIN_IDS:
                        try:
                            await bot.send_message(admin_id, admin_txt)
                        except Exception as e:
                            logger.warning(f"⚠️ Не вдалося надіслати адміну {admin_id}: {e}")

                else:
                    logger.info(f"ℹ️ Час {config.WORK_END_TIME}: зміна вже закрита")

                auto_close_done_today = True

            # === 3. НАГАДУВАННЯ "НАТИСНІТЬ СТОП" ===
            try:
                reminder_min = max(1, int(getattr(config, "STOP_REMINDER_MIN_BEFORE_END", 15)))
            except Exception:
                reminder_min = 15

            try:
                close_dt = config.KYIV.localize(datetime.combine(current_date, close_time).replace(tzinfo=None))
                reminder_dt = close_dt - timedelta(minutes=reminder_min)
            except Exception:
                close_dt = None
                reminder_dt = None

            state = db.get_state()
            if reminder_dt and close_dt and state.get("status") == "ON":
                sent_date = db.get_state_value("stop_reminder_sent_date", "") or ""
                if (reminder_dt <= now < close_dt) and (sent_date != today_str):
                    active = state.get("active_shift", "none")
                    st_time = state.get("start_time", "")
                    txt = (
                        f"⏰ <b>Нагадування</b>\n\n"
                        f"До кінця робочого дня лишилось <b>{reminder_min} хв</b>.\n"
                        f"Якщо генератор вже вимкнули — натисніть <b>СТОП</b> в боті, щоб закрити зміну.\n\n"
                        f"Поточний стан: <b>ON</b>\n"
                        f"Активна зміна: <b>{active}</b>\n"
                        f"Старт був о: <b>{st_time}</b>"
                    )

                    for admin_id in config.ADMIN_IDS:
                        try:
                            await bot.send_message(admin_id, txt, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                [InlineKeyboardButton(text="🏠 Дашборд", callback_data="home")]
                            ]))
                        except Exception as e:
                            logger.warning(f"⚠️ STOP reminder: не вдалося надіслати адміну {admin_id}: {e}")

                    db.set_state("stop_reminder_sent_date", today_str)

            # === 4. АЛЕРТИ ПО ПАЛИВУ (АДМІНАМ) ===
            try:
                fuel_level = float(state.get("current_fuel", 0.0) or 0.0)
            except Exception:
                fuel_level = 0.0

            threshold = float(getattr(config, "FUEL_ALERT_THRESHOLD_L", 40.0) or 40.0)
            cooldown_min = int(getattr(config, "FUEL_ALERT_COOLDOWN_MIN", 60) or 60)

            ordered_date = (db.get_state_value("fuel_ordered_date", "") or "").strip()

            # Якщо паливо відновилось — знімаємо прапорець "замовлено"
            if fuel_level >= threshold and ordered_date:
                db.set_state("fuel_ordered_date", "")

            if fuel_level < threshold and ordered_date != today_str:
                last_sent_raw = (db.get_state_value("fuel_alert_last_sent_ts", "") or "").strip()
                last_sent_dt = _parse_state_dt(last_sent_raw)
                can_send = (last_sent_dt is None) or ((now - last_sent_dt) >= timedelta(minutes=cooldown_min))

                if can_send:
                    hours_left = fuel_level / config.FUEL_CONSUMPTION if config.FUEL_CONSUMPTION > 0 else 0
                    hours_left_hhmm = format_hours_hhmm(hours_left)

                    txt = (
                        f"⛽ <b>Низький рівень палива</b>\n\n"
                        f"Поточний залишок: <b>{fuel_level:.1f} л</b> (поріг: {threshold:.0f} л)\n"
                        f"Вистачить на: <b>~{hours_left_hhmm}</b>\n\n"
                        f"Якщо паливо вже замовили — натисніть кнопку нижче, і нагадування вимкнеться до заправки."
                    )

                    kb = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="✅ Паливо замовлено", callback_data="fuel_ordered")],
                        [InlineKeyboardButton(text="🏠 Дашборд", callback_data="home")],
                    ])

                    for admin_id in config.ADMIN_IDS:
                        try:
                            await bot.send_message(admin_id, txt, reply_markup=kb)
                        except Exception as e:
                            logger.warning(f"⚠️ Fuel alert: не вдалося надіслати адміну {admin_id}: {e}")

                    db.set_state("fuel_alert_last_sent_ts", now.strftime("%Y-%m-%d %H:%M:%S"))

        except Exception as e:
            logger.error(f"❌ Scheduler Error: {e}", exc_info=True)

        await asyncio.sleep(60)
