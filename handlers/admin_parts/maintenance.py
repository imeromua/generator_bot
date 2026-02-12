import logging
from datetime import datetime

from aiogram import Router, F, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

import config
import database.db_api as db
from handlers.admin_parts.utils import ensure_admin_user, actor_name
from keyboards.builders import maintenance_menu_new, maintenance_action_menu, back_to_mnt, back_to_admin

router = Router()
logger = logging.getLogger(__name__)


class SetHoursForm(StatesGroup):
    generator = State()  # Який генератор
    hours = State()  # Значення мотогодин
    message_id = State()  # ID повідомлення для редагування


class MaintenanceForm(StatesGroup):
    generator = State()  # Який генератор
    action = State()  # Тип ТО


def format_mnt_status(generator_id: str) -> str:
    """Форматує статус ТО для генератора."""
    stats = db.get_maintenance_stats(generator_id)
    gen_name = db.get_generator_name(generator_id)  # Вже містить емодзі!
    
    # Форматування з попередженнями
    def fmt_line(name: str, icon: str, current: float, needed: float, interval: int) -> str:
        if needed <= 0:
            status = "🔴 ТЕРМІНОВЕ ТО!"
        elif needed <= 10:
            status = f"⚠️ Залишилось {needed:.1f} год"
        else:
            status = f"✅ Залишилось {needed:.1f} год"
        return f"├─ {icon} {name}: {current:.1f} год → {status}"
    
    oil_line = fmt_line("Масло", "🛢", stats['last_oil'], stats['oil_needed'], config.OIL_CHANGE_INTERVAL)
    spark_line = fmt_line("Свічки", "🕯", stats['last_spark'], stats['spark_needed'], config.SPARK_CHANGE_INTERVAL)
    mnt_line = fmt_line("Планове ТО", "🔧", stats['total_hours'] % config.MAINTENANCE_INTERVAL, stats['maintenance_needed'], config.MAINTENANCE_INTERVAL)
    
    return (
        f"<b>{gen_name}</b>:\n"  # gen_name вже має емодзі
        f"⏱ Загальний пробіг: <b>{stats['total_hours']:.1f} год</b>\n"
        f"{oil_line}\n"
        f"{spark_line}\n"
        f"{mnt_line.replace('├', '└')}"
    )


# --- ГОЛОВНЕ МЕНЮ ТО ---
@router.callback_query(F.data == "mnt_menu")
async def mnt_view(cb: types.CallbackQuery, state: FSMContext):
    """Головне меню технічного обслуговування."""
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)
    
    await state.clear()
    
    # Формуємо статус обох генераторів
    main_status = format_mnt_status("main")
    emergency_status = format_mnt_status("emergency")
    
    txt = (
        f"🛠 <b>Технічне Обслуговування</b>\n\n"
        f"{main_status}\n\n"
        f"{emergency_status}"
    )
    
    # Перевіряємо чи є термінове ТО
    main_next = db.get_next_maintenance_type("main")
    emerg_next = db.get_next_maintenance_type("emergency")
    
    if main_next[0] and main_next[1] <= 10:
        txt += f"\n\n⚠️ <b>УВАГА!</b> Основний генератор потребує ТО!"
    if emerg_next[0] and emerg_next[1] <= 10:
        txt += f"\n\n⚠️ <b>УВАГА!</b> Аварійний генератор потребує ТО!"
    
    try:
        await cb.message.edit_text(txt, reply_markup=maintenance_menu_new())
    except TelegramBadRequest:
        await cb.answer()


# --- ВИКОНАТИ ТО ---
@router.callback_query(F.data == "mnt_perform")
async def mnt_choose_generator(cb: types.CallbackQuery, state: FSMContext):
    """Вибір генератора для виконання ТО."""
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)
    
    kb = [
        [types.InlineKeyboardButton(text="🔋 Основний генератор", callback_data="mnt_gen_main")],
        [types.InlineKeyboardButton(text="⚠️ Аварійний генератор", callback_data="mnt_gen_emergency")],
        [types.InlineKeyboardButton(text="🔙 Назад", callback_data="mnt_menu")],
    ]
    markup = types.InlineKeyboardMarkup(inline_keyboard=kb)
    
    await cb.message.edit_text(
        "🛠 <b>Виконання ТО</b>\n\nОберіть генератор:",
        reply_markup=markup
    )
    await state.set_state(MaintenanceForm.generator)


