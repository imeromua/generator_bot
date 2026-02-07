import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Router, F, types
from aiogram.exceptions import TelegramBadRequest

import config
import database.db_api as db
from keyboards.builders import schedule_date_selector, schedule_grid

router = Router()
logger = logging.getLogger(__name__)


# --- 1. ГРАФІК: ВИБІР ДАТИ ---
@router.callback_query(F.data == "sched_select_date")
async def sched_select(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    now = datetime.now(config.KYIV)

    today_str = now.strftime("%Y-%m-%d")
    tom_str = (now + timedelta(days=1)).strftime("%Y-%m-%d")

    try:
        end_time_limit = datetime.strptime(config.WORK_END_TIME, "%H:%M").time()
        is_evening = now.time() > end_time_limit
    except ValueError:
        logger.error(f"Неправильний формат WORK_END_TIME: {config.WORK_END_TIME}")
        is_evening = False

    hint = "🌙 Вже вечір, заповнюємо на <b>ЗАВТРА</b>?" if is_evening else "☀️ День, редагуємо <b>СЬОГОДНІ</b>?"

    await cb.message.edit_text(
        f"📅 <b>Налаштування графіка</b>\n{hint}",
        reply_markup=schedule_date_selector(today_str, tom_str)
    )


# --- 2. ГРАФІК: СІТКА ---
@router.callback_query(F.data.startswith("sched_edit_"))
async def sched_edit(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    try:
        date_str = cb.data.split("_")[2]
        pretty_date = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d-%m-%Y")
    except (IndexError, ValueError) as e:
        logger.error(f"Помилка парсингу дати: {e}")
        return await cb.answer("❌ Неправильний формат дати", show_alert=True)

    now = datetime.now(config.KYIV)
    today_iso = now.strftime("%Y-%m-%d")

    try:
        start_t = datetime.strptime(config.WORK_START_TIME, "%H:%M").time()
    except ValueError:
        logger.error(f"Неправильний формат WORK_START_TIME: {config.WORK_START_TIME}")
        start_t = datetime.strptime("07:30", "%H:%M").time()

    is_hot_edit = False
    if date_str == today_iso and now.time() > start_t:
        is_hot_edit = True

    txt = f"📅 Графік на <b>{pretty_date}</b>\n(🔴 - немає світла)\n"
    if is_hot_edit:
        txt += "\n⚠️ <i>Ви змінюєте графік поточного дня. Не забудьте натиснути 'Сповістити'!</i>"

    try:
        await cb.message.edit_text(txt, reply_markup=schedule_grid(date_str, is_hot_edit))
    except TelegramBadRequest as e:
        # нормальна ситуація при повторному натисканні тієї ж кнопки
        if "message is not modified" not in str(e).lower():
            logger.warning(f"TelegramBadRequest при редагуванні графіка: {e}")

    await cb.answer()


# --- 3. ГРАФІК: КЛІКЕР ---
@router.callback_query(F.data.startswith("tog_"))
async def tog_hour(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    try:
        _, date_str, hour = cb.data.split("_")
        db.toggle_schedule(date_str, int(hour))

        now = datetime.now(config.KYIV)
        today_iso = now.strftime("%Y-%m-%d")
        start_t = datetime.strptime(config.WORK_START_TIME, "%H:%M").time()
        is_hot_edit = (date_str == today_iso and now.time() > start_t)

        try:
            await cb.message.edit_reply_markup(reply_markup=schedule_grid(date_str, is_hot_edit))
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e).lower():
                raise

        await cb.answer()
    except Exception as e:
        logger.error(f"Помилка toggle графіка: {e}")
        await cb.answer("❌ Помилка", show_alert=True)


# --- 4. ГРАФІК: СПОВІЩЕННЯ ---
@router.callback_query(F.data.startswith("sched_notify_"))
async def sched_notify(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    try:
        date_str = cb.data.split("_")[2]
        sched = db.get_schedule(date_str)
        pretty_date = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d-%m-%Y")
    except Exception as e:
        logger.error(f"Помилка отримання графіка: {e}")
        return await cb.answer("❌ Помилка отримання графіка", show_alert=True)

    txt = f"⚡ <b>УВАГА! ЗМІНА ГРАФІКА ({pretty_date})</b>\n\n"
    for h in range(8, 22):
        icon = "🔴" if sched.get(h) == 1 else "🟢"
        txt += f"{h:02}:00 {icon}  "
        if h == 14:
            txt += "\n"
    txt += "\n\n🔴 - Відключення\n🟢 - Світло є"

    users = db.get_all_users()
    count = 0
    fail_count = 0

    for uid, uname in users:
        try:
            await cb.bot.send_message(uid, txt)
            count += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.warning(f"Не вдалося надіслати {uname} (ID: {uid}): {e}")
            fail_count += 1

    logger.info(f"📢 Розсилка графіка: {count} успішно, {fail_count} помилок")
    await cb.answer(f"✅ Надіслано {count} користувачам", show_alert=True)
    await sched_edit(cb)
