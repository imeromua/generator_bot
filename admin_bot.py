import logging
import subprocess
import asyncio
import os
import re
import html
import sys
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
    CallbackQuery, FSInputFile
)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from dotenv import load_dotenv

# --- КОНФІГУРАЦІЯ ---
load_dotenv()

# FIX: Load sensitive data from environment variables (no hardcoded defaults)
TOKEN = os.getenv("ADMIN_BOT_TOKEN")
ADMIN_ID_STR = os.getenv("ADMIN_BOT_ADMIN_ID")
SERVICE_NAME = os.getenv("ADMIN_BOT_SERVICE_NAME", "generator_bot")
PROJECT_PATH = os.getenv("ADMIN_BOT_PROJECT_PATH", "/home/anubis/generator_bot")

if not TOKEN:
    raise RuntimeError("ADMIN_BOT_TOKEN is not set in environment")

if not ADMIN_ID_STR:
    raise RuntimeError("ADMIN_BOT_ADMIN_ID is not set in environment")

try:
    ADMIN_ID = int(ADMIN_ID_STR)
except ValueError as e:
    raise RuntimeError(f"ADMIN_BOT_ADMIN_ID must be integer, got: {ADMIN_ID_STR}") from e

ENV_FILE = os.path.join(PROJECT_PATH, ".env")
REQ_FILE = os.path.join(PROJECT_PATH, "requirements.txt")
LOG_FILE = os.path.join(PROJECT_PATH, "bot.log")  # Основний файл логів бота

# Security: Maximum output size to prevent message overflow
MAX_OUTPUT_SIZE = 4000

# --- ЛОГУВАННЯ ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- СТАНИ ---
class EnvState(StatesGroup):
    waiting_for_value = State()
    waiting_for_new_key = State()
    waiting_for_new_value = State()


class PipState(StatesGroup):
    waiting_for_new_reqs = State()


# --- ДОПОМІЖНІ ФУНКЦІЇ ---
def run_command(cmd, timeout=30):
    """Execute shell command with timeout and error handling."""
    try:
        result = subprocess.check_output(
            cmd,
            shell=True,
            stderr=subprocess.STDOUT,
            timeout=timeout
        )
        output = result.decode('utf-8').strip()

        # Truncate if too long
        if len(output) > MAX_OUTPUT_SIZE:
            output = output[:MAX_OUTPUT_SIZE] + "\n\n... (обрізано, занадто довгий вивід)"

        return output
    except subprocess.TimeoutExpired:
        return f"⏱ Timeout ({timeout}s)"
    except subprocess.CalledProcessError as e:
        error_output = e.output.decode('utf-8')
        if len(error_output) > MAX_OUTPUT_SIZE:
            error_output = error_output[:MAX_OUTPUT_SIZE] + "\n\n... (обрізано)"
        return f"❌ Error (exit code {e.returncode}):\n{error_output}"
    except Exception as e:
        return f"❌ Exception: {str(e)}"


def read_file(path):
    """Safely read file with error handling."""
    if not os.path.exists(path):
        return ""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        logger.error(f"Failed to read {path}: {e}")
        return f"Error reading file: {e}"


def write_file(path, content):
    """Safely write file with error handling."""
    try:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        return True
    except Exception as e:
        logger.error(f"Failed to write {path}: {e}")
        return False


def read_env():
    """Parse .env file into dictionary."""
    env_vars = {}
    content = read_file(ENV_FILE)
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if '=' in line:
            key, value = line.split('=', 1)
            env_vars[key.strip()] = value.strip()
    return env_vars


def write_env(env_vars):
    """Write dictionary to .env file."""
    content = ""
    for key, value in sorted(env_vars.items()):
        content += f"{key}={value}\n"
    return write_file(ENV_FILE, content)


def safe_html(text):
    """Escape HTML and truncate if needed."""
    if len(text) > MAX_OUTPUT_SIZE:
        text = text[:MAX_OUTPUT_SIZE] + "\n\n... (обрізано)"
    return html.escape(text)


