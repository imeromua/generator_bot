import asyncio
import logging
import random
import sys
from datetime import datetime

import aiohttp
from aiogram import Bot, Dispatcher, Router, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramNetworkError
from aiogram.filters import StateFilter
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# Налаштування логування (має бути якомога раніше)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Імпорти наших модулів
import config

# Критичні змінні перевіряємо в точці входу, а не під час імпорту config
config.validate_env()

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


# --- ЛОГІКА ПАРСЕРА ДТЕК ---
parser_router = Router()


@parser_router.message(F.text & ~F.text.startswith("/"), StateFilter(None))
async def check_dtek_post(msg: types.Message):
    """Перевіряє кожен текст: чи це графік? (тільки для адмінів)"""
    if msg.from_user.id not in config.ADMIN_IDS:
        return

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
    """Записує знайдений графік у БД (тільки для адмінів)"""
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

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
        logger.error(f"Parser Error: {e}", exc_info=True)
        await cb.answer("❌ Помилка обробки", show_alert=True)


def _is_transient_network_error(exc: Exception) -> bool:
    """
    Визначаємо "тимчасові" помилки, при яких треба робити retry/restart.
    Покриває ситуації на кшталт:
      - TelegramNetworkError (aiogram)
      - aiohttp ClientConnectorError (Cannot connect to host api.telegram.org:443 ...)
      - TimeoutError / asyncio.TimeoutError
      - OSError на Windows типу WinError 121 (semaphore timeout)
    """
    if isinstance(exc, TelegramNetworkError):
        return True

    if isinstance(exc, (aiohttp.ClientConnectorError, aiohttp.ClientOSError)):
        return True

    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return True

    if isinstance(exc, OSError):
        return True

    msg = str(exc).lower()
    if "cannot connect to host" in msg:
        return True
    if "semaphore timeout" in msg:
        return True
    if "превышен таймаут семафора" in msg:
        return True

    return False


async def _sleep_with_jitter(base_seconds: int, jitter_seconds: int = 3):
    """Сон з невеликим випадковим джитером, щоб уникати "бурстів" перезапусків."""
    extra = random.randint(0, max(0, jitter_seconds))
    await asyncio.sleep(max(0, base_seconds + extra))


async def _run_background_forever(name: str, coro_func, *args):
    """Supervisor: тримає фоновий процес живим, перезапускає при падінні/виході."""
    attempt = 0
    min_delay = 5
    max_delay = 60

    while True:
        try:
            await coro_func(*args)
            # якщо корутина завершилась без exception — це нетипово для наших daemon-loop'ів
            logger.error(f"⚠️ Background task '{name}' завершилась без помилки. Перезапуск через 60s")
            attempt = 0
            await _sleep_with_jitter(60, jitter_seconds=5)

        except asyncio.CancelledError:
            raise

        except Exception as e:
            attempt += 1
            delay = min(max_delay, min_delay * (2 ** max(0, attempt - 1)))
            logger.error(f"💥 Background task '{name}' впала: {e}. Restart in {delay}s", exc_info=True)
            await _sleep_with_jitter(delay, jitter_seconds=5)


def build_dispatcher() -> Dispatcher:
    """
    Dispatcher будуємо один раз на процес:
    - підключаємо error handler
    - підключаємо middleware
    - підключаємо routers
    Це важливо, щоб не отримувати: "Router is already attached..."
    """
    dp = Dispatcher()

    logger.info("🛡 Підключення error handler...")
    dp.errors.register(global_error_handler)

    logger.info("🛡 Підключення middleware...")
    dp.update.outer_middleware(ErrorHandlerMiddleware())  # Перехоплювач помилок
    dp.message.outer_middleware(WhitelistMiddleware())    # Білий список
    dp.callback_query.outer_middleware(WhitelistMiddleware())

    logger.info("📋 Реєстрація роутерів...")
    dp.include_router(common.router)
    dp.include_router(admin.router)
    dp.include_router(user.router)
    dp.include_router(parser_router)

    return dp


