import asyncio
import gspread
from gspread.utils import rowcol_to_a1
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import logging
import database.db_api as db
import config

# Налаштування логування
logging.basicConfig(level=logging.INFO)

async def sync_loop():
    """Фоновий процес синхронізації"""
    # Захист від запуску без ID
    if not config.SHEET_ID:
        logging.error("❌ SHEETS_ID не знайдено! Синхронізацію вимкнено.")
        return

    print(f"🚀 Google Sync запущено. Таблиця: {config.SHEET_NAME} (ID: ...{str(config.SHEET_ID)[-5:]})")
    
    while True:
        try:
            # 1. Чи є що відправляти?
            logs = db.get_unsynced()
            if logs:
                logging.info(f"📤 Відправляю {len(logs)} записів у Google...")
                
                # 2. Авторизація
                scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
                creds = ServiceAccountCredentials.from_json_keyfile_name("service_account.json", scope)
                client = gspread.authorize(creds)
                
                # Відкриваємо таблицю
                sheet = client.open_by_key(config.SHEET_ID).worksheet(config.SHEET_NAME)
                
                today_str = datetime.now(config.KYIV).strftime("%d.%m.%Y")
                
                # 3. Шукаємо рядок
                cell = sheet.find(today_str, in_column=1) 
                
                if cell is None:
                    logging.warning(f"⚠️ Дата {today_str} не знайдена в стовпці А! Створіть рядок у таблиці.")
                else:
                    r = cell.row
                    ids_to_mark = []
                    
                    for l in logs:
                        lid, ltype, ltime, luser, lval, ldriver, _ = l
                        t_only = ltime.split(" ")[1][:5]
                        
                        col = None
                        user_col = None 
                        
                        if ltype == "m_start":   col=2;  user_col=16
                        elif ltype == "m_end":   col=3
                        elif ltype == "d_start": col=4;  user_col=17
                        elif ltype == "d_end":   col=5
                        elif ltype == "e_start": col=6;  user_col=18
                        elif ltype == "e_end":   col=7
                        elif ltype == "auto_close": col=7
                        
                        elif ltype == "refill":
                            # --- ЛОГІКА СУМУВАННЯ ---
                            
                            # 1. Читаємо, що вже є в клітинці (L - 12 колонка)
                            try:
                                cur_val_raw = sheet.cell(r, 12).value
                                cur_drv_raw = sheet.cell(r, 15).value
                                
                                # Якщо пусто - 0, якщо є - міняємо кому на крапку і робимо float
                                if not cur_val_raw: 
                                    cur_liters = 0.0
                                else: 
                                    cur_liters = float(cur_val_raw.replace(",", ".").replace(" ", ""))
                            except:
                                cur_liters = 0.0

                            # 2. Беремо нове значення
                            try: new_liters = float(lval)
                            except: new_liters = 0.0
                            
                            # 3. Сумуємо
                            total_liters = cur_liters + new_liters
                            
                            # 4. Об'єднуємо імена водіїв (щоб не стерти попереднього)
                            if cur_drv_raw:
                                # Перевіряємо, чи цього водія ще немає в списку
                                if ldriver not in cur_drv_raw:
                                    total_drivers = f"{cur_drv_raw}, {ldriver}"
                                else:
                                    total_drivers = cur_drv_raw
                            else:
                                total_drivers = ldriver

                            # 5. ХАК ДЛЯ ЧИСЛА: Перетворюємо у рядок з КОМОЮ
                            # Це змусить Google (Ukraine locale) зрозуміти, що це число
                            final_val_str = str(total_liters).replace(".", ",")

                            # Записуємо літри
                            sheet.update(
                                range_name=rowcol_to_a1(r, 12), 
                                values=[[final_val_str]], 
                                value_input_option='USER_ENTERED'
                            )
                            # Записуємо водіїв
                            sheet.update(
                                range_name=rowcol_to_a1(r, 15), 
                                values=[[total_drivers]], 
                                value_input_option='USER_ENTERED'
                            )
                            ids_to_mark.append(lid)
                            continue
                        
                        # Запис часу та імені (тут все стандартно)
                        if col:
                            sheet.update(
                                range_name=rowcol_to_a1(r, col), 
                                values=[[t_only]], 
                                value_input_option='USER_ENTERED'
                            )
                            
                            if user_col: 
                                sheet.update(
                                    range_name=rowcol_to_a1(r, user_col), 
                                    values=[[luser]], 
                                    value_input_option='RAW'
                                )
                        
                        ids_to_mark.append(lid)
                        
                    # 4. Позначаємо в БД як відправлені
                    if ids_to_mark:
                        db.mark_synced(ids_to_mark)
                        
        except Exception as e:
            logging.error(f"❌ Sync Error: {e}")
        
        await asyncio.sleep(60)