def clear_all_logs() -> str:
    """Очистити локальний bot.log та повністю вичистити журнали systemd.

    УВАГА: journalctl --rotate/--vacuum-* застосовуються до всієї системи, тому
    це повне очищення історії журналів на сервері. Робіть тільки усвідомлено.
    """
    commands = []

    # Видаляємо локальний файл логів проєкту (bot.log)
    if os.path.exists(LOG_FILE):
        commands.append(f"rm -f {LOG_FILE}")

    # Ротація та "вакуум" для systemd-журналу (глобально, повне видалення історії)
    commands.append("sudo journalctl --rotate")
    commands.append("sudo journalctl --vacuum-time=1s")

    outputs = []
    for cmd in commands:
        outputs.append(f"$ {cmd}\n{run_command(cmd, timeout=60)}")

    return "\n\n".join(outputs)


def get_db_status() -> str:
    """Перевірка доступності PostgreSQL за POSTGRES_DSN з .env."""
    env = read_env()
    dsn = env.get("POSTGRES_DSN", "")

    if not dsn:
        return "❌ POSTGRES_DSN не знайдено в .env"

    m = re.match(r"postgresql://(.*?):(.*?)@(.*?):(.*?)/(.*)", dsn)
    if not m:
        return "❌ Неправильний формат POSTGRES_DSN"

    user, _password, host, port, dbname = m.groups()

    # Використовуємо pg_isready без пароля (достатньо для healthcheck)
    cmd = f"pg_isready -h {host} -p {port} -U {user} -d {dbname}"
    output = run_command(cmd, timeout=10)
    healthy = "accepting connections" in output
    icon = "🟢" if healthy else "🔴"

    return (
        f"{icon} <b>PostgreSQL</b>\n"
        f"DSN: <code>{host}:{port}/{dbname}</code>\n\n"
        f"<blockquote expandable>{safe_html(output)}</blockquote>"
    )


def get_redis_status() -> str:
    """Перевірка статусу Redis на основі REDIS_ENABLED/REDIS_URL з .env."""
    env = read_env()
    redis_enabled = env.get("REDIS_ENABLED", "0").strip() in ("1", "true", "True", "yes", "on")
    redis_url = env.get("REDIS_URL", "redis://localhost:6379/0")

    if not redis_enabled:
        return "ℹ️ Redis вимкнено (REDIS_ENABLED=0)"

    # Використовуємо redis-cli, якщо доступний
    cmd = f"redis-cli -u '{redis_url}' PING"
    output = run_command(cmd, timeout=5)
    healthy = "PONG" in output
    icon = "🟢" if healthy else "🔴"

    return (
        f"{icon} <b>Redis</b>\n"
        f"URL: <code>{redis_url}</code>\n\n"
        f"<blockquote expandable>{safe_html(output)}</blockquote>"
    )


# --- ГОЛОВНЕ МЕНЮ ---
kb_main = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="📊 Статус"), KeyboardButton(text="📜 Логи")],
    [KeyboardButton(text="📦 PIP"), KeyboardButton(text="🔧 ENV")],
    [KeyboardButton(text="💾 Бекап БД"), KeyboardButton(text="🚀 GIT PULL")],
    [KeyboardButton(text="🔄 RESTART"), KeyboardButton(text="⚙️ Системна інфо")]
], resize_keyboard=True)


# --- MIDDLEWARE для перевірки ADMIN ---
@dp.message.middleware()
async def admin_check_middleware(handler, event, data):
    if hasattr(event, 'from_user') and event.from_user.id != ADMIN_ID:
        logger.warning(f"Unauthorized access attempt from {event.from_user.id}")
        return
    return await handler(event, data)


@dp.callback_query.middleware()
async def admin_check_cb_middleware(handler, event, data):
    if event.from_user.id != ADMIN_ID:
        await event.answer("❌ Access denied", show_alert=True)
        return
    return await handler(event, data)


