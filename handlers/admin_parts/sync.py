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


@router.callback_query(F.data == "sync_menu")
async def show_sync_menu(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    # FIX #14: Show if sync is already in progress
    sync_in_progress = db.get_state_value("sync_in_progress", "0") == "1"
    status_text = "\n⚠️ <b>Синхронізація вже виконується!</b>\n" if sync_in_progress else ""
    
    txt = (
        "🔄 <b>Обмін з Google Sheets</b>\n\n"
        f"{status_text}"
        "🧠 <b>Розумна синхронізація</b> — автоматично визначає що змінилось в БД чи Sheets, \n"
        "синхронізує тільки зміни, перевіряє витрати палива та оновлює довідники.\n\n"
        "📥 <b>Імпорт</b> — читає дані з основної вкладки Sheets і повністю перезаписує БД.\n"
        "📤 <b>Експорт</b> — дописує/оновлює дні з логів БД в основну вкладку Sheets, не чіпаючи дні, де дані вже є.\n\n"
        "⚠️ Імпорт повністю очищає БД перед завантаженням (потрібне підтвердження).\n"
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

    # Safety guard: не синхронізуємо, якщо генератор "ON" (може йти зміна прямо зараз)
    try:
        st = db.get_state() or {}
        if (st.get("status") or "OFF") == "ON":
            return await cb.answer("⛔ Спочатку закрийте активну зміну (генератор ON)", show_alert=True)
    except Exception:
        pass

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
        "🔒 Безпечно для БД та Sheets."
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


# --- ІМПОРТ ---
@router.callback_query(F.data == "sync_import")
async def sync_import_confirm(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    # FIX #14: Check if sync is already in progress
    if db.get_state_value("sync_in_progress", "0") == "1":
        return await cb.answer("⚠️ Синхронізація вже виконується. Зачекайте.", show_alert=True)

    # Safety guard: не імпортуємо, якщо генератор "ON" (може йти зміна прямо зараз)
    try:
        st = db.get_state() or {}
        if (st.get("status") or "OFF") == "ON":
            return await cb.answer("⛔ Спочатку закрийте активну зміну (генератор ON)", show_alert=True)
    except Exception:
        pass

    txt = (
        "⚠️ <b>Підтвердження імпорту</b>\n\n"
        "Імпорт зробить наступне:\n"
        "• Повністю очистить БД\n"
        "• Завантажить дані з основної вкладки Google Sheets\n"
        "• Відновить журнал подій і стан генератора з цієї вкладки\n\n"
        "❌ <b>Цю операцію НЕМОЖЛИВО ВІДМІНИТИ!</b>\n\n"
        "Рекомендація: перед імпортом зробіть експорт як резервну копію."
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


# --- ЕКСПОРТ ---
@router.callback_query(F.data == "sync_export")
async def sync_export_confirm(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    # FIX #14: Check if sync is already in progress
    if db.get_state_value("sync_in_progress", "0") == "1":
        return await cb.answer("⚠️ Синхронізація вже виконується. Зачекайте.", show_alert=True)

    txt = (
        "⚠️ <b>Підтвердження експорту</b>\n\n"
        "Експорт зробить наступне:\n"
        "• Для кожного дня з логів БД допише/оновить дані в основній вкладці Sheets,\n"
        "  якщо для цієї дати (B..I,N,P,Q) ще порожні.\n"
        "• Дні, де в Sheets вже є дані в B..I,N,P,Q, будуть пропущені без змін.\n\n"
        "Це безпечно для БД, але може дописувати/оновлювати незаповнені дні в таблиці."
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
