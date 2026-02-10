import asyncio
import logging
import random
import sys
from datetime import datetime
from urllib.parse import urlparse

import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramNetworkError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage
from redis.asyncio import Redis

# Імпорт конфігурації
import config

# Налаштування логування
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Критичні змінні перевіряємо в точці входу
config.validate_env()

import database.models as db_models
from middlewares.auth import WhitelistMiddleware
from middlewares.error_handler import ErrorHandlerMiddleware, global_error_handler

# Імпорт хендлерів
from handlers import common, user, admin
# Імпорт винесеного роутера для парсингу ДТЕК
from handlers.admin_parts import dtek_parser

# Імпорт сервісів
from services.scheduler import scheduler_loop


def _safe_redis_target(url: str) -> str:
    try:
        u = urlparse(url)
        host = u.hostname or "localhost"
        port = u.port or 6379
        db = (u.path or "/0").lstrip("/") or "0"
        return f"{host}:{port}/{db}"
    except Exception:
        return "(invalid REDIS_URL)"


def _is_transient_network_error(exc: Exception) -> bool:
    """
    Визначаємо "тимчасові" помилки, при яких треба робити retry/restart.
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
    """Сон з невеликим випадковим джитером."""
    extra = random.randint(0, max(0, jitter_seconds))
    await asyncio.sleep(max(0, base_seconds + extra))


async def _run_background_forever(name: str, coro_func, *args):
    """Supervisor: тримає фоновий процес живим, перезапускає при падінні."""
    attempt = 0
    min_delay = 5
    max_delay = 60

    while True:
        try:
            await coro_func(*args)
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
    """Побудова Dispatcher з усіма middlewares та routers."""
    
    storage = MemoryStorage()

    if getattr(config, "REDIS_ENABLED", False):
        target = _safe_redis_target(getattr(config, "REDIS_URL", ""))
        try:
            redis = Redis.from_url(getattr(config, "REDIS_URL", "redis://localhost:6379/0"))
            storage = RedisStorage(redis=redis)
            logger.info(f"🧠 FSM storage: Redis ({target})")
        except Exception as e:
            logger.error(f"❌ Не вдалося підключити Redis FSM storage ({target}): {e}. Використовую MemoryStorage")
            storage = MemoryStorage()
            logger.info("🧠 FSM storage: Memory")
    else:
        logger.info("🧠 FSM storage: Memory (REDIS_ENABLED=0)")

    dp = Dispatcher(storage=storage)

    logger.info("🛡 Підключення error handler...")
    dp.errors.register(global_error_handler)

    logger.info("🛡 Підключення middleware...")
    dp.update.outer_middleware(ErrorHandlerMiddleware())
    dp.message.outer_middleware(WhitelistMiddleware())
    dp.callback_query.outer_middleware(WhitelistMiddleware())

    logger.info("📋 Реєстрація роутерів...")
    dp.include_router(common.router)
    dp.include_router(admin.router)
    dp.include_router(user.router)
    # Підключаємо винесений роутер
    dp.include_router(dtek_parser.router)

    return dp


async def run_polling_once(dp: Dispatcher):
    """Один цикл запуску бота."""
    bot = None
    tasks = []

    try:
        logger.info(f"🗄 DB backend: {getattr(config, 'DB_BACKEND', 'sqlite')} ({db_models.db_target_info()})")
        logger.info("🔧 Ініціалізація бази даних...")
        
        # Виклик ініціалізації БД.
        # В майбутньому, коли перейдемо на async DB, тут буде await db_models.init_db()
        db_models.init_db()

        bot = Bot(
            token=config.BOT_TOKEN,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML)
        )

        logger.info("🚀 Запуск фонових процесів...")
        tasks.append(asyncio.create_task(_run_background_forever("scheduler", scheduler_loop, bot), name="scheduler"))

        logger.info("=" * 50)
        logger.info("🚀 БОТ ЗАПУЩЕНО!")
        logger.info(f"📅 Режим: {'TEST' if config.IS_TEST_MODE else 'PROD'}")
        logger.info(f"📊 Таблиця: {config.SHEET_NAME}")
        logger.info(f"👥 Адмінів: {len(config.ADMIN_IDS)}")
        logger.info(f"🔓 Реєстрація: {'Відкрита' if config.REGISTRATION_OPEN else 'Закрита'}")
        logger.info("=" * 50)
        logger.info("Натисніть Ctrl+C для зупинки.")

        try:
            await bot.delete_webhook(drop_pending_updates=True)
            logger.info("✅ Webhook очищено")
        except Exception as e:
            logger.warning(f"⚠️ Помилка очищення webhook (ігноруємо): {e}")

        await dp.start_polling(
            bot,
            handle_signals=False,
            allowed_updates=dp.resolve_used_update_types()
        )

    finally:
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

        if bot:
            try:
                await bot.session.close()
                logger.info("✅ Сесія закрита")
            except Exception:
                pass


async def main():
    """Auto-restart цикл."""
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
                    f"❌ Мережева помилка (uptime={uptime:.1f}s). "
                    f"Restart #{restart_attempt}, delay={delay}s. Error: {e}"
                )

                if rapid_crash_count >= max_rapid_crashes:
                    hard_delay = max(120, delay)
                    logger.error(f"⛔ Забагато швидких падінь. Пауза {hard_delay}s.")
                    await _sleep_with_jitter(hard_delay, jitter_seconds=10)
                else:
                    await _sleep_with_jitter(delay, jitter_seconds=5)

                continue

            logger.error(f"💥 Фатальна помилка: {e}", exc_info=True)
            raise


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Бот зупинений користувачем.")
    except Exception as e:
        logger.error(f"💥 Фатальна помилка main: {e}", exc_info=True)
        sys.exit(1)