# --- START / HELP ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 <b>Привіт, Шеф!</b>\n\n"
        "🤖 Admin Bot v6.0 (DevOps Enhanced)\n"
        f"📦 Service: <code>{SERVICE_NAME}</code>\n"
        f"📁 Path: <code>{PROJECT_PATH}</code>\n\n"
        "Оберіть команду з меню:",
        reply_markup=kb_main,
        parse_mode="HTML"
    )


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    text = (
        "ℹ️ <b>Admin Bot — довідка</b>\n\n"
        "Цей бот керує сервісом <code>" + SERVICE_NAME + "</code> і допомагає з обслуговуванням.\n\n"
        "<b>Кнопки головного меню:</b>\n"
        "• <b>📊 Статус</b> — перевірка стану сервісу, БД (PostgreSQL) та Redis.\n"
        "• <b>📜 Логи</b> — перегляд журналів systemd по сервісу, фільтрація помилок, завантаження у файл,"
        " а також <b>🧹 Очистити логи</b> (повне видалення історії журналів: bot.log + journald).\n"
        "• <b>📦 PIP</b> — перегляд/редагування requirements.txt, встановлення пакетів, freeze, перевірка оновлень.\n"
        "• <b>🔧 ENV</b> — перегляд та зміна .env (ключі конфігурації бота).\n"
        "• <b>💾 Бекап БД</b> — створення та скачування SQL-бекапу PostgreSQL.\n"
        "• <b>🚀 GIT PULL</b> — оновлення коду з репозиторію та пропозиція перезапуску сервісу.\n"
        "• <b>🔄 RESTART</b> — м'який перезапуск сервісу через systemd.\n"
        "• <b>⚙️ Системна інфо</b> — CPU/RAM/Disk, uptime та споживання пам'яті сервісом.\n\n"
        "<b>Ризикові дії:</b>\n"
        "• <b>🧹 Очистити логи</b> — видаляє локальний <code>bot.log</code> та <b>повністю очищає</b> журнали systemd на сервері"
        " (journalctl --rotate/--vacuum-time=1s). Використовувати тільки коли точно не потрібна історія логів.\n"
        "• <b>🔄 RESTART</b> / <b>Перезапуск після GIT/PIP</b> — короткочасно зупиняє сервіс, користувачі можуть відчути паузу.\n"
        "• <b>🔧 ENV</b> — некоректні значення можуть зламати запуск бота (DB_BACKEND, POSTGRES_DSN тощо).\n\n"
        "Цей бот доступний тільки адміну (ADMIN_ID), усі дії логуються.")

    await message.answer(text, parse_mode="HTML")


# --- LOGS VIEWER ---
@dp.message(F.text == "📜 Логи")
async def logs_menu(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📋 50 останніх", callback_data="logs:50"),
            InlineKeyboardButton(text="📋 100 останніх", callback_data="logs:100")
        ],
        [
            InlineKeyboardButton(text="📋 200 останніх", callback_data="logs:200"),
            InlineKeyboardButton(text="📋 Всі сьогодні", callback_data="logs:today")
        ],
        [
            InlineKeyboardButton(text="🚨 Тільки помилки (50)", callback_data="logs:errors:50"),
            InlineKeyboardButton(text="⚠️ Warnings (50)", callback_data="logs:warnings:50")
        ],
        [
            InlineKeyboardButton(text="💾 Завантажити файл", callback_data="logs:download")
        ],
        [
            InlineKeyboardButton(text="🧹 Очистити логи", callback_data="logs:clear")
        ],
    ])

    await message.answer(
        "📜 <b>Перегляд логів</b>\n\n"
        "Оберіть кількість записів або рівень фільтрації, або очистіть логи:",
        reply_markup=kb,
        parse_mode="HTML"
    )


