import asyncio
import logging

from aiogram import Router, F, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

import config
import database.db_api as db
from keyboards.builders import sync_menu
from services.sheets_bidirectional_sync import bidirectional_sync
from utils.messaging import notify_success, notify_error  # FIX #25

# FIX: Import shift_pretty for user-friendly shift names
try:
    from handlers.user_parts.sheets_shift import shift_pretty
except ImportError:
    # Fallback if import fails
    def shift_pretty(code: str) -> str:
        mapping = {'m': '🟬 Зміна 1', 'd': '🟩 Зміна 2', 'e': '🟪 Зміна 3', 'x': '⚡ Екстра'}
        c = code.split('_')[0].lower() if '_' in code else code.lower()
        return mapping.get(c, code)

# Старі модулі sheets_import.py та sheets_export.py залишені як резервні утиліти.
# Можна використовувати через ручні скрипти якщо потрібно.

router = Router()
logger = logging.getLogger(__name__)


def _smart_sync_confirm_kb() -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton(text="✅ Підтверджую синхронізацію", callback_data="sync_smart_execute")],
        [InlineKeyboardButton(text="❌ Скасувати", callback_data="sync_menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


def _back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="sync_menu")]]
    )


def _acquire_sync_lock() -> bool:
    """FIX #14: Try to acquire sync lock atomically.
    
    Returns True if lock was acquired, False if sync is already in progress.
    """
    try:
        current = db.get_state_value("sync_in_progress", "0")
        if current == "1":
            return False
        db.set_state("sync_in_progress", "1")
        return True
    except Exception as e:
        logger.error(f"Failed to acquire sync lock: {e}")
        return False


def _release_sync_lock():
    """FIX #14: Release sync lock."""
    try:
        db.set_state("sync_in_progress", "0")
    except Exception as e:
        logger.error(f"Failed to release sync lock: {e}")


def _check_generator_off() -> tuple[bool, str]:
    """Перевіряє чи генератор вимкнений.
    
    Returns: (is_off: bool, message: str)
    """
    try:
        st = db.get_state() or {}
        status = (st.get("status") or "OFF").upper()
        
        if status == "ON":
            active_shift = st.get("active_shift", "none")
            # FIX: Use shift_pretty() for user-friendly display
            shift_name = shift_pretty(active_shift)
            return False, f"⛔ Синхронізація неможлива поки генератор працює ({shift_name}).\n\n📌 Закрийте активну зміну перед синхронізацією!"
        
        return True, ""
    except Exception as e:
        logger.error(f"Error checking generator status: {e}")
        return False, "⚠️ Помилка перевірки статусу генератора"


@router.callback_query(F.data == "sync_menu")
async def show_sync_menu(cb: types.CallbackQuery):
    """Показує меню синхронізації.
    
    Тільки розумна двонаправлена синхронізація.
    Старі окремі імпорт/експорт видалені з інтерфейсу.
    """
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    # FIX #14: Show if sync is already in progress
    sync_in_progress = db.get_state_value("sync_in_progress", "0") == "1"
    status_text = "\n⚠️ <b>Синхронізація вже виконується!</b>\n" if sync_in_progress else ""
    
    # Перевірка статусу генератора
    is_off, gen_msg = _check_generator_off()
    if not is_off:
        status_text += f"\n{gen_msg}\n"
    
    txt = (
        "🔄 <b>Розумна синхронізація з Google Sheets</b>\n\n"
        f"{status_text}"
        "🧠 <b>Автоматична двонаправлена синхронізація:</b>\n\n"
        "✅ Порівнює дані по датах між БД та Sheets\n"
        "✅ Синхронізує тільки зміни, не перезаписує\n"
        "✅ Автоматично вирішує конфлікти (більше даних = пріоритет)\n"
        "✅ Перевіряє витрати палива (колонка U)\n"
        "✅ Синхронізує довідники водіїв та персоналу\n\n"
        "🔒 <b>Безпека:</b>\n"
        "• Доступна тільки адміністраторам\n"
        "• Можлива лише коли генератор вимкнено (OFF)\n"
        "• Блокується під час виконання (lock)\n"
        "• Логується в системний журнал\n\n"
        "📊 Після синхронізації ви отримаєте детальний звіт.\n\n"
        "⚠️ <b>ВАЖЛИВО:</b> Синхронізація можлива тільки коли генератор ВИМКНЕНО."
    )
    await cb.message.edit_text(txt, reply_markup=sync_menu())
    await cb.answer()


