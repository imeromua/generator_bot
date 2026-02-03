import asyncio
import gspread
from gspread.utils import rowcol_to_a1
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import logging
import database.db_api as db
import config

logging.basicConfig(level=logging.INFO)

async def sync_loop():
    if not config.SHEET_ID:
        logging.error("❌ SHEETS_ID не знайдено! Синхронізацію вимкнено.")
        return

    print(f"🚀 Google Sync запущено. Таблиця: {config.SHEET_NAME} (ID: ...{str(config.SHEET_ID)[-5:]})")
    
    while True:
        try:
            logs = db.get_unsynced()
            if logs:
                logging.info(f"📤 Відправляю {len(logs)} записів у Google...")
                
                scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
                creds = ServiceAccountCredentials.from_json_keyfile_name("service_account.json", scope)
                client = gspread.authorize(creds)
                
                sheet = client.open_by_key(config.SHEET_ID).worksheet(config.SHEET_NAME)
                
                today_str = datetime.now(config.KYIV).strftime("%d.%m.%Y")
                
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
                        # 👇 ЕКСТРА (H=8, I=9)
                        elif ltype == "x_start": col=8;  user_col=19 # S=19
                        elif ltype == "x_end":   col=9
                        
                        elif ltype == "auto_close": col=7 # Або 9, якщо Екстра? Лишимо 7 поки
                        
                        elif ltype == "refill":
                            try:
                                cur_val_raw = sheet.cell(r, 12).value
                                cur_drv_raw = sheet.cell(r, 15).value
                                
                                if not cur_val_raw: cur_liters = 0.0
                                else: cur_liters = float(cur_val_raw.replace(",", ".").replace(" ", ""))
                            except: cur_liters = 0.0

                            try: new_liters = float(lval)
                            except: new_liters = 0.0
                            
                            total_liters = cur_liters + new_liters
                            
                            if cur_drv_raw:
                                if ldriver not in cur_drv_raw:
                                    total_drivers = f"{cur_drv_raw}, {ldriver}"
                                else:
                                    total_drivers = cur_drv_raw
                            else:
                                total_drivers = ldriver

                            final_val_str = str(total_liters).replace(".", ",")

                            sheet.update(
                                range_name=rowcol_to_a1(r, 12), 
                                values=[[final_val_str]], 
                                value_input_option='USER_ENTERED'
                            )
                            sheet.update(
                                range_name=rowcol_to_a1(r, 15), 
                                values=[[total_drivers]], 
                                value_input_option='USER_ENTERED'
                            )
                            ids_to_mark.append(lid)
                            continue
                        
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
                        
                    if ids_to_mark:
                        db.mark_synced(ids_to_mark)
                        
        except Exception as e:
            logging.error(f"❌ Sync Error: {e}")
        
        await asyncio.sleep(60)