async def run_polling_once(dp: Dispatcher):
    """
    Один цикл polling:
    - ініціалізація БД (idempotent)
    - створення Bot
    - старт фонових тасок (sync_loop / scheduler_loop)
    - start_polling
    - коректне скасування тасок і закриття сесії
    """
    bot = None
    tasks = []

    try:
        logger.info("🔧 Ініціалізація бази даних...")
        db_models.init_db()

        bot = Bot(
            token=config.BOT_TOKEN,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML)
        )

        logger.info("🚀 Запуск фонових процесів...")
        tasks.append(asyncio.create_task(_run_background_forever("google_sync", sync_loop), name="google_sync"))
        tasks.append(asyncio.create_task(_run_background_forever("scheduler", scheduler_loop, bot), name="scheduler"))

        logger.info("=" * 50)
        logger.info("🚀 БОТ ЗАПУЩЕНО!")
        logger.info(f"📅 Режим: {'TEST' if config.IS_TEST_MODE else 'PROD'}")
        logger.info(f"📊 Таблиця: {config.SHEET_NAME}")
        logger.info(f"👥 Адмінів: {len(config.ADMIN_IDS)}")
        logger.info(f"🔓 Реєстрація: {'Відкрита' if config.REGISTRATION_OPEN else 'Закрита'}")
        logger.info("=" * 50)
        logger.info("Натисніть Ctrl+C для зупинки.")

        # Очищення webhook (не критично)
        try:
            await bot.delete_webhook(drop_pending_updates=True)
            logger.info("✅ Webhook очищено")
        except Exception as e:
            logger.warning(f"⚠️ Помилка очищення webhook (ігноруємо): {e}")

        # Polling
        # handle_signals=False — щоб повторні запуски polling у цьому ж процесі були стабільні
        await dp.start_polling(
            bot,
            handle_signals=False,
            allowed_updates=dp.resolve_used_update_types()
        )

    finally:
        # Скасування фонових задач (щоб не дублювались)
        for t in tasks:
            try:
                t.cancel()
            except Exception:
                pass

        if tasks:
            try:
                await asyncio.gather(*tasks, return_exceptions=True)
            except Exception:
                pass

        # Закриття сесії
        if bot:
            try:
                await bot.session.close()
                logger.info("✅ Сесія закрита")
            except Exception:
                pass


async def main():
    """
    Auto-restart цикл:
    - Dispatcher створюємо один раз (routers attach один раз)
    - polling перезапускаємо при мережевих/Telegram помилках з backoff
    """
    dp = build_dispatcher()

    restart_attempt = 0
    rapid_crash_count = 0

    rapid_crash_threshold_seconds = 30
    max_rapid_crashes = 10

    min_delay = 5
    max_delay = 60

    while True:
        start_ts = datetime.now()

        try:
            await run_polling_once(dp)

            # Якщо polling завершився без exception — це або ручна зупинка, або dp.stop_polling()
            logger.info("ℹ️ Polling завершився без помилок. Вихід з програми.")
            return

        except KeyboardInterrupt:
            logger.info("🛑 Отримано сигнал зупинки (KeyboardInterrupt). Вихід.")
            return

        except Exception as e:
            uptime = (datetime.now() - start_ts).total_seconds()

            if uptime < rapid_crash_threshold_seconds:
                rapid_crash_count += 1
            else:
                rapid_crash_count = 0

            if _is_transient_network_error(e):
                restart_attempt += 1

                delay = min(max_delay, min_delay * (2 ** max(0, restart_attempt - 1)))
                logger.error(
                    f"❌ Мережева/Telegram помилка (uptime={uptime:.1f}s). "
                    f"Restart attempt #{restart_attempt}, delay={delay}s. Помилка: {e}"
                )

                if rapid_crash_count >= max_rapid_crashes:
                    hard_delay = max(120, delay)
                    logger.error(
                        f"⛔ Забагато швидких падінь ({rapid_crash_count}/{max_rapid_crashes}). "
                        f"Ймовірно Telegram API недоступний/заблокований. Пауза {hard_delay}s."
                    )
                    await _sleep_with_jitter(hard_delay, jitter_seconds=10)
                else:
                    await _sleep_with_jitter(delay, jitter_seconds=5)

                continue

            logger.error(f"💥 Фатальна помилка (не мережева): {e}", exc_info=True)
            raise


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Бот зупинений користувачем.")
    except Exception as e:
        logger.error(f"💥 Фатальна помилка: {e}", exc_info=True)
        sys.exit(1)