@dp.callback_query(F.data.startswith("logs:"))
async def logs_view(cb: CallbackQuery):
    parts = cb.data.split(":")

    # Окремо обробляємо очистку, щоб не ламати існуючу логіку
    if cb.data == "logs:clear":
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Так, повністю очистити",
                    callback_data="logs:clear_confirm",
                ),
                InlineKeyboardButton(
                    text="❌ Скасувати",
                    callback_data="logs:clear_cancel",
                ),
            ]
        ])

        await cb.message.answer(
            "⚠️ <b>Очистити логи</b>\n\n"
            "Буде <b>ПОВНІСТЮ</b> видалено локальний файл <code>bot.log</code> у проєкті та очищено "
            "історію журналів systemd (journalctl) на сервері.\n\n"
            "Цю операцію слід виконувати лише усвідомлено.",
            reply_markup=kb,
            parse_mode="HTML",
        )
        await cb.answer()
        return

    if len(parts) == 2:
        _, option = parts

        if option == "today":
            cmd = f"journalctl -u {SERVICE_NAME} --since today --no-pager"
            title = "📅 Логи за сьогодні"
        elif option == "download":
            await cb.answer("⏳ Генерую файл...", show_alert=True)
            filename = f"logs_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"
            run_command(f"journalctl -u {SERVICE_NAME} --no-pager > {filename}", timeout=60)
            if os.path.exists(filename):
                await cb.message.answer_document(FSInputFile(filename))
                os.remove(filename)
            return
        else:
            n = int(option)
            cmd = f"journalctl -u {SERVICE_NAME} -n {n} --no-pager"
            title = f"📋 Останні {n} записів"

    elif len(parts) == 3:
        _, filter_level, n = parts
        n = int(n)

        if filter_level == "errors":
            cmd = (
                f"journalctl -u {SERVICE_NAME} -n 500 --no-pager | "
                f"grep -E 'ERROR|CRITICAL|Exception|Traceback' | tail -n {n}"
            )
            title = f"🚨 Останні {n} помилок"
        elif filter_level == "warnings":
            cmd = (
                f"journalctl -u {SERVICE_NAME} -n 500 --no-pager | "
                f"grep -i 'warning' | tail -n {n}"
            )
            title = f"⚠️ Останні {n} попереджень"
        else:
            await cb.answer("❌ Невідомий фільтр", show_alert=True)
            return

    else:
        await cb.answer("❌ Невідомий формат команди", show_alert=True)
        return

    msg = await cb.message.answer("⏳ <i>Завантажую логи...</i>", parse_mode="HTML")

    output = run_command(cmd, timeout=15)

    if not output or output.startswith("❌"):
        await msg.edit_text(f"{title}\n\n❌ Логи недоступні або порожні")
        return

    # Split into chunks if too long
    chunks = []
    current_chunk = ""

    for line in output.split('\n'):
        if len(current_chunk) + len(line) + 1 > 3800:  # Leave room for formatting
            chunks.append(current_chunk)
            current_chunk = line
        else:
            current_chunk += line + "\n"

    if current_chunk:
        chunks.append(current_chunk)

    # Send first chunk with title
    if chunks:
        await msg.edit_text(
            f"{title}\n<blockquote expandable>{safe_html(chunks[0])}</blockquote>",
            parse_mode="HTML"
        )

        # Send remaining chunks
        for chunk in chunks[1:]:
            await cb.message.answer(
                f"<blockquote expandable>{safe_html(chunk)}</blockquote>",
                parse_mode="HTML"
            )

    await cb.answer()


@dp.callback_query(F.data == "logs:clear_confirm")
async def logs_clear_confirm(cb: CallbackQuery):
    msg = await cb.message.edit_text(
        "⏳ <i>Очищаю логи на сервері...</i>",
        parse_mode="HTML",
    )

    result = clear_all_logs()

    await msg.edit_text(
        "✅ <b>Очищення логів виконано</b>\n\n"
        "<blockquote expandable>" + safe_html(result) + "</blockquote>",
        parse_mode="HTML",
    )
    await cb.answer("✅ Готово")


@dp.callback_query(F.data == "logs:clear_cancel")
async def logs_clear_cancel(cb: CallbackQuery):
    await cb.message.edit_text("❌ Очищення логів скасовано")
    await cb.answer()


# --- STATUS (service/db/redis) ---
@dp.message(F.text == "📊 Статус")
async def status_menu(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟢 Сервіс", callback_data="status:service")],
        [InlineKeyboardButton(text="🗄 PostgreSQL", callback_data="status:db")],
        [InlineKeyboardButton(text="🧠 Redis", callback_data="status:redis")],
    ])

    await message.answer(
        "📊 <b>Статус інфраструктури</b>\n\n"
        "Оберіть, що перевірити:",
        reply_markup=kb,
        parse_mode="HTML",
    )


