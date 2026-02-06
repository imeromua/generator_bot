import asyncio
import logging
from datetime import datetime, time
import config
import database.db_api as db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def scheduler_loop(bot):
    """
    Фоновий процес для автоматичних нагадувань та перевірок.
    Наприклад: щоранковий брифінг о 07:50
    """
    logger.info("⏰ Scheduler запущено")
    
    brief_sent_today = False
    last_check_date = None
    
    while True:
        try:
            now = datetime.now(config.KYIV)
            current_date = now.date()
            
            # Скидаємо прапорець на початку нового дня
            if last_check_date != current_date:
                brief_sent_today = False
                last_check_date = current_date
                logger.info(f"📅 Новий день: {current_date}")
            
            # Парсимо час брифінгу
            try:
                brief_time = datetime.strptime(config.MORNING_BRIEF_TIME, "%H:%M").time()
            except ValueError:
                logger.error(f"❌ Неправильний формат BRIEF_TIME: {config.MORNING_BRIEF_TIME}")
                await asyncio.sleep(3600)  # Чекаємо годину і пробуємо знову
                continue
            
            # Перевіряємо, чи настав час брифінгу
            if now.time() >= brief_time and not brief_sent_today:
                logger.info(f"📢 Час для ранкового брифінгу: {config.MORNING_BRIEF_TIME}")
                
                # Отримуємо графік на сьогодні
                today_str = now.strftime("%Y-%m-%d")
                schedule = db.get_schedule(today_str)
                
                # Формуємо повідомлення
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
                
                # Отримуємо всіх користувачів
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
                            await asyncio.sleep(0.05)  # Невелика затримка між повідомленнями
                        except Exception as e:
                            fail_count += 1
                            logger.warning(f"⚠️ Не вдалося надіслати {user_name} (ID: {user_id}): {e}")
                    
                    logger.info(f"✅ Брифінг надіслано: {success_count} успішно, {fail_count} помилок")
                
                brief_sent_today = True
            
            # Перевіряємо стан генератора (приклад додаткової логіки)
            state = db.get_state()
            if state['status'] == 'ON':
                # Можна додати перевірку: якщо працює > 12 годин - надіслати попередження
                pass
            
            # Перевірка залишку палива
            fuel_level = state.get('current_fuel', 0)
            if fuel_level < 20:  # Менше 20 літрів
                # Можна надіслати попередження адмінам
                logger.warning(f"⚠️ Низький рівень палива: {fuel_level:.1f}л")
            
        except Exception as e:
            logger.error(f"❌ Scheduler Error: {e}", exc_info=True)
        
        # Перевіряємо кожну хвилину
        await asyncio.sleep(60)