# --- РОЗУМНА СИНХРОНІЗАЦІЯ ---
@router.callback_query(F.data == "sync_smart")
async def sync_smart_confirm(cb: types.CallbackQuery):
    """Підтвердження розумної синхронізації."""
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    # FIX #14: Check if sync is already in progress
    if db.get_state_value("sync_in_progress", "0") == "1":
        return await cb.answer("⚠️ Синхронізація вже виконується. Зачекайте.", show_alert=True)

    # Перевірка чи генератор вимкнений
    is_off, error_msg = _check_generator_off()
    if not is_off:
        return await cb.answer(error_msg, show_alert=True)

    txt = (
        "⚠️ <b>Підтвердження розумної синхронізації</b>\n\n"
        "🧠 Розумна синхронізація зробить наступне:\n\n"
        "✅ Порівняє дані по датах між БД та Sheets\n"
        "✅ Для кожної дати визначає:\n"
        "  • Якщо дата є тільки в БД → експорт в Sheets\n"
        "  • Якщо дата є тільки в Sheets → імпорт в БД\n"
        "  • Якщо дата є в обох → вирішує конфлікт (більше даних = пріоритет)\n"
        "  • Якщо дані однакові → пропускає\n\n"
        "✅ Перевіряє витрати палива (колонка U) на збіг з config.FUEL_CONSUMPTION\n"
        "✅ Синхронізує довідники водіїв та персоналу (колонки R, S)\n\n"
        "✅ Не перезаписує, а саме синхронізує зміни\n\n"
        "📏 Логує подію в системний журнал (доступно в боті)\n\n"
        "🔒 Безпечно для БД та Sheets.\n\n"
        "⚠️ Генератор має бути ВИМКНЕНИЙ (зараз OFF ✅)."
    )

    await cb.message.edit_text(txt, reply_markup=_smart_sync_confirm_kb())
    await cb.answer()


@router.callback_query(F.data == "sync_smart_execute")
async def sync_smart_execute(cb: types.CallbackQuery):
    """Виконання розумної синхронізації."""
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    user_id = cb.from_user.id  # FIX #25: For notifications

    # FIX #14: Acquire lock before starting
    if not _acquire_sync_lock():
        return await cb.answer(
            "⚠️ Синхронізація вже виконується. Зачекайте.",
            show_alert=True
        )

    try:
        # Подвійна перевірка перед виконанням
        is_off, error_msg = _check_generator_off()
        if not is_off:
            # FIX #25: Notify error
            notify_error(user_id, "❌ Синхронізація неможлива під час роботи генератора")
            return await cb.answer(error_msg, show_alert=True)

        # Отримуємо ім'я користувача з БД
        user = db.get_user(cb.from_user.id)
        if user:
            personnel_name = db.get_personnel_for_user(cb.from_user.id)
            user_name = personnel_name if personnel_name else (cb.from_user.full_name or "admin")
        else:
            user_name = cb.from_user.full_name or "admin"

        await cb.answer("⚙️ Синхронізація запускається...", show_alert=False)
        await cb.message.edit_text(
            "⏳ <b>Розумна синхронізація...</b>\n\n"
            "Зачекайте, це може зайняти кілька секунд..."
        )

        # Запускаємо двонаправлену синхронізацію з user_name
        report = await asyncio.to_thread(bidirectional_sync, user_name)

        # Формуємо звіт
        summary = report.summary()

        txt = (
            "✅ <b>Розумна синхронізація завершена!</b>\n"
            f"{summary}\n\n"
            "📏 Подія залогована в системний журнал (🕘 Останні події)."
        )

        await cb.message.edit_text(txt, reply_markup=_back_kb())
        
        # FIX #25: Notify success
        notify_success(
            user_id, 
            f"✅ Синхронізовано: {report.total_dates} дат, "
            f"імпорт: {report.imported}, експорт: {report.exported}"
        )

    except Exception as e:
        logger.error(f"❌ Помилка синхронізації: {e}", exc_info=True)
        
        # FIX #25: Notify error
        error_msg = str(e)[:100]  # Обрізаємо довгі помилки
        notify_error(user_id, f"❌ Помилка синхронізації: {error_msg}")
        
        await cb.message.edit_text(
            f"❌ <b>Помилка синхронізації</b>\n\n{e}",
            reply_markup=_back_kb(),
        )
    finally:
        # FIX #14: Always release lock
        _release_sync_lock()
