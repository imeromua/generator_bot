import asyncio
import logging
from datetime import datetime, time, timedelta
import config
import database.db_api as db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def scheduler_loop(bot):
    """
    Фоновий процес для автоматичних нагадувань та перевірок.
    - Щоранковий брифінг о 07:50
    - Авто-закриття зміни о 20:30
    """
    logger.info("⏰ Scheduler запущено")
    
    brief_sent_today = False
    auto_close_done_today = False
    last_check_date = None
    
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
            except ValueError:
                logger.error(f"❌ Неправильний формат BRIEF_TIME: {config.MORNING_BRIEF_TIME}")
                brief_time = time(7, 50)
            
            if now.time() >= brief_time and not brief_sent_today:
                logger.info(f"📢 Час для ранкового брифінгу: {config.MORNING_BRIEF_TIME}")
                
                today_str = now.strftime("%Y-%m-%d")
                schedule = db.get_schedule(today_str)
                
                txt = f"☀️ <b>Доброго ранку!</b>\n\n"
                txt += f"📅 Графік відключень на сьогодні ({now.strftime('%d.%m.%Y')}):\n\n"
                
                has_outages = any(schedule.get(h) == 1 for h in range(8, 22))
                
                if has_outages:
                    for h in range(8, 22):
                        icon = "🔴" if schedule.get(h) == 1 else "🟢"
                        txt += f"{h:02}:00 {icon}  "
                        if h == 14:
                            txt += "\n"
                    txt += "\n\n🔴 - Відключення\n🟢 - Світло є"
                else:
                    txt += "✅ Відключень не заплановано!"
                
                users = db.get_all_users()
                
                if not users:
                    logger.warning("⚠️ Немає користувачів для розсилки")
                else:
                    success_count = 0
                    fail_count = 0
                    
                    for user_id, user_name in users:
                        try:
                            await bot.send_message(user_id, txt)
                            success_count += 1
                            await asyncio.sleep(0.05)
                        except Exception as e:
                            fail_count += 1
                            logger.warning(f"⚠️ Не вдалося надіслати {user_name} (ID: {user_id}): {e}")
                    
                    logger.info(f"✅ Брифінг надіслано: {success_count} успішно, {fail_count} помилок")
                
                brief_sent_today = True
            
            # === 2. АВТО-ЗАКРИТТЯ ЗМІНИ О 20:30 ===
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
                    db.set_state('active_shift', 'none')  # ⚠️ ЦЕ КЛЮЧОВИЙ РЯДОК!
                    
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
        
        # Перевіряємо кожну хвилину
        await asyncio.sleep(60)
