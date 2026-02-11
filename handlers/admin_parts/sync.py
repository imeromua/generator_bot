import asyncio
import logging

from aiogram import Router, F, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

import config
import database.db_api as db
from keyboards.builders import sync_menu, back_to_admin
from services.sheets_export import full_export
from services.sheets_import import full_import

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


def _back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="sync_menu")]]
    )


@router.callback_query(F.data == "sync_menu")
async def show_sync_menu(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    txt = (
        "🔄 <b>Обмін з Google Sheets</b>\n\n"
        "📥 <b>Імпорт</b> — читає дані з основної вкладки Sheets і повністю перезаписує БД.\n"
        "📤 <b>Експорт</b> — дописує/оновлює дні з логів БД в основну вкладку Sheets, не чіпаючи дні, де дані вже є.\n\n"
        "⚠️ Імпорт повністю очищає БД перед завантаженням (потрібне підтвердження).\n"
        "⚠️ Ніяких фонових синхронізацій, тільки ручні операції.\n"
    )
    await cb.message.edit_text(txt, reply_markup=sync_menu())
    await cb.answer()


@router.callback_query(F.data == "sync_import")
async def sync_import_confirm(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

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

    await cb.answer("⚙️ Імпорт запускається...", show_alert=False)
    await cb.message.edit_text("⏳ <b>Імпорт з Google Sheets...</b>\n\nЗачекайте, це може зайняти кілька секунд...")

    try:
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


@router.callback_query(F.data == "sync_export")
async def sync_export_confirm(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    txt = (
        "⚠️ <b>Підтвердження експорту</b>\n\n"
        "Експорт зробить наступне:\n"
        "• Для кожного дня з логів БД допише/оновить дані в основній вкладці Sheets,\n"
        "  якщо для цієї дати (B..I,N,P,Q) ще порожні.\n"
        "• Дні, де в Sheets уже є дані в B..I,N,P,Q, будуть пропущені без змін.\n\n"
        "Це безпечно для БД, але може дописувати/оновлювати незаповнені дні в таблиці."
    )

    await cb.message.edit_text(txt, reply_markup=_export_confirm_kb())
    await cb.answer()


@router.callback_query(F.data == "sync_export_execute")
async def sync_export_execute(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    await cb.answer("⚙️ Експорт запускається...", show_alert=False)
    await cb.message.edit_text("⏳ <b>Експорт в Google Sheets...</b>\n\nЗачекайте, це може зайняти кілька секунд...")

    try:
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
