import asyncio
import gspread
import logging
import os
from gspread.utils import rowcol_to_a1
from google.oauth2.service_account import Credentials
from datetime import datetime
import database.db_api as db
import config

logging.basicConfig(level=logging.INFO)

async def sync_loop():
    """Фоновий процес синхронізації"""
    if not config.SHEET_ID:
        logging.error("❌ SHEET_ID не знайдено! Синхронізацію вимкнено.")
        return

    if not os.path.exists("service_account.json"):
        logging.error("❌ Файл service_account.json не знайдено! Синхронізацію вимкнено.")
        return

    print(f"🚀 Google Sync запущено. Таблиця: {config.SHEET_NAME}")
    
    while True:
        try:
            scopes = [
                "https://spreadsheets.google.com/feeds", 
                "https://www.googleapis.com/auth/drive"
            ]
            creds = Credentials.from_service_account_file("service_account.json", scopes=scopes)
            client = gspread.authorize(creds)
            
            # Відкриваємо таблицю
            sheet = client.open_by_key(config.SHEET_ID).worksheet(config.SHEET_NAME)
            
            # --- ЕТАП 1: ЧИТАННЯ (Синхронізація водіїв) ---
            try:
                # Читаємо стовпець AB (28)
                drivers_raw = sheet.col_values(28)[2:] 
                drivers_clean = [d.strip() for d in drivers_raw if d.strip()]
                
                if drivers_clean:
                    db.sync_drivers_from_sheet(drivers_clean)
                    logging.info(f"✅ Синхронізовано {len(drivers_clean)} водіїв")
            except Exception as e:
                logging.error(f"⚠️ Не вдалося прочитати список водіїв: {e}")

            # --- ЕТАП 2: ЗАПИС ---
            logs = db.get_unsynced()
            if logs:
                logging.info(f"📤 Відправляю {len(logs)} записів у Google...")
                
                today_str = datetime.now(config.KYIV).strftime("%Y-%m-%d")
                cell = sheet.find(today_str, in_column=1) 
                
                if cell is None:
                    logging.warning(f"⚠️ Дата {today_str} не знайдена в стовпці А!")
                else:
                    r = cell.row
                    ids_to_mark = []
                    
                    for l in logs:
                        lid, ltype, ltime, luser, lval, ldriver, _ = l
                        t_only = ltime.split(" ")[1][:5]
                        
                        col = None
                        user_col = None 
                        
                        if ltype == "m_start":   col=2;  user_col=19
                        elif ltype == "m_end":   col=3
                        elif ltype == "d_start": col=4;  user_col=21
                        elif ltype == "d_end":   col=5
                        elif ltype == "e_start": col=6;  user_col=23
                        elif ltype == "e_end":   col=7
                        elif ltype == "x_start": col=8;  user_col=25
                        elif ltype == "x_end":   col=9
                        elif ltype == "auto_close": col=7 
                        
                        elif ltype == "refill":
                            try:
                                # === РОЗПАКОВКА (Літри | Чек) ===
                                if lval and "|" in lval:
                                    liters_str, receipt_str = lval.split("|", 1)
                                else:
                                    liters_str = lval if lval else "0"
                                    receipt_str = ""

                                # 1. ЛІТРИ (N = 14)
                                try:
                                    cur_val_raw = sheet.cell(r, 14).value
                                    if not cur_val_raw:
                                        cur_liters = 0.0
                                    else:
                                        cur_liters = float(cur_val_raw.replace(",", ".").replace(" ", ""))
                                except (ValueError, TypeError, AttributeError):
                                    cur_liters = 0.0

                                try:
                                    new_liters = float(liters_str)
                                except (ValueError, TypeError):
                                    new_liters = 0.0
                                
                                total_liters = cur_liters + new_liters
                                final_val_str = str(total_liters).replace(".", ",")

                                sheet.update(
                                    range_name=rowcol_to_a1(r, 14), 
                                    values=[[final_val_str]], 
                                    value_input_option='USER_ENTERED'
                                )

                                # 2. ЧЕК (P = 16)
                                try:
                                    cur_receipt = sheet.cell(r, 16).value
                                    if cur_receipt and receipt_str:
                                        new_receipt = f"{cur_receipt}, {receipt_str}"
                                    elif receipt_str:
                                        new_receipt = receipt_str
                                    else:
                                        new_receipt = cur_receipt if cur_receipt else ""
                                except (AttributeError, TypeError):
                                    new_receipt = receipt_str if receipt_str else ""

                                sheet.update(
                                    range_name=rowcol_to_a1(r, 16), 
                                    values=[[new_receipt]], 
                                    value_input_option='USER_ENTERED'
                                )
                                
                                # 3. ВОДІЙ (AA = 27)
                                if ldriver:
                                    sheet.update(
                                        range_name=rowcol_to_a1(r, 27), 
                                        values=[[ldriver]], 
                                        value_input_option='USER_ENTERED'
                                    )
                                
                                ids_to_mark.append(lid)
                                logging.info(f"✅ Синхронізовано заправку: {new_liters}л, чек: {receipt_str}")
                            except Exception as e:
                                logging.error(f"❌ Помилка синхронізації заправки ID {lid}: {e}")
                            continue
                        
                        # Запис часу та імені
                        if col:
                            try:
                                sheet.update(
                                    range_name=rowcol_to_a1(r, col), 
                                    values=[[t_only]], 
                                    value_input_option='USER_ENTERED'
                                )
                                
                                if user_col and luser: 
                                    sheet.update(
                                        range_name=rowcol_to_a1(r, user_col), 
                                        values=[[luser]], 
                                        value_input_option='RAW'
                                    )
                                
                                ids_to_mark.append(lid)
                                logging.info(f"✅ Синхронізовано подію: {ltype} о {t_only}")
                            except Exception as e:
                                logging.error(f"❌ Помилка синхронізації події ID {lid}: {e}")
                        
                    if ids_to_mark:
                        db.mark_synced(ids_to_mark)
                        logging.info(f"✅ Позначено {len(ids_to_mark)} записів як синхронізовані")
                        
        except gspread.exceptions.APIError as e:
            logging.error(f"❌ Google API Error: {e}")
        except gspread.exceptions.SpreadsheetNotFound:
            logging.error(f"❌ Таблиця з ID {config.SHEET_ID} не знайдена!")
        except Exception as e:
            logging.error(f"❌ Sync Error: {e}")
        
        await asyncio.sleep(60)
