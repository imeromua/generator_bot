import asyncio
import logging
from aiogram import Bot, Dispatcher, Router, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.client.session.aiohttp import AiohttpSession # 👈 Додано для фікса тайм-ауту
from datetime import datetime

# Імпорти наших модулів
import config
import database.models as db_models
import database.db_api as db
from middlewares.auth import AuthMiddleware

# Імпорт хендлерів (обробників)
from handlers import common, user, admin

# Імпорт сервісів
from services.google_sync import sync_loop
from services.scheduler import scheduler_loop
from services.parser import parse_dtek_message

# Налаштування логування
logging.basicConfig(level=logging.INFO)

# --- 1. НАЛАШТУВАННЯ СЕСІЇ (ФІКС ВИЛЬОТІВ) ---
session = AiohttpSession(timeout=60)

# Ініціалізація бота з сесією
bot = Bot(
    token=config.BOT_TOKEN, 
    session=session, 
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

# --- ЛОГІКА ПАРСЕРА ДТЕК (Повернено на місце) ---
parser_router = Router()

@parser_router.message(F.text & ~F.text.startswith("/"))
async def check_dtek_post(msg: types.Message):
    """Перевіряє кожен текст: чи це графік?"""
    # Аналізуємо текст
    ranges = parse_dtek_message(msg.text)
    
    if ranges:
        txt = "🕵️‍♂️ <b>Знайдено графік для 3.2:</b>\n"
        kb = []
        for s, e in ranges:
            txt += f"🔴 {s} - {e}\n"
            # Кнопка для застосування конкретного діапазону
            kb.append([InlineKeyboardButton(text=f"Застосувати {s}-{e}", callback_data=f"apply_{s}_{e}")])
        
        kb.append([InlineKeyboardButton(text="❌ Скасувати", callback_data="home")])
        
        await msg.reply(txt, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@parser_router.callback_query(F.data.startswith("apply_"))
async def apply_schedule_range(cb: types.CallbackQuery):
    """Записує знайдений графік у БД"""
    try:
        # data = apply_08:00_12:00
        parts = cb.data.split("_")
        s_str, e_str = parts[1], parts[2]
        
        # Конвертуємо "08:00" -> 8 (година)
        s_h = int(s_str.split(":")[0])
        e_h = int(e_str.split(":")[0])
        
        # Обробка переходу через добу (00:00 = 24)
        if e_h == 0: e_h = 24
        
        date_str = datetime.now(config.KYIV).strftime("%Y-%m-%d")
        
        # Запис в БД
        db.set_schedule_range(date_str, s_h, e_h)
        
        await cb.message.edit_text(f"✅ <b>Графік оновлено!</b>\n🔴 {s_str} - {e_str} встановлено як відключення.")
        await cb.answer()
        
    except Exception as e:
        logging.error(f"Parser Error: {e}")
        await cb.answer("❌ Помилка обробки", show_alert=True)


async def main():
    # 1. Ініціалізація БД
    db_models.init_db()
    
    # 2. Підключення Middleware (Охорона)
    dp.message.outer_middleware(AuthMiddleware())
    dp.callback_query.outer_middleware(AuthMiddleware())
    
    # 3. Реєстрація роутерів
    dp.include_router(common.router)   # Старт, Реєстрація
    dp.include_router(admin.router)    # Адмінка
    dp.include_router(user.router)     # Кнопки генератора
    dp.include_router(parser_router)   # Парсер тексту (ТУТ ВІН Є)
    
    # 4. Запуск фонових процесів
    asyncio.create_task(sync_loop())         
    asyncio.create_task(scheduler_loop(bot)) 
    
    print("🚀 БОТ ЗАПУЩЕНО! Натисніть Ctrl+C для зупинки.")

    # 5. Безпечне видалення вебхука
    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        logging.warning(f"⚠️ Помилка очищення webhook (ігноруємо): {e}")

    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("🛑 Бот зупинений.")