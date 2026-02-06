import asyncio
import logging
from aiogram import Bot, Dispatcher, Router, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import StateFilter
from datetime import datetime
import sys

# Імпорти наших модулів
import config
import database.models as db_models
import database.db_api as db
from middlewares.auth import WhitelistMiddleware
from middlewares.error_handler import ErrorHandlerMiddleware, global_error_handler

# Імпорт хендлерів
from handlers import common, user, admin

# Імпорт сервісів
from services.google_sync import sync_loop
from services.scheduler import scheduler_loop
from services.parser import parse_dtek_message

# Налаштування логування
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- ЛОГІКА ПАРСЕРА ДТЕК ---
parser_router = Router()

@parser_router.message(F.text & ~F.text.startswith("/"), StateFilter(None))
async def check_dtek_post(msg: types.Message):
    """Перевіряє кожен текст: чи це графік?"""
    ranges = parse_dtek_message(msg.text)
    
    if ranges:
        txt = "🕵️‍♂️ <b>Знайдено графік для 3.2:</b>\n"
        kb = []
        for s, e in ranges:
            txt += f"🔴 {s} - {e}\n"
            kb.append([InlineKeyboardButton(text=f"Застосувати {s}-{e}", callback_data=f"apply_{s}_{e}")])
        
        kb.append([InlineKeyboardButton(text="❌ Скасувати", callback_data="home")])
        await msg.reply(txt, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@parser_router.callback_query(F.data.startswith("apply_"))
async def apply_schedule_range(cb: types.CallbackQuery):
    """Записує знайдений графік у БД"""
    try:
        parts = cb.data.split("_")
        s_str, e_str = parts[1], parts[2]
        
        s_h = int(s_str.split(":")[0])
        e_h = int(e_str.split(":")[0])
        
        if e_h == 0:
            e_h = 24
        
        date_str = datetime.now(config.KYIV).strftime("%Y-%m-%d")
        db.set_schedule_range(date_str, s_h, e_h)
        
        await cb.message.edit_text(f"✅ <b>Графік оновлено!</b>\n🔴 {s_str} - {e_str}")
        await cb.answer()
        
    except Exception as e:
        logger.error(f"Parser Error: {e}")
        await cb.answer("❌ Помилка обробки", show_alert=True)


async def main():
    bot = None
    
    try:
        # 1. База даних
        logger.info("🔧 Ініціалізація бази даних...")
        db_models.init_db()
        
        # 2. Створення бота
        bot = Bot(
            token=config.BOT_TOKEN,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML)
        )
        
        # 3. Створення диспетчера
        dp = Dispatcher()
        
        # 4. Підключення Error Handler (ПЕРШИЙ!)
        logger.info("🛡 Підключення error handler...")
        dp.errors.register(global_error_handler)
        
        # 5. Підключення Middleware
        logger.info("🛡 Підключення middleware...")
        dp.update.outer_middleware(ErrorHandlerMiddleware())  # Перехоплювач помилок
        dp.message.outer_middleware(WhitelistMiddleware())    # Білий список
        dp.callback_query.outer_middleware(WhitelistMiddleware())
        
        # 6. Реєстрація роутерів
        logger.info("📋 Реєстрація роутерів...")
        dp.include_router(common.router)
        dp.include_router(admin.router)
        dp.include_router(user.router)
        dp.include_router(parser_router)
        
        # 7. Запуск фонових процесів
        logger.info("🚀 Запуск фонових процесів...")
        asyncio.create_task(sync_loop())
        asyncio.create_task(scheduler_loop(bot))
        
        logger.info("=" * 50)
        logger.info("🚀 БОТ ЗАПУЩЕНО!")
        logger.info(f"📅 Режим: {'TEST' if config.IS_TEST_MODE else 'PROD'}")
        logger.info(f"📊 Таблиця: {config.SHEET_NAME}")
        logger.info(f"👥 Адмінів: {len(config.ADMIN_IDS)}")
        logger.info(f"🔓 Реєстрація: {'Відкрита' if config.REGISTRATION_OPEN else 'Закрита'}")
        logger.info("=" * 50)
        logger.info("Натисніть Ctrl+C для зупинки.")
        
        # 8. Очищення webhook
        try:
            await bot.delete_webhook(drop_pending_updates=True)
            logger.info("✅ Webhook очищено")
        except Exception as e:
            logger.warning(f"⚠️ Помилка очищення webhook (ігноруємо): {e}")
        
        # 9. Запуск polling
        await dp.start_polling(bot)
        
    except KeyboardInterrupt:
        logger.info("🛑 Отримано сигнал зупинки...")
    except Exception as e:
        logger.error(f"❌ Критична помилка при запуску: {e}", exc_info=True)
        raise
    finally:
        if bot:
            try:
                await bot.session.close()
                logger.info("✅ Сесія закрита")
            except:
                pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Бот зупинений користувачем.")
    except Exception as e:
        logger.error(f"💥 Фатальна помилка: {e}", exc_info=True)
        sys.exit(1)