@dp.callback_query(F.data.startswith("status:"))
async def status_view(cb: CallbackQuery):
    _, target = cb.data.split(":", 1)

    if target == "service":
        status_raw = run_command(f"systemctl status {SERVICE_NAME}")
        is_active = "active (running)" in status_raw
        icon = "🟢" if is_active else "🔴"

        text = (
            f"{icon} <b>System Status</b>\n"
            f"<blockquote expandable>{safe_html(status_raw[:3000])}</blockquote>"
        )
        await cb.message.answer(text, parse_mode="HTML")

    elif target == "db":
        text = get_db_status()
        await cb.message.answer(text, parse_mode="HTML")

    elif target == "redis":
        text = get_redis_status()
        await cb.message.answer(text, parse_mode="HTML")

    else:
        await cb.answer("❌ Невідомий статус-таргет", show_alert=True)
        return

    await cb.answer()


# --- SYSTEM INFO ---
@dp.message(F.text == "⚙️ Системна інфо")
async def system_info(message: types.Message):
    msg = await message.answer("⏳ <i>Збираю інформацію...</i>", parse_mode="HTML")

    # Gather system metrics
    uptime = run_command("uptime -p")
    disk = run_command("df -h / | tail -1 | awk '{print $5}'")
    mem = run_command("free -h | grep Mem | awk '{print $3\"/\"$2}'")
    cpu = run_command("top -bn1 | grep 'Cpu(s)' | awk '{print $2}'")

    # Service info
    service_uptime = run_command(
        f"systemctl show {SERVICE_NAME} --property=ActiveEnterTimestamp --value"
    )
    service_memory = run_command(
        f"systemctl show {SERVICE_NAME} --property=MemoryCurrent --value"
    )

    try:
        mem_mb = int(service_memory) / 1024 / 1024
        service_memory_str = f"{mem_mb:.1f} MB"
    except Exception:
        service_memory_str = "N/A"

    text = (
        "⚙️ <b>Системна інформація</b>\n\n"
        f"🖥 CPU: <code>{cpu}%</code>\n"
        f"💾 RAM: <code>{mem}</code>\n"
        f"💿 Disk: <code>{disk}</code>\n"
        f"⏰ Uptime: <code>{uptime}</code>\n\n"
        f"📦 <b>Service: {SERVICE_NAME}</b>\n"
        f"🔄 Started: <code>{service_uptime}</code>\n"
        f"💾 Memory: <code>{service_memory_str}</code>"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Оновити", callback_data="sysinfo_refresh")]
    ])

    await msg.edit_text(text, reply_markup=kb, parse_mode="HTML")


@dp.callback_query(F.data == "sysinfo_refresh")
async def sysinfo_refresh(cb: CallbackQuery):
    await system_info(cb.message)
    await cb.answer("✅ Оновлено")


# --- PIP MANAGER ---
@dp.message(F.text == "📦 PIP")
async def pip_menu(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📄 Переглянути requirements.txt", callback_data="pip_view")],
        [InlineKeyboardButton(text="✏️ Редагувати файл", callback_data="pip_edit")],
        [InlineKeyboardButton(text="🔄 ВСТАНОВИТИ (pip install)", callback_data="pip_install")],
        [InlineKeyboardButton(text="📦 Показати встановлені (pip freeze)", callback_data="pip_freeze")],
        [InlineKeyboardButton(text="🔍 Перевірити оновлення", callback_data="pip_outdated")]
    ])

    await message.answer(
        "📦 <b>Менеджер пакетів Python</b>\nОберіть дію:",
        reply_markup=kb,
        parse_mode="HTML"
    )


@dp.callback_query(F.data == "pip_view")
async def pip_view(cb: CallbackQuery):
    content = read_file(REQ_FILE)
    if not content:
        content = "(файл порожній або відсутній)"

    await cb.message.answer(
        f"📄 <b>requirements.txt:</b>\n<pre>{safe_html(content)}</pre>",
        parse_mode="HTML"
    )
    await cb.answer()


@dp.callback_query(F.data == "pip_edit")
async def pip_edit_start(cb: CallbackQuery, state: FSMContext):
    content = read_file(REQ_FILE)
    await state.set_state(PipState.waiting_for_new_reqs)

    await cb.message.answer(
        "✏️ <b>Редагування requirements.txt</b>\n\n"
        "Надішліть мені **НОВИЙ** вміст файлу одним повідомленням.\n"
        "Він повністю замінить старий файл.",
        parse_mode="HTML"
    )
    if content:
        await cb.message.answer(f"<code>{safe_html(content)}</code>", parse_mode="HTML")
    await cb.answer()


