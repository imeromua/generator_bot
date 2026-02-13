"""Управління генераторами: UI для перемикання між основним та аварійним генератором.

Функціонал:
- Перемикання між генераторами (тільки коли статус OFF)
- Показ статистики кожного генератора
- Експорт звіту аварійного генератора в Excel
- Архів звітів
"""

import logging
from io import BytesIO
from datetime import datetime, timedelta

from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext

import config
import database.db_api as db
from keyboards.builders import InlineKeyboardBuilder

try:
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill
    from openpyxl.cell.cell import MergedCell
    from openpyxl.utils import get_column_letter
    EXCEL_AVAILABLE = True
except ImportError:
    EXCEL_AVAILABLE = False
    MergedCell = None
    get_column_letter = None

router = Router()
logger = logging.getLogger(__name__)

# Максимальна кількість звітів в архіві
MAX_ARCHIVE_SIZE = 10


def _generator_keyboard(last_export_time: str = None):
    """Клавіатура для управління генераторами.
    
    Args:
        last_export_time: Час останнього експорту (наприклад "21:36")
    """
    builder = InlineKeyboardBuilder()
    
    active_gen = db.get_active_generator()
    
    if active_gen == "main":
        builder.button(text="⚡ Перемкнути на АВАРІЙНИЙ", callback_data="gen_switch_emergency")
    else:
        builder.button(text="🔋 Перемкнути на ОСНОВНИЙ", callback_data="gen_switch_main")
    
    builder.button(text="📊 Статистика генераторів", callback_data="gen_stats")
    
    if active_gen == "emergency":
        export_text = "📥 Експорт звіту (Excel)"
        if last_export_time:
            export_text += f" • {last_export_time}"
        builder.button(text=export_text, callback_data="gen_export_excel")
        builder.button(text="📂 Архів звітів", callback_data="gen_archive")
    
    builder.button(text="🔙 Назад", callback_data="admin_home")
    builder.adjust(1)
    
    return builder.as_markup()


