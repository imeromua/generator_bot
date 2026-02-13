# ⚙️ Configuration Guide

Повний посібник з налаштування generator_bot.

## 📋 Зміст

- [Основи](#основи)
- [Конфігураційні групи](#конфігураційні-групи)
- [Використання в коді](#використання-в-коді)
- [Pydantic валідація](#pydantic-валідація)
- [Приклади конфігурацій](#приклади-конфігурацій)

---

## 🔑 Основи

### Структура конфігурації

Конфігурація побудована на **Pydantic BaseSettings**, що забезпечує:

- ✅ **Автоматичну валідацію** змінних середовища
- ✅ **Типізацію** всіх параметрів
- ✅ **Чіткі повідомлення про помилки**
- ✅ **Зворотну сумісність** зі старим кодом

### Завантаження конфігурації

```bash
# Створити .env файл
cp .env.example .env

# Відредагувати параметри
nano .env
```

Конфігурація завантажується автоматично при імпорті `config` модуля.

---

## 📊 Конфігураційні групи

### 1️⃣ Core Settings

Основні параметри бота.

```env
# Обов'язкові
BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11

# Режим роботи: TEST або PROD
MODE=TEST
```

**Опис:**
- `BOT_TOKEN` - Telegram bot token (з @BotFather)
- `MODE` - Режим: `TEST` (тестова таблиця) або `PROD` (production)

---

### 2️⃣ Database Settings

Налаштування бази даних.

```env
# Backend: sqlite або postgres
DB_BACKEND=sqlite

# SQLite (якщо DB_BACKEND=sqlite)
SQLITE_PATH=generator.db

# PostgreSQL (якщо DB_BACKEND=postgres)
POSTGRES_DSN=postgresql://user:password@localhost:5432/generator_bot
POSTGRES_ADMIN_DSN=postgresql://admin:password@localhost:5432/postgres

# Connection Pool (тільки для PostgreSQL)
PG_POOL_MIN_SIZE=2
PG_POOL_MAX_SIZE=10
PG_POOL_TIMEOUT=30
PG_POOL_MAX_IDLE=300
```

**Валідація:**
- Якщо `DB_BACKEND=postgres`, то `POSTGRES_DSN` обов'язковий
- `psycopg` має бути встановлений для PostgreSQL
- Pool sizes мусять бути >= 1

---

### 3️⃣ Redis Settings

Налаштування кешування.

```env
# Увімкнути/вимкнути Redis
REDIS_ENABLED=1

# URL до Redis
REDIS_URL=redis://localhost:6379/0
```

**Валідація:**
- Якщо `REDIS_ENABLED=1`, то `REDIS_URL` обов'язковий

---

### 4️⃣ Google Sheets Settings

Налаштування Google Sheets інтеграції.

```env
# Обов'язкові
SHEET_ID_PROD=1ABC...xyz
SHEET_ID_TEST=2DEF...uvw

# Опціональні
SHEETS_RUNTIME_ENABLED=1
SERVICE_ACCOUNT_PATH=service_account.json
SHEET_NAME=ЛЮТИЙ
LOGS_SHEET_NAME=ПОДІЇ
```

**Опис:**
- `SHEET_ID_PROD` / `SHEET_ID_TEST` - Google Sheets document IDs
- `SHEETS_RUNTIME_ENABLED` - Вкл/викл синхронізації в runtime
- `SERVICE_ACCOUNT_PATH` - Шлях до service account JSON

---

### 5️⃣ Logging Settings

Налаштування логування.

```env
LOG_FILE=bot.log
LOG_LEVEL=INFO
LOG_MAX_BYTES=10485760  # 10MB
LOG_BACKUP_COUNT=5
```

**Рівні логування:**
- `DEBUG` - Детальна інформація
- `INFO` - Загальні події (рекомендовано)
- `WARNING` - Попередження
- `ERROR` - Помилки
- `CRITICAL` - Критичні помилки

**Валідація:**
- `LOG_MAX_BYTES` >= 1024
- `LOG_BACKUP_COUNT` >= 0

---

### 6️⃣ Work Schedule Settings

Графік роботи.

```env
TIMEZONE=Europe/Kyiv
WORK_START=07:30
WORK_END=20:30
BRIEF_TIME=07:30
```

**Формат часу:** `HH:MM` (24-годинний)

**Валідація:**
- Час має бути в форматі `HH:MM`
- 0 <= години < 24
- 0 <= хвилини < 60
- Невірна таймзона автоматично змінюється на UTC

---

### 7️⃣ Maintenance Settings

Інтервали технічного обслуговування (в мотогодинах).

```env
OIL_CHANGE_INTERVAL=100
SPARK_CHANGE_INTERVAL=100
MAINTENANCE_INTERVAL=300

# Зворотна сумісність (опціонально)
OIL_LIMIT=100
```

**Валідація:**
- Всі інтервали > 0

---

### 8️⃣ Fuel Settings

Налаштування палива.

```env
# Витрата палива (л/год)
FUEL_CONSUMPTION=5.3
FUEL_RATE=5.3  # Альтернативна назва

# Аварійний генератор (опціонально)
EMERGENCY_FUEL_CONSUMPTION=6.0

# Сповіщення
FUEL_ALERT_THRESHOLD=40.0
FUEL_ALERT_COOLDOWN_MIN=60
STOP_REMINDER_MIN=15
```

**Логіка:**
- `FUEL_RATE` - аліас для `FUEL_CONSUMPTION`
- Якщо `EMERGENCY_FUEL_CONSUMPTION` не вказано, використовується `FUEL_CONSUMPTION`

**Валідація:**
- Всі значення > 0

---

### 9️⃣ Access Settings

Контроль доступу.

```env
# Обов'язкові
ADMINS=123456789,987654321

# Опціональні
BOT_STATUS=ON
USERS=111111111,222222222
```

**Опис:**
- `ADMINS` - Telegram ID адміністраторів (через кому)
- `BOT_STATUS` - `ON` (реєстрація відкрита) або `OFF`
- `USERS` - Whitelist користувачів

**Валідація:**
- ID мусять бути цілими числами

---

## 💻 Використання в коді

### Новий спосіб (Pydantic)

```python
from config import settings

# Доступ до налаштувань
bot_token = settings.bot_token
is_test = settings.is_test_mode

# Груповані налаштування
db_backend = settings.database.backend
redis_enabled = settings.redis.enabled
log_level = settings.logging.log_level

# Методи
admin_ids = settings.access.get_admin_ids()
whitelist = settings.access.get_whitelist()
sheet_id = settings.sheet_id  # Auto-selected based on MODE

# Properties
kyiv_tz = settings.kyiv_tz  # ZoneInfo object
is_registration_open = settings.access.registration_open
```

### Старий спосіб (зворотна сумісність)

```python
import config

# Direct imports (працює як і раніше)
BOT_TOKEN = config.BOT_TOKEN
ADMIN_IDS = config.ADMIN_IDS
DB_BACKEND = config.DB_BACKEND
FUEL_CONSUMPTION = config.FUEL_CONSUMPTION
```

### Валідація

```python
from config import settings

# Автоматична валідація при імпорті
# Якщо конфіг невірний - бот не запуститься

# Для backward compatibility
settings.validate_all()  # == стара validate_env()

# Показати конфігурацію
settings.print_config()
```

---

## ✅ Pydantic Валідація

### Автоматичні перевірки

```python
# Перевірка типів
FUEL_CONSUMPTION: float  # Має бути float
ADMIN_IDS: list[int]     # Має бути списком int

# Перевірка обмежень
fuel_consumption > 0         # Має бути додатним
pg_pool_min_size >= 1        # >= 1
log_max_bytes >= 1024        # >= 1KB

# Перевірка формату
work_start_time: "HH:MM"    # Час у форматі HH:MM
log_level: Literal["DEBUG", "INFO", ...]  # Тільки дозволені значення
```

### Custom Validators

```python
class DatabaseSettings(BaseSettings):
    backend: Literal["sqlite", "postgres"] = "sqlite"
    postgres_dsn: str = ""
    
    @model_validator(mode="after")
    def validate_postgres_config(self):
        """Check postgres requirements."""
        if self.backend == "postgres":
            if not self.postgres_dsn:
                raise ValueError("POSTGRES_DSN required")
            # Check psycopg installed
            try:
                import psycopg
            except ImportError:
                raise ImportError("Install psycopg")
        return self
```

### Повідомлення про помилки

```
❌ ПОМИЛКА КОНФІГУРАЦІЇ!

Деталі: 1 validation error for Settings
bot_token
  Field required [type=missing, input_value={...}, input_type=dict]

Перевірте файл .env та переконайтесь, що всі обов'язкові параметри вказані.
```

---

## 📦 Приклади конфігурацій

### Мінімальна (розробка)

```env
BOT_TOKEN=your_test_token
SHEET_ID_PROD=prod_sheet_id
SHEET_ID_TEST=test_sheet_id
ADMINS=your_telegram_id
MODE=TEST
DB_BACKEND=sqlite
SQLITE_PATH=test.db
SHEETS_RUNTIME_ENABLED=0
```

### Production (SQLite)

```env
BOT_TOKEN=your_prod_token
SHEET_ID_PROD=prod_sheet_id
SHEET_ID_TEST=test_sheet_id
ADMINS=123456789,987654321
MODE=PROD
DB_BACKEND=sqlite
SQLITE_PATH=/var/lib/generator_bot/generator.db
REDIS_ENABLED=0
SHEETS_RUNTIME_ENABLED=1
LOG_LEVEL=INFO
LOG_FILE=/var/log/generator_bot/bot.log
```

### Production (PostgreSQL + Redis)

```env
BOT_TOKEN=your_prod_token
SHEET_ID_PROD=prod_sheet_id
SHEET_ID_TEST=test_sheet_id
ADMINS=123456789,987654321
MODE=PROD

# Database
DB_BACKEND=postgres
POSTGRES_DSN=postgresql://botuser:secure_pass@db.internal:5432/generator_bot
PG_POOL_MIN_SIZE=5
PG_POOL_MAX_SIZE=20

# Redis
REDIS_ENABLED=1
REDIS_URL=redis://redis.internal:6379/0

# Sheets
SHEETS_RUNTIME_ENABLED=1
SERVICE_ACCOUNT_PATH=/app/config/service_account.json

# Logging
LOG_LEVEL=WARNING
LOG_FILE=/var/log/generator_bot/bot.log
LOG_MAX_BYTES=52428800  # 50MB
LOG_BACKUP_COUNT=10

# Fuel
FUEL_CONSUMPTION=5.3
EMERGENCY_FUEL_CONSUMPTION=6.0
FUEL_ALERT_THRESHOLD=30.0
```

### Docker Compose

```env
BOT_TOKEN=your_token
SHEET_ID_PROD=prod_id
SHEET_ID_TEST=test_id
ADMINS=123456789
MODE=PROD

DB_BACKEND=postgres
POSTGRES_DSN=postgresql://botuser:botpass@postgres:5432/generator_bot

REDIS_ENABLED=1
REDIS_URL=redis://redis:6379/0

LOG_LEVEL=INFO
```

---

## 🔧 Troubleshooting

### Помилка: "Field required"

```
Validation error: bot_token - Field required
```

**Рішення:** Додайте `BOT_TOKEN=...` у `.env`

### Помилка: "POSTGRES_DSN is required"

```
Validation error: POSTGRES_DSN is required when DB_BACKEND=postgres
```

**Рішення:** Додайте `POSTGRES_DSN` або змініть `DB_BACKEND=sqlite`

### Помилка: "Invalid time format"

```
Validation error: Time must be in HH:MM format, got: 25:00
```

**Рішення:** Використовуйте формат `HH:MM` з валідними значеннями (00:00 - 23:59)

### Перевірка конфігурації

```bash
# Показати поточну конфігурацію
python -m config

# Або в Python
python -c "from config import settings; settings.print_config()"
```

---

## 📚 Додаткові ресурси

- [Pydantic Settings Documentation](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
- [Environment Variables Best Practices](https://12factor.net/config)
- [.env.example](.env.example) - Шаблон конфігурації