@dp.message(PipState.waiting_for_new_reqs)
async def pip_edit_save(message: types.Message, state: FSMContext):
    new_content = message.text
    if write_file(REQ_FILE, new_content):
        await state.clear()
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Запустити встановлення", callback_data="pip_install")]
        ])
        await message.answer(
            "✅ <b>Файл збережено!</b>\nТепер натисніть кнопку, щоб оновити пакети.",
            reply_markup=kb,
            parse_mode="HTML"
        )
    else:
        await message.answer("❌ Помилка збереження файлу")


@dp.callback_query(F.data == "pip_install")
async def pip_install(cb: CallbackQuery):
    msg = await cb.message.answer(
        "⏳ <i>Запускаю pip install... Це може зайняти час.</i>",
        parse_mode="HTML"
    )

    python_exe = sys.executable
    cmd = f"{python_exe} -m pip install -r {REQ_FILE}"

    output = run_command(cmd, timeout=180)  # 3 minutes timeout

    success = "Successfully installed" in output or "Requirement already satisfied" in output
    icon = "✅" if success else "⚠️"

    await msg.edit_text(
        f"{icon} <b>Результат встановлення</b>\n"
        f"<blockquote expandable>{safe_html(output)}</blockquote>",
        parse_mode="HTML"
    )

    if success:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Перезапустити Бота", callback_data="save_and_restart")]
        ])
        await cb.message.answer(
            "Рекомендується перезапустити сервіс для застосування змін.",
            reply_markup=kb
        )

    await cb.answer()


@dp.callback_query(F.data == "pip_freeze")
async def pip_freeze(cb: CallbackQuery):
    msg = await cb.message.answer("⏳ <i>Отримую список...</i>", parse_mode="HTML")
    python_exe = sys.executable
    output = run_command(f"{python_exe} -m pip freeze")

    await msg.edit_text(
        f"📦 <b>Встановлені пакети:</b>\n<blockquote expandable>{safe_html(output)}</blockquote>",
        parse_mode="HTML"
    )
    await cb.answer()


@dp.callback_query(F.data == "pip_outdated")
async def pip_outdated(cb: CallbackQuery):
    msg = await cb.message.answer(
        "⏳ <i>Перевіряю оновлення...</i>",
        parse_mode="HTML"
    )
    python_exe = sys.executable
    output = run_command(f"{python_exe} -m pip list --outdated", timeout=60)

    if "Package" not in output:
        await msg.edit_text("✅ Всі пакети актуальні!")
    else:
        await msg.edit_text(
            f"🔍 <b>Доступні оновлення:</b>\n"
            f"<blockquote expandable>{safe_html(output)}</blockquote>",
            parse_mode="HTML"
        )
    await cb.answer()


# --- GIT & CONTROL ---
@dp.message(F.text == "🚀 GIT PULL")
async def git_update(message: types.Message):
    msg = await message.answer("⏳ <i>Git Pull...</i>", parse_mode="HTML")

    pull_res = run_command(f"cd {PROJECT_PATH} && git pull")
    log_res = run_command(
        f"cd {PROJECT_PATH} && git log -1 --format='%h - %s (%cr) <%an>'"
    )

    updated = "Updating" in pull_res or "Fast-forward" in pull_res
    already_uptodate = "Already up to date" in pull_res

    icon = "✅" if (updated or already_uptodate) else "⚠️"

    text = (
        f"{icon} <b>GIT UPDATE</b>\n"
        f"🔖 {safe_html(log_res)}\n"
        f"<blockquote expandable>{safe_html(pull_res)}</blockquote>"
    )

    await msg.edit_text(text, parse_mode="HTML")

    if updated:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Перезапустити", callback_data="save_and_restart")]
        ])
        await message.answer(
            "✅ Код оновлено! Рекомендується перезапустити сервіс.",
            reply_markup=kb,
        )