def _document_keyboard():
    """Клавіатура для документа звіту."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Повернутися до меню", callback_data="generator_switch")
    builder.adjust(1)
    return builder.as_markup()


@router.callback_query(F.data == "generator_switch")
async def gen_switch_menu(cb: types.CallbackQuery, state: FSMContext):
    """Головне меню перемикання генераторів.
    
    Важливо: підтримує концепцію "єдиного вікна" так само, як адмін-панель.
    Якщо меню відкривається з документа (звіт Excel), повідомлення-документ
    видаляється і створюється нове текстове повідомлення, яке стає новим
    tracked UI (db.set_ui_message).
    """
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)
    
    await state.clear()
    
    active_gen = db.get_active_generator()
    gen_name = db.get_generator_name(active_gen)
    
    st = db.get_state()
    status = st.get("status", "OFF")
    
    # Інформація про активний генератор
    if active_gen == "main":
        stats = db.get_generator_stats("main")
        info_text = (
            f"⚡ <b>Управління генераторами</b>\n"
            f"──────────────────\n"
            f"🔋 Активний: {gen_name}\n"
            f"📊 Статус: {'🟢 ВИМКНЕНО' if status == 'OFF' else '🟩 ПРАЦЮЄ'}\n\n"
            f"📈 Основний генератор:\n"
            f"  ⏱ Мотогодини: {stats['total_hours']:.1f} год\n"
            f"  🛢 Мастило: {stats['last_oil_change']:.1f} год\n"
            f"  🕯 Свічки: {stats['last_spark_change']:.1f} год\n\n"
            f"💡 Для перемикання генератор має бути вимкнений (OFF)"
        )
    else:
        stats = db.get_generator_stats("emergency")
        info_text = (
            f"⚡ <b>Управління генераторами</b>\n"
            f"──────────────────\n"
            f"⚠️ Активний: {gen_name}\n"
            f"📊 Статус: {'🟢 ВИМКНЕНО' if status == 'OFF' else '🟩 ПРАЦЮЄ'}\n\n"
            f"📈 Аварійний генератор:\n"
            f"  ⏱ Мотогодини: {stats['total_hours']:.1f} год\n"
            f"  🛢 Мастило: {stats['last_oil_change']:.1f} год\n"
            f"  🕯 Свічки: {stats['last_spark_change']:.1f} год\n\n"
            f"⚠️ <b>УВАГА!</b> Аварійний генератор НЕ синхронізується з Google Sheets.\n"
            f"Звіт можна експортувати в Excel.\n\n"
            f"💡 Для перемикання генератор має бути вимкнений (OFF)"
        )
    
    # Перевіряємо, чи це текстове повідомлення
    if cb.message.text:
        # Якщо текстове - редагуємо в рамках single-window
        await cb.message.edit_text(info_text, reply_markup=_generator_keyboard())
        msg_to_track = cb.message
    else:
        # Якщо документ - видаляємо і створюємо нове текстове повідомлення
        await cb.message.delete()
        msg_to_track = await cb.message.answer(info_text, reply_markup=_generator_keyboard())
    
    # Оновлюємо tracked UI, щоб _is_outdated_ui() в адмін-панелі не вважав
    # це старим повідомленням. Таким чином генератор-меню вписується в
    # концепцію "єдиного вікна" разом з admin_home.
    try:
        db.set_ui_message(int(cb.from_user.id), int(msg_to_track.chat.id), int(msg_to_track.message_id))
    except Exception:
        pass


@router.callback_query(F.data.startswith("gen_switch_"))
async def gen_switch_action(cb: types.CallbackQuery, state: FSMContext):
    """Перемикання генератора."""
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)
    
    target = "main" if cb.data == "gen_switch_main" else "emergency"
    
    # Отримуємо ім'я адміна
    user_info = db.get_user(int(cb.from_user.id))
    admin_name = user_info[1] if user_info else cb.from_user.full_name
    
    success, message = db.switch_generator(target, admin_name)
    
    if success:
        await cb.answer(message, show_alert=True)
        # Оновлюємо меню
        await gen_switch_menu(cb, state)
    else:
        await cb.answer(message, show_alert=True)


@router.callback_query(F.data == "gen_stats")
async def gen_stats_view(cb: types.CallbackQuery, state: FSMContext):
    """Показ статистики обох генераторів."""
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)
    
    main_stats = db.get_generator_stats("main")
    emerg_stats = db.get_generator_stats("emergency")
    
    active_gen = db.get_active_generator()
    
    # Отримуємо залишок палива як float
    try:
        current_fuel = float(db.get_state_value('current_fuel', '0.0'))
    except (ValueError, TypeError):
        current_fuel = 0.0
    
    text = (
        f"📊 <b>Статистика генераторів</b>\n"
        f"──────────────────\n\n"
        f"{'🔹' if active_gen == 'main' else '▫️'} <b>Основний генератор</b>\n"
        f"  ⏱ Мотогодини: {main_stats['total_hours']:.1f} год\n"
        f"  🛢 Від заміни мастила: {main_stats['last_oil_change']:.1f} год\n"
        f"  🕯 Від заміни свічок: {main_stats['last_spark_change']:.1f} год\n\n"
        f"{'🔸' if active_gen == 'emergency' else '▫️'} <b>Аварійний генератор</b>\n"
        f"  ⏱ Мотогодини: {emerg_stats['total_hours']:.1f} год\n"
        f"  🛢 Від заміни мастила: {emerg_stats['last_oil_change']:.1f} год\n"
        f"  🕯 Від заміни свічок: {emerg_stats['last_spark_change']:.1f} год\n\n"
        f"{'🔹' if active_gen == 'main' else '🔸'} - Активний генератор\n"
        f"──────────────────\n"
        f"💡 Спільні параметри:\n"
        f"  ⛽ Залишок палива: {current_fuel:.1f} л\n"
        f"  👥 Персонал та водії\n"
    )
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="generator_switch")
    
    await cb.message.edit_text(text, reply_markup=builder.as_markup())


@router.callback_query(F.data == "gen_archive")
async def gen_archive_view(cb: types.CallbackQuery, state: FSMContext):
    """Показ архіву звітів."""
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)
    
    # Отримуємо архів звітів з state
    archive_json = db.get_state_value('reports_archive', '[]')
    try:
        import json
        archive = json.loads(archive_json)
    except Exception:
        archive = []
    
    if not archive:
        await cb.answer("📂 Архів звітів порожній", show_alert=True)
        return
    
    text = (
        f"📂 <b>Архів звітів</b>\n"
        f"──────────────────\n"
        f"Останні {len(archive)} звітів:\n\n"
    )
    
    builder = InlineKeyboardBuilder()
    
    for idx, report in enumerate(reversed(archive), 1):
        file_id = report.get('file_id')
        timestamp = report.get('timestamp', '')
        
        # Форматуємо дату
        try:
            dt = datetime.fromisoformat(timestamp)
            date_str = dt.strftime("%d.%m.%Y %H:%M")
        except Exception:
            date_str = timestamp
        
        text += f"{idx}. 📊 {date_str}\n"
        builder.button(text=f"📥 Звіт #{idx}", callback_data=f"gen_get_report_{file_id}")
    
    builder.button(text="🔙 Назад", callback_data="generator_switch")
    builder.adjust(1)
    
    await cb.message.edit_text(text, reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("gen_get_report_"))
async def gen_get_report(cb: types.CallbackQuery, state: FSMContext):
    """Отримати звіт з архіву."""
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)
    
    file_id = cb.data.replace("gen_get_report_", "")
    
    await cb.answer("📤 Відправляю звіт...")
    
    try:
        # Видаляємо старе меню (єдине вікно)
        await cb.message.delete()
        
        # Відправляємо документ з кнопками
        await cb.message.answer_document(
            document=file_id,
            caption="📊 Звіт аварійного генератора з архіву",
            reply_markup=_document_keyboard()
        )
    except Exception as e:
        logger.error(f"Помилка отримання звіту з архіву: {e}")
        await cb.answer(f"❌ Помилка: {e}", show_alert=True)


@router.callback_query(F.data == "gen_export_excel")
async def gen_export_excel(cb: types.CallbackQuery, state: FSMContext):
    """Експорт звіту аварійного генератора в Excel."""
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)
    
    if not EXCEL_AVAILABLE:
        return await cb.answer(
            "❌ Модуль openpyxl не встановлено.\nВиконайте: pip install openpyxl",
            show_alert=True
        )
    
    await cb.answer("📤 Генерую звіт...")
    
    try:
        # Створюємо робочу книгу
        wb = Workbook()
        ws = wb.active
        ws.title = "Аварійний генератор"
        
        # Стилі
        header_fill = PatternFill(start_color="FFA500", end_color="FFA500", fill_type="solid")
        header_font = Font(bold=True, color="FFFFFF")
        
        # Заголовок
        ws['A1'] = "Звіт: Аварійний генератор"
        ws['A1'].font = Font(bold=True, size=14)
        ws.merge_cells('A1:D1')
        
        # Загальна інформація
        stats = db.get_generator_stats("emergency")
        st = db.get_state()
        
        ws['A3'] = "Мотогодини:"
        ws['B3'] = f"{stats['total_hours']:.2f} год"
        
        ws['A4'] = "Від заміни мастила:"
        ws['B4'] = f"{stats['last_oil_change']:.2f} год"
        
        ws['A5'] = "Від заміни свічок:"
        ws['B5'] = f"{stats['last_spark_change']:.2f} год"
        
        ws['A6'] = "Поточний залишок палива:"
        ws['B6'] = f"{float(st.get('current_fuel', 0.0)):.2f} л"
        
        # Таблиця подій
        ws['A8'] = "Журнал подій (аварійний генератор)"
        ws['A8'].font = Font(bold=True, size=12)
        
        # Заголовки таблиці
        headers = ["Дата/Час", "Подія", "Користувач", "Значення", "Водій"]
        for col, header in enumerate(headers, start=1):
            cell = ws.cell(row=9, column=col)
            cell.value = header
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center")
        
        # Отримуємо всі логи аварійного генератора за останні 30 днів
        end_date = datetime.now(config.KYIV).strftime("%Y-%m-%d")
        start_date = (datetime.now(config.KYIV) - timedelta(days=30)).strftime("%Y-%m-%d")
        
        logs = db.get_logs_for_period(start_date, end_date, generator_id="emergency")
        
        # Заповнюємо таблицю
        row = 10
        event_names = {
            "m_start": "🌅 Зміна 1 (початок)",
            "m_end": "🌅 Зміна 1 (кінець)",
            "d_start": "☀️ Зміна 2 (початок)",
            "d_end": "☀️ Зміна 2 (кінець)",
            "e_start": "🌙 Зміна 3 (початок)",
            "e_end": "🌙 Зміна 3 (кінець)",
            "x_start": "⚡ Екстра (початок)",
            "x_end": "⚡ Екстра (кінець)",
            "refill": "⛽ Заправка",
            "correction": "🔧 Корекція палива",
        }
        
        for log in logs:
            event_type, timestamp, user_name, value, driver_name, receipt_number, _ = log
            
            ws.cell(row=row, column=1).value = timestamp
            ws.cell(row=row, column=2).value = event_names.get(event_type, event_type)
            ws.cell(row=row, column=3).value = user_name or "-"
            ws.cell(row=row, column=4).value = value or "-"
            ws.cell(row=row, column=5).value = driver_name or "-"
            
            row += 1
        
        # Автоширина колонок (безпечно обробляємо MergedCell)
        for col_idx in range(1, 6):  # Колонки A-E
            max_length = 0
            # Отримуємо літеру колонки безпечно через функцію
            column_letter = get_column_letter(col_idx)
            
            for row_idx in range(1, ws.max_row + 1):
                cell = ws.cell(row=row_idx, column=col_idx)
                # Пропускаємо об'єднані комірки
                if MergedCell and isinstance(cell, MergedCell):
                    continue
                try:
                    cell_len = len(str(cell.value or ""))
                    if cell_len > max_length:
                        max_length = cell_len
                except Exception:
                    pass
            
            adjusted_width = min(max_length + 2, 50)
            ws.column_dimensions[column_letter].width = adjusted_width
        
        # Зберігаємо в пам'ять
        buffer = BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        
        # Відправляємо файл
        filename = f"emergency_generator_{datetime.now(config.KYIV).strftime('%Y%m%d_%H%M')}.xlsx"
        file = types.BufferedInputFile(buffer.read(), filename=filename)
        
        # Видаляємо старе меню (концепція єдиного вікна)
        await cb.message.delete()
        
        # Відправляємо документ з кнопками
        sent_msg = await cb.message.answer_document(
            document=file,
            caption=f"📊 Звіт аварійного генератора\n🗓 Період: {start_date} — {end_date}\n📁 {len(logs)} подій",
            reply_markup=_document_keyboard()
        )
        
        # Зберігаємо в архів
        import json
        archive_json = db.get_state_value('reports_archive', '[]')
        try:
            archive = json.loads(archive_json)
        except Exception:
            archive = []
        
        # Додаємо новий звіт
        archive.append({
            'file_id': sent_msg.document.file_id,
            'timestamp': datetime.now(config.KYIV).isoformat(),
            'filename': filename
        })
        
        # Обмежуємо розмір архіву
        if len(archive) > MAX_ARCHIVE_SIZE:
            archive = archive[-MAX_ARCHIVE_SIZE:]
        
        # Зберігаємо назад в БД
        db.set_state_value('reports_archive', json.dumps(archive))
        
    except Exception as e:
        logger.error(f"Помилка експорту Excel: {e}", exc_info=True)
        await cb.answer(f"❌ Помилка експорту: {e}", show_alert=True)
