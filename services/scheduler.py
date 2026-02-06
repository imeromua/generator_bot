import asyncio
import logging
from datetime import datetime, time, timedelta

import config
import database.db_api as db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _format_hours_hhmm(hours_float: float) -> str:
    """Конвертує години (float) у формат ГГ:ХХ. Підтримує від'ємні значення."""
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


async def scheduler_loop(bot):
    """
    Фоновий процес для автоматичних нагадувань та перевірок.
    - Щоранковий брифінг строго о 07:30 (вікно 2 хв), тільки для юзерів (не адмінів)
    - Авто-закриття зміни о WORK_END_TIME
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

                today_str = now.strftime("%Y-%m-%d")
                schedule = db.get_schedule(today_str)
                ranges = _schedule_to_ranges(schedule)
                total_off = sum((e - s) for s, e in ranges)

                st = db.get_state()
                try:
                    current_fuel = float(st.get("current_fuel", 0.0) or 0.0)
                except Exception:
                    current_fuel = 0.0

                hours_left = current_fuel / config.FUEL_CONSUMPTION if config.FUEL_CONSUMPTION > 0 else 0
                hours_left_hhmm = _format_hours_hhmm(hours_left)

                to_service = config.MAINTENANCE_LIMIT - (st["total_hours"] - st["last_oil"])
                to_service_hhmm = _format_hours_hhmm(to_service)

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
                if current_fuel < 20:
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
                if state['status'] == 'ON':
                    logger.info(f"🌙 Час авто-закриття: {config.WORK_END_TIME}")

                    # Розрахунок тривалості
                    try:
                        start_date_str = state.get('start_date', '')
                        start_time_str = state['start_time']

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

                    except Exception as e:
                        logger.error(f"Помилка розрахунку тривалості: {e}")
                        dur = 0.0

                    # Оновлення годин та палива
                    db.update_hours(dur)
                    fuel_consumed = dur * config.FUEL_CONSUMPTION
                    remaining_fuel = db.update_fuel(-fuel_consumed)

                    # ⚠️ КРИТИЧНО: Скидання статусу
                    db.set_state('status', 'OFF')
                    db.set_state('active_shift', 'none')

                    # Логування
                    db.add_log('auto_close', 'System')

                    logger.info(f"🤖 Авто-закриття виконано: {dur:.2f} год, витрачено {fuel_consumed:.1f}л")

                    # Сповіщення адмінів
                    admin_txt = (
                        f"🤖 <b>Авто-закриття зміни</b>\n\n"
                        f"⏱ Працював: <b>{dur:.2f} год</b>\n"
                        f"📉 Використано: <b>{fuel_consumed:.1f} л</b>\n"
                        f"⛽ Залишок: <b>{remaining_fuel:.1f} л</b>\n"
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

            # === 3. ПЕРЕВІРКА ПАЛИВА ===
            fuel_level = db.get_state().get('current_fuel', 0)
            if fuel_level < 20:
                logger.warning(f"⚠️ Низький рівень палива: {fuel_level:.1f}л")

        except Exception as e:
            logger.error(f"❌ Scheduler Error: {e}", exc_info=True)

        await asyncio.sleep(60)