@dp.message(F.text == "🔄 RESTART")
async def restart_bot_btn(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Підтвердити", callback_data="confirm_restart"),
            InlineKeyboardButton(text="❌ Скасувати", callback_data="cancel_restart"),
        ]
    ])

    await message.answer(
        "⚠️ <b>Підтвердіть перезапуск</b>\n\n"
        f"Сервіс <code>{SERVICE_NAME}</code> буде перезапущено.",
        reply_markup=kb,
        parse_mode="HTML",
    )


@dp.callback_query(F.data == "confirm_restart")
async def confirm_restart(cb: CallbackQuery):
    msg = await cb.message.edit_text("🔄 Перезапускаю...")
    run_command(f"sudo systemctl restart {SERVICE_NAME}")

    await asyncio.sleep(3)

    status = run_command(f"systemctl is-active {SERVICE_NAME}")
    if status == "active":
        await msg.edit_text("✅ <b>Перезапуск успішний!</b>", parse_mode="HTML")
    else:
        await msg.edit_text(f"⚠️ Status: <code>{status}</code>", parse_mode="HTML")

    await cb.answer()


@dp.callback_query(F.data == "cancel_restart")
async def cancel_restart(cb: CallbackQuery):
    await cb.message.delete()
    await cb.answer("Скасовано")


# --- ENV EDITOR ---
async def show_env_menu_internal(message_obj, is_edit=False):
    env_vars = read_env()
    kb = []
    for key, value in sorted(env_vars.items()):
        display_val = (value[:8] + '..') if len(value) > 10 else value
        kb.append([
            InlineKeyboardButton(
                text=f"{key}={display_val}", callback_data=f"edit_env:{key}"
            )
        ])
    kb.append([
        InlineKeyboardButton(text="➕ Нова змінна", callback_data="add_new_env")
    ])
    kb.append([
        InlineKeyboardButton(
            text="💾 ЗБЕРЕГТИ ТА ПЕРЕЗАВАНТАЖИТИ",
            callback_data="save_and_restart",
        )
    ])
    markup = InlineKeyboardMarkup(inline_keyboard=kb)
    text = "🔧 <b>Налаштування .env</b>"
    if is_edit:
        await message_obj.edit_text(text, reply_markup=markup, parse_mode="HTML")
    else:
        await message_obj.answer(text, reply_markup=markup, parse_mode="HTML")


@dp.message(F.text == "🔧 ENV")
async def env_menu_handler(message: types.Message):
    await show_env_menu_internal(message)


@dp.callback_query(F.data.startswith("edit_env:"))
async def edit_env_var(cb: CallbackQuery, state: FSMContext):
    key = cb.data.split(":")[1]
    env_vars = read_env()
    await state.update_data(editing_key=key)
    await state.set_state(EnvState.waiting_for_value)

    quick_replies = []
    if key == "DB_BACKEND":
        quick_replies = ["postgres", "sqlite"]
    elif key == "MODE":
        quick_replies = ["TEST", "PROD"]
    elif key in ["REDIS_ENABLED", "SHEETS_RUNTIME_ENABLED"]:
        quick_replies = ["0", "1"]
    elif key == "LOG_LEVEL":
        quick_replies = ["INFO", "DEBUG", "WARNING"]

    kb = []
    if quick_replies:
        kb.append([
            InlineKeyboardButton(text=v, callback_data=f"set_val:{v}")
            for v in quick_replies
        ])
    kb.append([
        InlineKeyboardButton(text="↩️ Скасувати", callback_data="cancel_env")
    ])

    await cb.message.edit_text(
        f"✏️ <b>{key}</b>\nЗараз: <code>{env_vars.get(key, '')}</code>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb),
        parse_mode="HTML",
    )
    await cb.answer()


@dp.callback_query(F.data.startswith("set_val:"))
async def set_val_callback(cb: CallbackQuery, state: FSMContext):
    value = cb.data.split(":", 1)[1]
    data = await state.get_data()
    key = data.get("editing_key")
    if key:
        env = read_env()
        env[key] = value
        write_env(env)
    await state.clear()
    await show_env_menu_internal(cb.message, is_edit=True)
    await cb.answer("✅ Збережено")


