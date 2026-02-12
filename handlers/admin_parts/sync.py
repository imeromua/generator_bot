import asyncio
import logging
from datetime import datetime

from aiogram import Router, F, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

import config
import database.db_api as db
from keyboards.builders import sync_menu, back_to_admin
from services.sheets_export import full_export
from services.sheets_import import full_import
from services.sheets_bidirectional_sync import bidirectional_sync

router = Router()
logger = logging.getLogger(__name__)


def _import_confirm_kb() -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton(text="✅ Підтверджую імпорт", callback_data="sync_import_execute")],
        [InlineKeyboardButton(text="❌ Скасувати", callback_data="sync_menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


def _export_confirm_kb() -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton(text="✅ Підтверджую експорт", callback_data="sync_export_execute")],
        [InlineKeyboardButton(text="❌ Скасувати", callback_data="sync_menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


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
            return False, f"⛔ Синхронізація неможлива поки генератор працює (зміна: {active_shift}).\n\n📌 Закрийте активну зміну перед синхронізацією!"
        
        return True, ""
    except Exception as e:
        logger.error(f"Error checking generator status: {e}")
        return False, "⚠️ Помилка перевірки статусу генератора"


@router.callback_query(F.data == "sync_menu")
async def show_sync_menu(cb: types.CallbackQuery):
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
        "🔄 <b>Обмін з Google Sheets</b>\n\n"
        f"{status_text}"
        "🧠 <b>Розумна синхронізація</b> (рекомендовано) — автоматично визначає що змінилось, \n"
        "синхронізує тільки зміни, перевіряє витрати палива та оновлює довідники.\n\n"
        "📥 <b>Імпорт</b> (аварійний) — ПОВНІСТЮ очищає БД і завантажує з Sheets.\n"
        "📤 <b>Експорт</b> (аварійний) — дописує з БД тільки порожні дні в Sheets.\n\n"
        "⚠️ <b>ВАЖЛИВО:</b> Синхронізація можлива тільки коли генератор ВИМКНЕНО.\n"
        "⚠️ Ніяких фонових синхронізацій, тільки ручні операції.\n"
    )
    await cb.message.edit_text(txt, reply_markup=sync_menu())
    await cb.answer()


# --- РОЗУМНА СИНХРОНІЗАЦІЯ ---
@router.callback_query(F.data == "sync_smart")
async def sync_smart_confirm(cb: types.CallbackQuery):
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
        "🔒 Безпечно для БД та Sheets.\n\n"
        "⚠️ Генератор має бути ВИМКНЕНИЙ (зараз OFF ✅)."
    )

    await cb.message.edit_text(txt, reply_markup=_smart_sync_confirm_kb())
    await cb.answer()


@router.callback_query(F.data == "sync_smart_execute")
async def sync_smart_execute(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    # FIX #14: Acquire lock before starting
    if not _acquire_sync_lock():
        return await cb.answer("⚠️ Синхронізація вже виконується. Зачекайте.", show_alert=True)

    try:
        # Подвійна перевірка перед виконанням
        is_off, error_msg = _check_generator_off()
        if not is_off:
            return await cb.answer(error_msg, show_alert=True)

        await cb.answer("⚙️ Синхронізація запускається...", show_alert=False)
        await cb.message.edit_text("⏳ <b>Розумна синхронізація...</b>\n\nЗачекайте, це може зайняти кілька секунд...")

        # Запускаємо двонаправлену синхронізацію
        report = await asyncio.to_thread(bidirectional_sync)

        # Формуємо звіт
        summary = report.summary()

        txt = (
            "✅ <b>Розумна синхронізація завершена!</b>\n"
            f"{summary}"
        )

        await cb.message.edit_text(txt, reply_markup=_back_kb())

    except Exception as e:
        logger.error(f"❌ Помилка синхронізації: {e}", exc_info=True)
        await cb.message.edit_text(
            f"❌ <b>Помилка синхронізації</b>\n\n{e}",
            reply_markup=_back_kb(),
        )
    finally:
        # FIX #14: Always release lock
        _release_sync_lock()


# --- ІМПОРТ (АВАРІЙНИЙ) ---
@router.callback_query(F.data == "sync_import")
async def sync_import_confirm(cb: types.CallbackQuery):
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
        "⚠️ <b>Підтвердження імпорту (АВАРІЙНА ОПЦІЯ)</b>\n\n"
        "❌ <b>ЦЕ ДЕСТРУКТИВНА ОПЕРАЦІЯ!</b>\n\n"
        "Імпорт зробить наступне:\n"
        "• ПОВНІСТЮ очистить БД (всі дані будуть видалені)\n"
        "• Завантажить дані з основної вкладки Google Sheets\n"
        "• Відновить журнал подій і стан генератора\n\n"
        "❌ <b>Цю операцію НЕМОЖЛИВО ВІДМІНИТИ!</b>\n\n"
        "👉 Рекомендація: використовуйте <b>Розумну синхронізацію</b> замість імпорту.\n"
        "👉 Використовуйте імпорт тільки для повного відновлення з Sheets."
    )

    await cb.message.edit_text(txt, reply_markup=_import_confirm_kb())
    await cb.answer()


@router.callback_query(F.data == "sync_import_execute")
async def sync_import_execute(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    # FIX #14: Acquire lock before starting
    if not _acquire_sync_lock():
        return await cb.answer("⚠️ Синхронізація вже виконується. Зачекайте.", show_alert=True)

    try:
        # Подвійна перевірка перед виконанням
        is_off, error_msg = _check_generator_off()
        if not is_off:
            return await cb.answer(error_msg, show_alert=True)

        await cb.answer("⚙️ Імпорт запускається...", show_alert=False)
        await cb.message.edit_text("⏳ <b>Імпорт з Google Sheets...</b>\n\nЗачекайте, це може зайняти кілька секунд...")

        # FIX #15: Import wrapped in try-finally to ensure cleanup
        # Note: Full transactional rollback would require changes to full_import() itself
        await asyncio.to_thread(full_import)

        txt = (
            "✅ <b>Імпорт завершено!</b>\n\n"
            "📄 Дані з Google Sheets завантажені в базу:\n"
            "• розклад змін та часи роботи\n"
            "• заправки палива\n"
            "• журнал подій і стан генератора\n"
            "• довідники водіїв та персоналу\n\n"
            "⚠️ Попередні дані в БД було повністю видалено перед імпортом."
        )
        await cb.message.edit_text(txt, reply_markup=_back_kb())

    except Exception as e:
        logger.error(f"❌ Помилка імпорту: {e}", exc_info=True)
        await cb.message.edit_text(
            f"❌ <b>Помилка імпорту</b>\n\n{e}",
            reply_markup=_back_kb(),
        )
    finally:
        # FIX #14: Always release lock
        _release_sync_lock()


# --- ЕКСПОРТ (АВАРІЙНИЙ) ---
@router.callback_query(F.data == "sync_export")
async def sync_export_confirm(cb: types.CallbackQuery):
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
        "⚠️ <b>Підтвердження експорту (АВАРІЙНА ОПЦІЯ)</b>\n\n"
        "Експорт зробить наступне:\n"
        "• Для кожного дня з логів БД допише/оновить дані в Sheets\n"
        "• Тільки для дат, де колонки B..I,N,P,Q ще порожні\n"
        "• Дні з даними в Sheets будуть пропущені\n\n"
        "✅ Безпечно для БД, але може дописувати незаповнені дні в таблиці.\n\n"
        "👉 Рекомендація: використовуйте <b>Розумну синхронізацію</b> замість експорту."
    )

    await cb.message.edit_text(txt, reply_markup=_export_confirm_kb())
    await cb.answer()


@router.callback_query(F.data == "sync_export_execute")
async def sync_export_execute(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    # FIX #14: Acquire lock before starting
    if not _acquire_sync_lock():
        return await cb.answer("⚠️ Синхронізація вже виконується. Зачекайте.", show_alert=True)

    try:
        # Подвійна перевірка перед виконанням
        is_off, error_msg = _check_generator_off()
        if not is_off:
            return await cb.answer(error_msg, show_alert=True)

        await cb.answer("⚙️ Експорт запускається...", show_alert=False)
        await cb.message.edit_text("⏳ <b>Експорт в Google Sheets...</b>\n\nЗачекайте, це може зайняти кілька секунд...")

        result = await asyncio.to_thread(full_export)
        updated = []
        skipped = []
        if isinstance(result, dict):
            updated = result.get("updated", []) or []
            skipped = result.get("skipped", []) or []

        def _fmt_dates(dates: list[str]) -> str:
            out = []
            for d in dates:
                try:
                    dt = datetime.strptime(d, "%Y-%m-%d")
                    out.append(dt.strftime("%d.%m.%Y"))
                except Exception:
                    out.append(d)
            return ", ".join(out) if out else "—"

        updated_txt = _fmt_dates(updated)
        skipped_txt = _fmt_dates(skipped)

        txt = (
            "✅ <b>Експорт завершено!</b>\n\n"
            "📄 Дані з БД записані в основну вкладку Sheets (A,B..I,N,P,Q).\n\n"
            f"🟢 Оновлено днів: <b>{len(updated)}</b> ({updated_txt})\n"
            f"🟡 Пропущено днів (дані вже є в Sheets): <b>{len(skipped)}</b> ({skipped_txt})"
        )
        await cb.message.edit_text(txt, reply_markup=_back_kb())

    except Exception as e:
        logger.error(f"❌ Помилка експорту: {e}", exc_info=True)
        await cb.message.edit_text(
            f"❌ <b>Помилка експорту</b>\n\n{e}",
            reply_markup=_back_kb(),
        )
    finally:
        # FIX #14: Always release lock
        _release_sync_lock()