@router.callback_query(MaintenanceForm.generator, F.data.startswith("mnt_gen_"))
async def mnt_choose_action(cb: types.CallbackQuery, state: FSMContext):
    """Вибір типу ТО."""
    generator_id = cb.data.replace("mnt_gen_", "")
    await state.update_data(generator=generator_id)
    
    gen_name = db.get_generator_name(generator_id)
    stats = db.get_maintenance_stats(generator_id)
    
    kb = [
        [types.InlineKeyboardButton(text=f"🛢 Заміна мастила (↻ {stats['last_oil']:.1f} год)", callback_data="mnt_action_oil")],
        [types.InlineKeyboardButton(text=f"🕯 Заміна свічок (↻ {stats['last_spark']:.1f} год)", callback_data="mnt_action_spark")],
        [types.InlineKeyboardButton(text="🔧 Планове ТО (масло + свічки)", callback_data="mnt_action_maintenance")],
        [types.InlineKeyboardButton(text="🔙 Назад", callback_data="mnt_perform")],
    ]
    markup = types.InlineKeyboardMarkup(inline_keyboard=kb)
    
    await cb.message.edit_text(
        f"🛠 <b>Виконання ТО: {gen_name}</b>\n\n"
        f"⏱ Загальний пробіг: <b>{stats['total_hours']:.1f} год</b>\n\n"
        f"Оберіть тип ТО:",
        reply_markup=markup
    )
    await state.set_state(MaintenanceForm.action)


@router.callback_query(MaintenanceForm.action, F.data.startswith("mnt_action_"))
async def mnt_confirm_action(cb: types.CallbackQuery, state: FSMContext):
    """Підтвердження виконання ТО."""
    action = cb.data.replace("mnt_action_", "")
    data = await state.get_data()
    generator_id = data.get("generator", "main")
    
    user = ensure_admin_user(cb.from_user.id, first_name=cb.from_user.first_name)
    actor = (user[1] if user and user[1] else actor_name(cb.from_user.id, first_name=cb.from_user.first_name))
    
    # Записуємо ТО
    db.record_maintenance(action, actor, generator_id)
    
    gen_name = db.get_generator_name(generator_id)
    action_names = {
        "oil": "🛢 Заміна мастила",
        "spark": "🕯 Заміна свічок",
        "maintenance": "🔧 Планове ТО",
    }
    action_name = action_names.get(action, action)
    
    logger.info(f"🛠 {actor} виконав {action_name} для {gen_name}")
    
    await cb.answer(f"✅ {action_name} виконано!", show_alert=True)
    await state.clear()
    await mnt_view(cb, state)


# --- ІСТОРІЯ ТО ---
@router.callback_query(F.data == "mnt_history")
async def mnt_history_menu(cb: types.CallbackQuery):
    """Вибір генератора для перегляду історії."""
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)
    
    kb = [
        [types.InlineKeyboardButton(text="🔋 Основний генератор", callback_data="mnt_hist_main")],
        [types.InlineKeyboardButton(text="⚠️ Аварійний генератор", callback_data="mnt_hist_emergency")],
        [types.InlineKeyboardButton(text="📊 Всі генератори", callback_data="mnt_hist_all")],
        [types.InlineKeyboardButton(text="🔙 Назад", callback_data="mnt_menu")],
    ]
    markup = types.InlineKeyboardMarkup(inline_keyboard=kb)
    
    await cb.message.edit_text(
        "📜 <b>Історія ТО</b>\n\nОберіть генератор:",
        reply_markup=markup
    )


@router.callback_query(F.data.startswith("mnt_hist_"))
async def mnt_show_history(cb: types.CallbackQuery):
    """Відображення історії ТО."""
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)
    
    generator_filter = cb.data.replace("mnt_hist_", "")
    generator_id = None if generator_filter == "all" else generator_filter
    
    history = db.get_maintenance_history(generator_id, limit=20)
    
    if not history:
        txt = "📜 <b>Історія ТО</b>\n\nІсторія порожня."
    else:
        action_names = {
            "oil": "🛢 Масло",
            "spark": "🕯 Свічки",
            "maintenance": "🔧 Планове ТО",
        }
        
        lines = []
        for record in history:
            # record: (id, date, type, hours, admin, generator_id)
            rec_id, date_str, action, hours, admin, gen_id = record
            gen_icon = "🔋" if gen_id == "main" else "⚠️"
            action_name = action_names.get(action, action)
            
            # Форматуємо дату
            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
                date_fmt = dt.strftime("%d.%m.%Y %H:%M")
            except Exception:
                date_fmt = date_str
            
            lines.append(f"{gen_icon} {action_name} • {hours:.1f} год • {date_fmt}\n   👤 {admin}")
        
        txt = f"📜 <b>Історія ТО</b> (останні {len(history)} записів)\n\n" + "\n\n".join(lines)
    
    kb = [[types.InlineKeyboardButton(text="🔙 Назад", callback_data="mnt_history")]]
    markup = types.InlineKeyboardMarkup(inline_keyboard=kb)
    
    await cb.message.edit_text(txt, reply_markup=markup)