@dp.message(EnvState.waiting_for_value)
async def set_val_message(message: types.Message, state: FSMContext):
    data = await state.get_data()
    key = data.get("editing_key")
    if key:
        env = read_env()
        env[key] = message.text.strip()
        write_env(env)
    await state.clear()
    await show_env_menu_internal(message)


@dp.callback_query(F.data == "add_new_env")
async def add_new_start(cb: CallbackQuery, state: FSMContext):
    await state.set_state(EnvState.waiting_for_new_key)
    await cb.message.edit_text(
        "➕ Введіть назву нової змінної:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="↩️ Скасувати", callback_data="cancel_env"
                    )
                ]
            ]
        ),
    )
    await cb.answer()


@dp.message(EnvState.waiting_for_new_key)
async def add_new_key(message: types.Message, state: FSMContext):
    key = message.text.strip().upper().replace(" ", "_")
    await state.update_data(new_key=key)
    await state.set_state(EnvState.waiting_for_new_value)
    await message.answer(f"Введіть значення для <code>{key}</code>:", parse_mode="HTML")


@dp.message(EnvState.waiting_for_new_value)
async def add_new_val(message: types.Message, state: FSMContext):
    data = await state.get_data()
    env = read_env()
    env[data.get("new_key")] = message.text.strip()
    write_env(env)
    await state.clear()
    await message.answer("✅ Змінну додано!")
    await show_env_menu_internal(message)


@dp.callback_query(F.data == "cancel_env")
async def cancel_env(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await show_env_menu_internal(cb.message, is_edit=True)
    await cb.answer()


@dp.callback_query(F.data == "save_and_restart")
async def save_restart(cb: CallbackQuery):
    await cb.message.edit_text("🔄 Перезапускаю сервіс...")
    result = run_command(f"sudo systemctl restart {SERVICE_NAME}")

    await asyncio.sleep(3)

    status = run_command(f"systemctl is-active {SERVICE_NAME}")
    if status == "active":
        await cb.message.answer(
            "✅ <b>Сервіс успішно перезапущено!</b>", parse_mode="HTML"
        )
    else:
        await cb.message.answer(f"⚠️ Status: {status}", parse_mode="HTML")

    await cb.answer()


# --- BACKUP ---
@dp.message(F.text == "💾 Бекап БД")
async def backup_db(message: types.Message):
    env = read_env()
    dsn = env.get("POSTGRES_DSN", "")

    if not dsn:
        await message.answer("❌ POSTGRES_DSN не знайдено в .env")
        return

    try:
        m = re.match(r"postgresql://(.*?):(.*?)@(.*?):(.*?)/(.*)", dsn)
        if not m:
            await message.answer("❌ Неправильний формат DSN")
            return

        user, password, host, port, dbname = m.groups()
        filename = f"backup_{dbname}_{datetime.now().strftime('%Y%m%d_%H%M')}.sql"

        msg = await message.answer("⏳ <i>Створюю бекап...</i>", parse_mode="HTML")

        cmd = (
            f"PGPASSWORD='{password}' pg_dump -U {user} -h {host} -p {port} {dbname} "
            f"> {filename}"
        )
        result = run_command(cmd, timeout=120)

        if os.path.exists(filename):
            file_size = os.path.getsize(filename) / 1024 / 1024  # MB
            await message.answer_document(
                FSInputFile(filename),
                caption=(
                    "📦 <b>Backup created</b>\n"
                    f"💾 Size: {file_size:.2f} MB\n"
                    f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
                ),
                parse_mode="HTML",
            )
            os.remove(filename)
            await msg.delete()
        else:
            await msg.edit_text(
                f"❌ Помилка створення бекапу:\n{safe_html(result)}"
            )

    except Exception as e:
        logger.error(f"Backup error: {e}", exc_info=True)
        await message.answer(f"❌ Помилка: {str(e)}")


# --- GRACEFUL SHUTDOWN ---
async def on_shutdown():
    logger.info("Shutting down admin bot...")
    await bot.session.close()


async def main():
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info(f"Admin Bot started. Watching service: {SERVICE_NAME}")
        await dp.start_polling(bot)
    finally:
        await on_shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped by user")
