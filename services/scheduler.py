import asyncio
from datetime import datetime
import database.db_api as db
import config

async def scheduler_loop(bot):
    """
    Нескінченний цикл перевірки часу.
    """
    print("⏰ Планувальник (Scheduler) запущено.")
    
    while True:
        now = datetime.now(config.KYIV)
        
        # 1. АВТО-ЗАКРИТТЯ ЗМІНИ
        end_t = datetime.strptime(config.WORK_END_TIME, "%H:%M").time()
        
        if now.hour == end_t.hour and now.minute == end_t.minute:
            st = db.get_state()
            if st['status'] == 'ON':
                # Розрахунок часу роботи
                start_dt = datetime.strptime(f"{now.date()} {st['start_time']}", "%Y-%m-%d %H:%M")
                dur = (now.replace(tzinfo=None) - start_dt).total_seconds() / 3600.0
                
                # Запис в БД
                db.update_hours(dur)
                
                # Витрата палива (якщо треба, можна і тут додати, але поки спрощено)
                # Краще додати, щоб баланс сходився:
                fuel_consumed = dur * config.FUEL_CONSUMPTION
                db.update_fuel(-fuel_consumed)

                db.set_state('status', 'OFF')
                
                # 👇 ВАЖЛИВО: Скидаємо активну зміну!
                db.set_state('active_shift', 'none') 
                
                db.add_log("auto_close", "SYSTEM") 
                
                # Сповіщення адмінам
                for admin_id in config.ADMIN_IDS:
                    try:
                        await bot.send_message(
                            admin_id, 
                            f"🏁 <b>АВТО-ЗАКРИТТЯ ({config.WORK_END_TIME})</b>\n"
                            f"Генератор примусово зупинено.\n"
                            f"⏱ Час роботи: {dur:.2f} год\n"
                            f"📉 Паливо: {fuel_consumed:.1f} л"
                        )
                    except: pass
            
            await asyncio.sleep(65)

        # 2. РАНКОВИЙ БРИФ
        brief_t = datetime.strptime(config.MORNING_BRIEF_TIME, "%H:%M").time()
        
        if now.hour == brief_t.hour and now.minute == brief_t.minute:
            sched = db.get_schedule(now.strftime("%Y-%m-%d"))
            
            txt = f"📅 <b>БРИФ НА СЬОГОДНІ ({now.strftime('%d.%m')})</b>\n\n"
            for h in range(8, 22):
                icon = "🔴" if sched.get(h) == 1 else "🟢"
                txt += f"{h:02}:00 {icon}  "
                if h == 14: txt += "\n"
            
            txt += "\n\n🔴 - Відключення\n🟢 - Світло є"

            users = db.get_all_users()
            for user_id, _ in users:
                try:
                    await bot.send_message(user_id, txt)
                except: pass
                
            await asyncio.sleep(65)

        await asyncio.sleep(30)