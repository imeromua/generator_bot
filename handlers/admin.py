from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest
from datetime import datetime, timedelta
import logging
import os
import asyncio

import config
import database.db_api as db
from handlers.admin_parts.export_logs import router as export_logs_router
from handlers.admin_parts.sheet_mode import router as sheet_mode_router
from handlers.admin_parts.utils import (
    ensure_admin_user as _ensure_admin_user,
    actor_name as _actor_name,
    fmt_state_ts as _fmt_state_ts,
)
from keyboards.builders import (
    admin_panel, schedule_grid, report_period,
    back_to_admin, after_add_menu, maintenance_menu, back_to_mnt,
    schedule_date_selector
)
from services.excel_report import generate_report

router = Router()
router.include_router(sheet_mode_router)
router.include_router(export_logs_router)

logger = logging.getLogger(__name__)


class AddDriverForm(StatesGroup):
    name = State()


class SetHoursForm(StatesGroup):
    hours = State()


# --- ВХІД В АДМІНКУ ---
@router.callback_query(F.data == "admin_home")
async def adm_menu(cb: types.CallbackQuery, state: FSMContext):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)
    await state.clear()
    logger.info(f"👤 Адмін {cb.from_user.id} відкрив панель")

    # короткий статус Sheets прямо в хедері адмінки
    sheets_line = ""
    try:
        is_offline = db.sheet_is_offline()
        forced_offline = bool(db.sheet_is_forced_offline())
        if not is_offline:
            last_ok = _fmt_state_ts(db.get_state_value("sheet_last_ok_ts", ""))
            sheets_line = f"Google Sheets: 🌐 <b>ONLINE</b> (останній OK: {last_ok})"
        else:
            offline_since = _fmt_state_ts(db.get_state_value("sheet_offline_since_ts", ""))
            mode = "примусово" if forced_offline else "авто"
            sheets_line = f"Google Sheets: 🔌 <b>OFFLINE</b> ({mode}) з {offline_since}"
    except Exception:
        sheets_line = ""

    txt = "⚙️ <b>Адмін Панель</b>"
    if sheets_line:
        txt += f"\n\n{sheets_line}\n➖➖➖➖➖➖"

    await cb.message.edit_text(txt, reply_markup=admin_panel())


# --- ПАЛИВО: замовлено ---
@router.callback_query(F.data == "fuel_ordered")
async def fuel_ordered(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    now = datetime.now(config.KYIV)
    today_str = now.strftime("%Y-%m-%d")

    db.set_state("fuel_ordered_date", today_str)
    db.set_state("fuel_alert_last_sent_ts", now.strftime("%Y-%m-%d %H:%M:%S"))

    actor = _actor_name(cb.from_user.id, first_name=cb.from_user.first_name)
    try:
        db.add_log("fuel_ordered", actor, ts=now.strftime("%Y-%m-%d %H:%M:%S"))
    except Exception:
        pass

    # Оновлюємо повідомлення (якщо можемо)
    try:
        orig = getattr(cb.message, "html_text", None) or getattr(cb.message, "text", "") or ""
        note = "\n\n✅ <b>Паливо замовлено.</b> Нагадування вимкнено до заправки (поки паливо знову не стане ≥ порогу)."
        new_text = (orig + note).strip() if orig else note.strip()

        # прибираємо кнопку, залишаємо лише "На головну" для зручності
        kb = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="🏠 Дашборд", callback_data="home")]
        ])

        await cb.message.edit_text(new_text, reply_markup=kb)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.warning(f"fuel_ordered edit failed: {e}")
    except Exception as e:
        logger.warning(f"fuel_ordered edit failed: {e}")

    await cb.answer("✅ Прийнято", show_alert=True)


