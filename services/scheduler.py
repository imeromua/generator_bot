import asyncio
from datetime import datetime
import database.db_api as db
import config

async def scheduler_loop(bot):
    """
    Нескінченний цикл перевірки часу.
    Приймає об'єкт bot, щоб надсилати повідомлення.
    """
    print("⏰ Планувальник (Scheduler) запущено.")
    
    while True:
        now = datetime.now(config.KYIV)
        
        # 1. АВТО-ЗАКРИТТЯ ЗМІНИ (наприклад, 20:30)
        # Перевіряємо точний збіг години і хвилини
        end_t = datetime.strptime(config.WORK_END_TIME, "%H:%M").time()
        
        if now.hour == end_t.hour and now.minute == end_t.minute:
            st = db.get_state()
            if st['status'] == 'ON':
                # Розрахунок часу роботи
                start_dt = datetime.strptime(f"{now.date()} {st['start_time']}", "%Y-%m-%d %H:%M")
                dur = (now.replace(tzinfo=None) - start_dt).total_seconds() / 3600.0
                
                # Запис в БД
                db.update_hours(dur)
                db.set_state('status', 'OFF')
                db.add_log("auto_close", "SYSTEM") # Спеціальний лог
                
                # Сповіщення адмінам
                for admin_id in config.ADMIN_IDS:
                    try:
                        await bot.send_message(
                            admin_id, 
                            f"🏁 <b>АВТО-ЗАКРИТТЯ ({config.WORK_END_TIME})</b>\n"
                            f"Генератор примусово зупинено.\n"
                            f"⏱ Час роботи: {dur:.2f} год"
                        )
                    except: pass
            
            # Чекаємо 65 секунд, щоб не спрацювати двічі в одну хвилину
            await asyncio.sleep(65)

        # 2. РАНКОВИЙ БРИФ (наприклад, 07:50)
        brief_t = datetime.strptime(config.MORNING_BRIEF_TIME, "%H:%M").time()
        
        if now.hour == brief_t.hour and now.minute == brief_t.minute:
            # Формуємо текст графіка
            sched = db.get_schedule(now.strftime("%Y-%m-%d"))
            
            txt = f"📅 <b>БРИФ НА СЬОГОДНІ ({now.strftime('%d.%m')})</b>\n\n"
            # Форматування: 08:00 🔴 | 09:00 🟢 ...
            # Виводимо з 08:00 до 22:00
            for h in range(8, 22):
                icon = "🔴" if sched.get(h) == 1 else "🟢"
                txt += f"{h:02}:00 {icon}  "
                if h == 14: txt += "\n" # Перенос рядка для краси
            
            txt += "\n\n🔴 - Відключення\n🟢 - Світло є"

            # Розсилка всім активним юзерам
            users = db.get_all_users()
            for user_id, _ in users:
                try:
                    await bot.send_message(user_id, txt)
                except: pass
                
            await asyncio.sleep(65)

        # Перевірка кожні 30 секунд
        await asyncio.sleep(30)