# --- КОРЕКЦІЯ МОТОГОДИН ---
@router.callback_query(F.data == "mnt_set_hours")
async def mnt_hours_choose_gen(cb: types.CallbackQuery, state: FSMContext):
    """Вибір генератора для корекції мотогодин."""
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)
    
    main_stats = db.get_maintenance_stats("main")
    emerg_stats = db.get_maintenance_stats("emergency")
    
    kb = [
        [types.InlineKeyboardButton(
            text=f"🔋 Основний ({main_stats['total_hours']:.1f} год)",
            callback_data="mnt_hours_main"
        )],
        [types.InlineKeyboardButton(
            text=f"⚠️ Аварійний ({emerg_stats['total_hours']:.1f} год)",
            callback_data="mnt_hours_emergency"
        )],
        [types.InlineKeyboardButton(text="🔙 Назад", callback_data="mnt_menu")],
    ]
    markup = types.InlineKeyboardMarkup(inline_keyboard=kb)
    
    await cb.message.edit_text(
        "⏱ <b>Корекція мотогодин</b>\n\nОберіть генератор:",
        reply_markup=markup
    )
    await state.set_state(SetHoursForm.generator)


@router.callback_query(SetHoursForm.generator, F.data.startswith("mnt_hours_"))
async def ask_hours(cb: types.CallbackQuery, state: FSMContext):
    """Запит нового значення мотогодин."""
    generator_id = cb.data.replace("mnt_hours_", "")
    await state.update_data(generator=generator_id, message_id=cb.message.message_id)
    
    gen_name = db.get_generator_name(generator_id)
    stats = db.get_maintenance_stats(generator_id)
    
    await cb.message.edit_text(
        f"⏱ <b>Корекція мотогодин: {gen_name}</b>\n\n"
        f"Поточне значення: <b>{stats['total_hours']:.1f} год</b>\n\n"
        f"Введіть нове значення:",
        reply_markup=back_to_mnt()
    )
    await state.set_state(SetHoursForm.hours)


@router.message(SetHoursForm.hours)
async def save_hours(msg: types.Message, state: FSMContext):
    """Збереження нового значення мотогодин."""
    if msg.from_user.id not in config.ADMIN_IDS:
        await state.clear()
        return await msg.answer("⛔ Тільки для адмінів")
    
    data = await state.get_data()
    bot_message_id = data.get("message_id")
    generator_id = data.get("generator", "main")
    gen_name = db.get_generator_name(generator_id)
    stats = db.get_maintenance_stats(generator_id)
    
    try:
        val_text = msg.text.replace(",", ".").strip()
        val = float(val_text)
        
        # Валідація
        if val < 0:
            await msg.delete()
            try:
                await msg.bot.edit_message_text(
                    chat_id=msg.chat.id,
                    message_id=bot_message_id,
                    text=(
                        f"⏱ <b>Корекція мотогодин: {gen_name}</b>\n\n"
                        f"Поточне значення: <b>{stats['total_hours']:.1f} год</b>\n\n"
                        f"❌ <b>Помилка:</b> Значення не може бути від'ємним\n\n"
                        f"Введіть нове значення:"
                    ),
                    reply_markup=back_to_mnt()
                )
            except Exception:
                pass
            return
        
        if val > 100000:
            await msg.delete()
            try:
                await msg.bot.edit_message_text(
                    chat_id=msg.chat.id,
                    message_id=bot_message_id,
                    text=(
                        f"⏱ <b>Корекція мотогодин: {gen_name}</b>\n\n"
                        f"Поточне значення: <b>{stats['total_hours']:.1f} год</b>\n\n"
                        f"❌ <b>Помилка:</b> Значення занадто велике (максимум 100000)\n\n"
                        f"Введіть нове значення:"
                    ),
                    reply_markup=back_to_mnt()
                )
            except Exception:
                pass
            return
        
        # Збереження
        db.set_total_hours(val, generator_id)
        
        actor = actor_name(msg.from_user.id, first_name=msg.from_user.first_name)
        logger.info(f"⏱ {actor} встановив мотогодини для {gen_name}: {val}")
        
        # Видаляємо повідомлення користувача
        await msg.delete()
        
        # Оновлюємо повідомлення бота з меню ТО
        main_status = format_mnt_status("main")
        emergency_status = format_mnt_status("emergency")
        
        txt = (
            f"✅ <b>Встановлено для {gen_name}: {val} год</b>\n"
            f"────────\n\n"
            f"🛠 <b>Технічне Обслуговування</b>\n\n"
            f"{main_status}\n\n"
            f"{emergency_status}"
        )
        
        try:
            await msg.bot.edit_message_text(
                chat_id=msg.chat.id,
                message_id=bot_message_id,
                text=txt,
                reply_markup=maintenance_menu_new()
            )
        except TelegramBadRequest:
            # Якщо не вдалося відредагувати, відправляємо нове
            await msg.answer(txt, reply_markup=maintenance_menu_new())
        
        await state.clear()
        
    except ValueError:
        # Неправильний формат
        await msg.delete()
        try:
            await msg.bot.edit_message_text(
                chat_id=msg.chat.id,
                message_id=bot_message_id,
                text=(
                    f"⏱ <b>Корекція мотогодин: {gen_name}</b>\n\n"
                    f"Поточне значення: <b>{stats['total_hours']:.1f} год</b>\n\n"
                    f"❌ <b>Помилка:</b> Введіть число (наприклад 100.5)\n\n"
                    f"Введіть нове значення:"
                ),
                reply_markup=back_to_mnt()
            )
        except Exception:
            pass