# --- ПЕРСОНАЛ: меню ---
@router.callback_query(F.data == "personnel_menu")
async def personnel_menu(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    users = db.get_all_users_with_personnel()
    if not users:
        return await cb.message.edit_text("👥 Немає користувачів у БД.", reply_markup=admin_panel())

    txt = "👥 <b>Персонал → прив'язка користувачів</b>\n\nОберіть користувача:" \
          "\n<i>(натисніть, щоб призначити ПІБ з колонки 'ПЕРСОНАЛ')</i>"

    kb = []
    for uid, full_name, pers in users[:30]:
        label = f"{full_name}"
        if pers:
            label += f" → ✅ {pers}"
        else:
            label += " → ⚠️ не призначено"
        kb.append([types.InlineKeyboardButton(text=label[:60], callback_data=f"pers_user_{uid}")])

    kb.append([types.InlineKeyboardButton(text="🔙 Назад", callback_data="admin_home")])

    await cb.message.edit_text(txt, reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data.startswith("pers_user_"))
async def personnel_choose_user(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    try:
        uid = int(cb.data.split("_")[-1])
    except Exception:
        return await cb.answer("❌ Помилка ID", show_alert=True)

    user = db.get_user(uid)
    if not user:
        return await cb.answer("❌ Користувача не знайдено", show_alert=True)

    current = db.get_personnel_for_user(uid)
    names = db.get_personnel_names()

    if not names:
        txt = (
            f"👤 <b>{user[1]}</b>\n"
            f"🆔 <code>{uid}</code>\n\n"
            f"Поточна прив'язка: <b>{current or '—'}</b>\n\n"
            f"⚠️ Список персоналу ще не завантажений.\n"
            f"Перевірте, що в таблиці заповнена колонка AC (ПЕРСОНАЛ) і синхронізація працює."
        )
        kb = [[types.InlineKeyboardButton(text="🔙 Назад", callback_data="personnel_menu")]]
        return await cb.message.edit_text(txt, reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb))

    txt = (
        f"👤 <b>{user[1]}</b>\n"
        f"🆔 <code>{uid}</code>\n\n"
        f"Поточна прив'язка: <b>{current or '—'}</b>\n\n"
        f"Оберіть ПІБ (як у колонці 'ПЕРСОНАЛ'):\n"
    )

    kb = []
    for i, name in enumerate(names[:40]):
        kb.append([types.InlineKeyboardButton(text=name, callback_data=f"pers_set_{uid}_{i}")])

    kb.append([types.InlineKeyboardButton(text="🚫 Зняти прив'язку", callback_data=f"pers_clear_{uid}")])
    kb.append([types.InlineKeyboardButton(text="🔙 Назад", callback_data="personnel_menu")])

    await cb.message.edit_text(txt, reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data.startswith("pers_set_"))
async def personnel_set(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    try:
        _, _, uid_s, idx_s = cb.data.split("_", 3)
        uid = int(uid_s)
        idx = int(idx_s)
    except Exception:
        return await cb.answer("❌ Помилка призначення", show_alert=True)

    names = db.get_personnel_names()
    if idx < 0 or idx >= len(names):
        return await cb.answer("⚠️ Список персоналу оновився. Відкрийте ще раз.", show_alert=True)

    db.set_personnel_for_user(uid, names[idx])
    await cb.answer("✅ Призначено", show_alert=True)
    await personnel_choose_user(cb)


@router.callback_query(F.data.startswith("pers_clear_"))
async def personnel_clear(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    try:
        uid = int(cb.data.split("_")[-1])
    except Exception:
        return await cb.answer("❌ Помилка", show_alert=True)

    db.set_personnel_for_user(uid, None)
    await cb.answer("✅ Прив'язку знято", show_alert=True)
    await personnel_choose_user(cb)


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


# --- МЕНЮ ТО ---
@router.callback_query(F.data == "mnt_menu")
async def mnt_view(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    st = db.get_state()
    txt = (f"🛠 <b>Технічне Обслуговування</b>\n\n"
           f"⏱ Загальний пробіг: <b>{st['total_hours']:.1f} год</b>\n"
           f"🛢 Після заміни мастила: <b>{(st['total_hours'] - st['last_oil']):.1f} год</b>\n"
           f"🕯 Після заміни свічок: <b>{(st['total_hours'] - st['last_spark']):.1f} год</b>")

    try:
        await cb.message.edit_text(txt, reply_markup=maintenance_menu())
    except TelegramBadRequest:
        await cb.answer()


@router.callback_query(F.data == "mnt_oil")
async def mnt_oil(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    user = _ensure_admin_user(cb.from_user.id, first_name=cb.from_user.first_name)
    actor = (user[1] if user and user[1] else _actor_name(cb.from_user.id, first_name=cb.from_user.first_name))

    db.record_maintenance("oil", actor)
    logger.info(f"🛢 {actor} виконав заміну мастила")
    await cb.answer("✅ Мастило замінено!", show_alert=True)
    await mnt_view(cb)


@router.callback_query(F.data == "mnt_spark")
async def mnt_spark(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    user = _ensure_admin_user(cb.from_user.id, first_name=cb.from_user.first_name)
    actor = (user[1] if user and user[1] else _actor_name(cb.from_user.id, first_name=cb.from_user.first_name))

    db.record_maintenance("spark", actor)
    logger.info(f"🕯 {actor} виконав заміну свічок")
    await cb.answer("✅ Свічки замінено!", show_alert=True)
    await mnt_view(cb)


@router.callback_query(F.data == "mnt_set_hours")
async def ask_hours(cb: types.CallbackQuery, state: FSMContext):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    st = db.get_state()
    await cb.message.edit_text(f"⏱ Поточний: <b>{st['total_hours']:.1f}</b>\nВведіть нове:", reply_markup=back_to_mnt())
    await state.set_state(SetHoursForm.hours)


@router.message(SetHoursForm.hours)
async def save_hours(msg: types.Message, state: FSMContext):
    if msg.from_user.id not in config.ADMIN_IDS:
        await state.clear()
        return await msg.answer("⛔ Тільки для адмінів")

    try:
        val_text = msg.text.replace(",", ".").strip()
        val = float(val_text)

        if val < 0:
            return await msg.answer("❌ Значення не може бути від'ємним", reply_markup=back_to_mnt())

        if val > 100000:
            return await msg.answer("❌ Значення занадто велике (максимум 100000)", reply_markup=back_to_mnt())

        db.set_total_hours(val)
        actor = _actor_name(msg.from_user.id, first_name=msg.from_user.first_name)
        logger.info(f"⏱ {actor} встановив мотогодини: {val}")
        await msg.answer(f"✅ Встановлено: <b>{val} год</b>")

        st = db.get_state()
        txt = (f"🛠 <b>Технічне Обслуговування</b>\n\n"
               f"⏱ Загальний пробіг: <b>{st['total_hours']:.1f} год</b>\n"
               f"🛢 Після заміни мастила: <b>{(st['total_hours'] - st['last_oil']):.1f} год</b>\n"
               f"🕯 Після заміни свічок: <b>{(st['total_hours'] - st['last_spark']):.1f} год</b>")

        await msg.answer(txt, reply_markup=maintenance_menu())
        await state.clear()
    except ValueError:
        await msg.answer("❌ Введіть число (наприклад 100.5)", reply_markup=back_to_mnt())


# --- ЗВІТИ ---
@router.callback_query(F.data == "download_report")
async def report_ask(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    await cb.message.edit_text("📊 Період:", reply_markup=report_period())


@router.callback_query(F.data.in_({"rep_current", "rep_prev"}))
async def report_gen(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    try:
        await cb.message.edit_text("⏳ Генерую звіт, зачекайте...")
        period = "current" if cb.data == "rep_current" else "prev"

        file_path, caption = await generate_report(period)

        if not file_path:
            await cb.message.edit_text(caption, reply_markup=admin_panel())
            return

        file = types.FSInputFile(file_path)

        nav_kb = types.InlineKeyboardMarkup(inline_keyboard=[
            [
                types.InlineKeyboardButton(text="⚙️ Адмін панель", callback_data="admin_home"),
                types.InlineKeyboardButton(text="🏠 Головне меню", callback_data="home"),
            ]
        ])

        await cb.message.answer_document(file, caption=caption, reply_markup=nav_kb)

        os.remove(file_path)
        logger.info(f"📊 Звіт згенеровано: {period}")

        await cb.message.delete()
        await cb.answer("✅ Звіт готовий!")

    except Exception as e:
        logger.error(f"Помилка генерації звіту: {e}", exc_info=True)
        await cb.message.edit_text(f"❌ Помилка генерації звіту: {str(e)}", reply_markup=admin_panel())


# --- ЮЗЕРИ ---
@router.callback_query(F.data == "users_list")
async def users_view(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    users = db.get_all_users()
    txt = "👥 <b>Користувачі в БД:</b>\n\n"

    if not users:
        txt += "<i>Поки немає зареєстрованих користувачів</i>"
    else:
        for uid, name in users:
            txt += f"👤 {name}\n🆔 <code>{uid}</code>\n\n"
        txt += "<i>Натисніть на ID, щоб скопіювати.</i>"

    kb = types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="🔙 Назад", callback_data="admin_home")]])
    await cb.message.edit_text(txt, reply_markup=kb)


# --- ВОДІЇ ---
@router.callback_query(F.data == "add_driver_start")
async def drv_add(cb: types.CallbackQuery, state: FSMContext):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    await cb.message.edit_text("✍️ Введіть прізвище водія:", reply_markup=back_to_admin())
    await state.set_state(AddDriverForm.name)


@router.message(AddDriverForm.name)
async def drv_save(msg: types.Message, state: FSMContext):
    if msg.from_user.id not in config.ADMIN_IDS:
        await state.clear()
        return await msg.answer("⛔ Тільки для адмінів")

    driver_name = msg.text.strip()

    if not driver_name:
        return await msg.answer("❌ Ім'я не може бути порожнім", reply_markup=back_to_admin())

    if len(driver_name) > 50:
        return await msg.answer("❌ Ім'я занадто довге (максимум 50 символів)", reply_markup=back_to_admin())

    success = db.add_driver(driver_name)

    actor = _actor_name(msg.from_user.id, first_name=msg.from_user.first_name)

    if success:
        logger.info(f"🚛 {actor} додав водія: {driver_name}")
        await msg.answer(f"✅ {driver_name} доданий.", reply_markup=after_add_menu())
    else:
        await msg.answer(f"⚠️ Водій {driver_name} вже існує.", reply_markup=after_add_menu())

    await state.clear()
