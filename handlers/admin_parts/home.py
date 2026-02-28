import logging
from datetime import datetime, timedelta

from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext

import config
import database.db_api as db
from keyboards.builders import admin_panel

# FIX: Import shift_pretty for consistent formatting
try:
    from handlers.user_parts.sheets_shift import shift_pretty
except ImportError:
    # Fallback if import fails - емодзі часу доби
    def shift_pretty(code: str) -> str:
        mapping = {'m': '🌅 Зміна 1', 'd': '☀️ Зміна 2', 'e': '🌙 Зміна 3', 'x': '⚡ Екстра'}
        c = code.split('_')[0].lower() if '_' in code else code.lower()
        return mapping.get(c, code)


router = Router()
logger = logging.getLogger(__name__)


def _is_outdated_ui(cb: types.CallbackQuery) -> bool:
    """Повертає True, якщо callback прийшов зі старого повідомлення (не з відстежуваного single-window UI)."""
    try:
        ui = db.get_ui_message(int(cb.from_user.id))
    except Exception:
        ui = None

    if not ui:
        return False

    _chat_id, message_id = ui
    try:
        return int(cb.message.message_id) != int(message_id)
    except Exception:
        return False


def _format_sync_time(ts_str: str | None) -> str:
    """Форматує час синхронізації у зручному вигляді."""
    if not ts_str:
        return "ніколи"

    try:
        # Парсимо час із бази
        dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
        dt = dt.replace(tzinfo=config.KYIV)
        now = datetime.now(config.KYIV)

        # Обчислюємо різницю
        diff = now - dt

        if diff.total_seconds() < 60:
            return "щойно"
        elif diff.total_seconds() < 3600:
            mins = int(diff.total_seconds() // 60)
            return f"{mins} хв тому"
        elif diff.total_seconds() < 86400:
            hours = int(diff.total_seconds() // 3600)
            return f"{hours} год тому"
        elif dt.date() == (now - timedelta(days=1)).date():
            return f"вчора о {dt.strftime('%H:%M')}"
        else:
            return dt.strftime("%d.%m %H:%M")
    except Exception:
        return ts_str[:16] if ts_str else "невідомо"


# --- ВХІД В АДМІНКУ ---
@router.callback_query(F.data == "admin_home")
async def adm_menu(cb: types.CallbackQuery, state: FSMContext):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    # Якщо натиснули кнопку на старому повідомленні — прибираємо його
    if _is_outdated_ui(cb):
        try:
            await cb.message.delete()
        except Exception:
            pass
        return await cb.answer("✅ Оновлено (відкрийте адмінку з актуального меню)")

    await state.clear()
    logger.info(f"👤 Адмін {cb.from_user.id} відкрив панель")

    # 1. Отримуємо актуальний стан з БД
    st = db.get_state()

    # Отримуємо активний генератор
    active_gen = db.get_active_generator()
    gen_name = db.get_generator_name(active_gen)

    # Іконка генератора
    if active_gen == "emergency":
        gen_icon = "⚠️"
        gen_label = f"{gen_icon} <b>Генератор {gen_name}</b>"
    else:
        gen_icon = "🔋"
        gen_label = f"{gen_icon} <b>Генератор {gen_name}</b>"

    # --- СТАТУС ГЕНЕРАТОРА ---
    status = st.get("status", "OFF")
    if status == "ON":
        active_shift = st.get("active_shift", "невідомо")
        # FIX: Use shift_pretty() for consistent formatting
        shift_name = shift_pretty(active_shift)
        status_line = f"🟩 <b>ПРАЦЮЄ</b> ({shift_name})"
        start_time = st.get("start_time", "")
        if start_time:
            status_line += f"\n   ⏱ Старт: {start_time}"
    else:
        status_line = "🟢 <b>ВИМКНЕНО</b>"

    # --- ПАЛИВО ---
    try:
        current_fuel = float(st.get("current_fuel", 0.0) or 0.0)
    except ValueError:
        current_fuel = 0.0

    # Алерт при низькому рівні
    if current_fuel < config.FUEL_ALERT_THRESHOLD_L:
        fuel_icon = "⚠️"
    else:
        fuel_icon = "⛽"

    fuel_line = f"{fuel_icon} Паливо: <b>{current_fuel:.1f} л</b>"

    # --- СЕРВІС (ТО) ---
    try:
        total_hours = float(st.get("total_hours", 0.0) or 0.0)
        last_oil = float(st.get("last_oil_change", 0.0) or 0.0)
        limit = config.MAINTENANCE_LIMIT
        left_hours = limit - (total_hours - last_oil)
    except ValueError:
        left_hours = 0.0

    if left_hours < 0:
        mnt_icon = "💀 <b>ПРОСТРОЧЕНО!</b>"
    elif left_hours < 20:
        mnt_icon = "⚠️"
    else:
        mnt_icon = "🔧"

    mnt_line = f"{mnt_icon} До ТО: <b>{left_hours:.1f} год</b>"

    # --- МОТОГОДИНИ ---
    total_line = f"⏱ Загальні мотогодини: <b>{total_hours:.1f} год</b>"

    # FIX #23: Отримуємо останню синхронізацію
    last_sync_ts, last_sync_user = db.get_last_sync()
    if last_sync_ts:
        sync_time = _format_sync_time(last_sync_ts)
        if last_sync_user:
            sync_line = f"🔄 Остання синхронізація: {sync_time}\n   👤 Виконав: {last_sync_user}"
        else:
            sync_line = f"🔄 Остання синхронізація: {sync_time}"
    else:
        sync_line = "🔄 Остання синхронізація: ніколи"

    # FIX #23: Покращений дизайн адмін панелі з назвою генератора
    txt = (
        f"⚙️ <b>Адмін Панель</b>\n"
        f"──────────────────\n"
        f"{gen_label}\n"
        f"{status_line}\n\n"
        f"{fuel_line}\n"
        f"{mnt_line}\n"
        f"{total_line}\n"
        f"──────────────────\n"
        f"{sync_line}\n"
    )

    # Перевіряємо, чи це текстове повідомлення
    if cb.message.text:
        # Якщо текстове - редагуємо
        await cb.message.edit_text(text=txt, reply_markup=admin_panel())
    else:
        # Якщо документ - видаляємо і створюємо нове
        await cb.message.delete()
        new_msg = await cb.message.answer(text=txt, reply_markup=admin_panel())
        # Фіксуємо message_id нового повідомлення
        try:
            db.set_ui_message(int(cb.from_user.id), int(new_msg.chat.id), int(new_msg.message_id))
        except Exception:
            pass
        return

    # Фіксуємо message_id як єдине вікно для адміна
    try:
        db.set_ui_message(int(cb.from_user.id), int(cb.message.chat.id), int(cb.message.message_id))
    except Exception:
        pass
