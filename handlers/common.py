from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import database.db_api as db
import config
from keyboards.builders import main_dashboard

router = Router()

class RegForm(StatesGroup):
    name = State()

@router.message(Command("start"))
async def cmd_start(msg: types.Message, state: FSMContext):
    user_id = msg.from_user.id
    # 👇 Цей рядок покаже в консолі, що команда дійшла до бота
    print(f"DEBUG: Отримано /start від {user_id} ({msg.from_user.full_name})")
    
    await state.clear()
    
    user = db.get_user(user_id)
    # Авто-реєстрація адміна
    if user_id in config.ADMIN_IDS and not user:
        name = f"Admin {msg.from_user.first_name}"
        db.register_user(user_id, name)
        user = db.get_user(user_id)

    if not user:
        await msg.answer(
            f"👋 Вітаю! Твій ID: <code>{user_id}</code>\n"
            f"Я тебе ще не знаю.\n"
            f"Будь ласка, напиши своє <b>Прізвище та Ім'я</b>:"
        )
        await state.set_state(RegForm.name)
    else:
        # Показуємо дашборд (common.py потребує функції show_dash, імпортуємо її тут)
        # Або викликаємо локально, якщо вона тут визначена.
        # У попередніх версіях show_dash була тут.
        await show_dash(msg, user_id, user[1])

@router.message(RegForm.name)
async def process_name(msg: types.Message, state: FSMContext):
    db.register_user(msg.from_user.id, msg.text)
    await state.clear()
    await msg.answer(f"✅ Приємно познайомитись, {msg.text}!")
    await show_dash(msg, msg.from_user.id, msg.text)

# Ця функція має бути тут
async def show_dash(msg: types.Message, user_id, user_name):
    st = db.get_state()
    role = 'admin' if user_id in config.ADMIN_IDS else 'manager'
    completed = db.get_today_completed_shifts()
    
    status_icon = "🟢 ПРАЦЮЄ" if st['status']=='ON' else "💤 ВИМКНЕНО"
    to_service = config.MAINTENANCE_LIMIT - (st['total_hours'] - st['last_oil'])
    current_fuel = st['current_fuel']
    hours_left = current_fuel / config.FUEL_CONSUMPTION if config.FUEL_CONSUMPTION > 0 else 0
    
    mode_mark = ""
    import os
    if os.getenv("MODE") == "TEST":
        mode_mark = "🧪 <b>ТЕСТОВИЙ РЕЖИМ</b>\n➖➖➖➖➖➖\n"

    txt = (f"{mode_mark}"
           f"🔋 <b>Генератор:</b> {status_icon}\n"
           f"⛽ Залишок палива: <b>{current_fuel:.1f} л</b>\n"
           f"⏳ Вистачить на: <b>~{hours_left:.1f} год</b>\n\n"
           f"👤 <b>Ви:</b> {user_name}\n"
           f"🛢 До ТО: <b>{to_service:.1f} год</b>")
    
    if st['status'] == 'ON':
        txt += f"\n⏱ Старт був о: {st['start_time']}"

    await msg.answer(txt, reply_markup=main_dashboard(role, st.get('active_shift', 'none'), completed))