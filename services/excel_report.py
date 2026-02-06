import asyncio
import logging
from datetime import datetime, timedelta
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
import database.db_api as db
import config

logger = logging.getLogger(__name__)

async def generate_report(period):
    """
    Генерує Excel звіт за вказаний період.
    period: 'current' (поточний місяць) або 'prev' (минулий місяць)
    """
    try:
        logger.info(f"📊 Початок генерації звіту: {period}")
        
        # Визначаємо період
        now = datetime.now(config.KYIV)
        
        if period == "current":
            start_date = now.replace(day=1)
            # Останній день поточного місяця
            if now.month == 12:
                end_date = now.replace(day=31)
            else:
                end_date = (now.replace(month=now.month + 1, day=1) - timedelta(days=1))
            period_name = start_date.strftime("%B %Y")
        else:  # prev
            # Перший день минулого місяця
            first_day_current = now.replace(day=1)
            last_day_prev = first_day_current - timedelta(days=1)
            start_date = last_day_prev.replace(day=1)
            end_date = last_day_prev
            period_name = start_date.strftime("%B %Y")
        
        start_str = start_date.strftime("%Y-%m-%d")
        end_str = end_date.strftime("%Y-%m-%d")
        
        logger.info(f"📅 Період: {start_str} - {end_str}")
        
        # Отримуємо логи
        logs = db.get_logs_for_period(start_str, end_str)
        
        if not logs:
            logger.warning("⚠️ Немає даних за вказаний період")
            return None, f"⚠️ Немає даних за {period_name}"
        
        logger.info(f"📋 Знайдено записів: {len(logs)}")
        
        # Створюємо Excel файл
        wb = Workbook()
        ws = wb.active
        ws.title = f"Звіт {period_name}"
        
        # Стилі
        header_font = Font(bold=True, size=12, color="FFFFFF")
        header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
        header_alignment = Alignment(horizontal="center", vertical="center")
        
        border_thin = Border(
            left=Side(style='thin'),
            right=Side(style='thin'),
            top=Side(style='thin'),
            bottom=Side(style='thin')
        )
        
        # Заголовок звіту
        ws.merge_cells('A1:F1')
        title_cell = ws['A1']
        title_cell.value = f"Звіт роботи генератора за {period_name}"
        title_cell.font = Font(bold=True, size=14)
        title_cell.alignment = Alignment(horizontal="center")
        
        # Шапка таблиці
        headers = ["Дата/Час", "Подія", "Користувач", "Значення", "Водій", "Примітки"]
        ws.append([])  # Пустий рядок
        ws.append(headers)
        
        header_row = ws.max_row
        for col_num, header in enumerate(headers, 1):
            cell = ws.cell(row=header_row, column=col_num)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_alignment
            cell.border = border_thin
        
        # Словник для перекладу подій
        event_names = {
            "m_start": "🌅 Ранок СТАРТ",
            "m_end": "🌅 Ранок СТОП",
            "d_start": "☀️ День СТАРТ",
            "d_end": "☀️ День СТОП",
            "e_start": "🌙 Вечір СТАРТ",
            "e_end": "🌙 Вечір СТОП",
            "x_start": "⚡ Екстра СТАРТ",
            "x_end": "⚡ Екстра СТОП",
            "refill": "⛽ Заправка",
            "auto_close": "🤖 Авто-закриття"
        }
        
        # Заповнюємо дані
        for log in logs:
            event_type, timestamp, user_name, value, driver_name = log
            
            # Форматуємо подію
            event_pretty = event_names.get(event_type, event_type)
            
            # Обробляємо значення
            value_display = ""
            notes = ""
            
            if event_type == "refill" and value:
                if "|" in value:
                    liters, receipt = value.split("|", 1)
                    value_display = f"{liters} л"
                    notes = f"Чек: {receipt}"
                else:
                    value_display = f"{value} л"
            elif value:
                value_display = value
            
            # Додаємо рядок
            row_data = [
                timestamp,
                event_pretty,
                user_name or "",
                value_display,
                driver_name or "",
                notes
            ]
            ws.append(row_data)
            
            # Застосовуємо бордери
            row_num = ws.max_row
            for col_num in range(1, 7):
                ws.cell(row=row_num, column=col_num).border = border_thin
        
        # Автоматична ширина колонок
        column_widths = {
            'A': 20,  # Дата/Час
            'B': 20,  # Подія
            'C': 25,  # Користувач
            'D': 15,  # Значення
            'E': 20,  # Водій
            'F': 30   # Примітки
        }
        
        for col, width in column_widths.items():
            ws.column_dimensions[col].width = width
        
        # Додаємо статистику внизу
        ws.append([])  # Пустий рядок
        stats_row_start = ws.max_row + 1
        
        # Підраховуємо статистику
        total_starts = sum(1 for log in logs if log[0].endswith('_start'))
        total_refills = sum(1 for log in logs if log[0] == 'refill')
        total_liters = 0.0
        
        for log in logs:
            if log[0] == 'refill' and log[3]:
                value_str = log[3]
                if "|" in value_str:
                    liters_str = value_str.split("|")[0]
                else:
                    liters_str = value_str
                try:
                    total_liters += float(liters_str)
                except (ValueError, TypeError):
                    pass
        
        # Додаємо статистику
        ws.append(["СТАТИСТИКА"])
        stats_row = ws.max_row
        ws.cell(row=stats_row, column=1).font = Font(bold=True, size=12)
        
        ws.append([f"Загальна кількість запусків:", total_starts])
        ws.append([f"Загальна кількість заправок:", total_refills])
        ws.append([f"Загальна кількість палива:", f"{total_liters:.1f} л"])
        
        # Отримуємо стан генератора
        state = db.get_state()
        ws.append([f"Загальний наробіток:", f"{state['total_hours']:.1f} год"])
        ws.append([f"До ТО (мастило):", f"{(config.MAINTENANCE_LIMIT - (state['total_hours'] - state['last_oil'])):.1f} год"])
        
        # Форматування статистики
        for row_num in range(stats_row, ws.max_row + 1):
            ws.cell(row=row_num, column=1).font = Font(bold=True)
        
        # Зберігаємо файл
        filename = f"report_{period}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        wb.save(filename)
        
        logger.info(f"✅ Звіт згенеровано: {filename}")
        
        caption = (
            f"📊 <b>Звіт за {period_name}</b>\n\n"
            f"📅 Період: {start_date.strftime('%d.%m.%Y')} - {end_date.strftime('%d.%m.%Y')}\n"
            f"📝 Записів: {len(logs)}\n"
            f"🚀 Запусків: {total_starts}\n"
            f"⛽ Заправок: {total_refills} ({total_liters:.1f} л)\n"
            f"⏱ Наробіток: {state['total_hours']:.1f} год"
        )
        
        return filename, caption
        
    except Exception as e:
        logger.error(f"❌ Помилка генерації звіту: {e}", exc_info=True)
        return None, f"❌ Помилка генерації звіту: {str(e)}"
