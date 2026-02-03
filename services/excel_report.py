import pandas as pd
import os
from datetime import datetime, timedelta
import database.db_api as db
import config

async def generate_report(period_type):
    """
    period_type: 'current' або 'prev'
    """
    now = datetime.now(config.KYIV)
    cutoff_time = datetime.strptime(config.WORK_END_TIME, "%H:%M").time()

    # --- ВИЗНАЧЕННЯ ДАТ ---
    if period_type == "current":
        start_date = now.replace(day=1).strftime("%Y-%m-%d")
        if now.time() < cutoff_time:
            end_dt = now - timedelta(days=1)
        else:
            end_dt = now
        end_date = end_dt.strftime("%Y-%m-%d")
        filename = f"Звіт_{now.strftime('%B')}.xlsx"
        
        if end_date < start_date:
            return None, "📅 Місяць тільки почався, завершених змін ще немає."
            
    else: # prev
        last_month = now.replace(day=1) - timedelta(days=1)
        start_date = last_month.replace(day=1).strftime("%Y-%m-%d")
        end_date = last_month.strftime("%Y-%m-%d")
        filename = f"Звіт_Минулий.xlsx"

    # --- ОТРИМАННЯ ДАНИХ ---
    logs = db.get_logs_for_period(start_date, end_date)
    if not logs:
        return None, f"📂 Даних немає за період {start_date} - {end_date}"

    # --- ОБРОБКА PANDAS ---
    data_map = {}
    for row in logs:
        evt, ts, user, val, drv = row
        date_str = ts.split(" ")[0]
        time_str = ts.split(" ")[1][:5]

        if date_str not in data_map:
            data_map[date_str] = {"Дата": date_str}

        # Розкладаємо події
        if evt == "m_start": 
            data_map[date_str]["Ранок Старт"] = time_str
            data_map[date_str]["Ранок Хто"] = user
        elif evt == "m_end": data_map[date_str]["Ранок Кінець"] = time_str
        
        elif evt == "d_start": 
            data_map[date_str]["День Старт"] = time_str
            data_map[date_str]["День Хто"] = user
        elif evt == "d_end": data_map[date_str]["День Кінець"] = time_str
        
        elif evt == "e_start": 
            data_map[date_str]["Вечір Старт"] = time_str
            data_map[date_str]["Вечір Хто"] = user
        elif evt == "e_end" or evt == "auto_close": 
            data_map[date_str]["Вечір Кінець"] = time_str
        
        # 👇 ДОДАНО ОБРОБКУ ЕКСТРА ЗМІНИ
        elif evt == "x_start":
            data_map[date_str]["Екстра Старт"] = time_str
            data_map[date_str]["Екстра Хто"] = user
        elif evt == "x_end":
            data_map[date_str]["Екстра Кінець"] = time_str

        elif evt == "refill":
            cur = data_map[date_str].get("Заправка (л)", 0)
            try: add = float(val)
            except: add = 0
            data_map[date_str]["Заправка (л)"] = cur + add
            cur_d = data_map[date_str].get("Водій", "")
            if drv and drv not in cur_d:
                data_map[date_str]["Водій"] = f"{cur_d}, {drv}".strip(", ")

    # Створення таблиці
    df = pd.DataFrame(list(data_map.values()))
    
    # Сортування колонок (Додано Екстра)
    cols = ["Дата", 
            "Ранок Старт", "Ранок Кінець", "Ранок Хто",
            "День Старт", "День Кінець", "День Хто",
            "Вечір Старт", "Вечір Кінець", "Вечір Хто",
            "Екстра Старт", "Екстра Кінець", "Екстра Хто",
            "Заправка (л)", "Водій"]
            
    final_cols = [c for c in cols if c in df.columns]
    df = df[final_cols].sort_values(by="Дата")

    # Збереження
    path = f"temp_{filename}"
    df.to_excel(path, index=False)
    
    return path, f"✅ Період: {start_date} — {end_date}"