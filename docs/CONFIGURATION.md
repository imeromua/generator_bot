# ⚙️ Configuration Guide

Повний посібник з налаштування generator_bot, який використовує Pydantic для type-safe конфігурації.

## 📋 Зміст

- [Огляд](#огляд)
- [Швидкий старт](#швидкий-старт)
- [Структура конфігурації](#структура-конфігурації)
- [Параметри](#параметри)
- [Валідація](#валідація)
- [Міграція](#міграція)

---

## 🔍 Огляд

Бот використовує **Pydantic BaseSettings** для управління конфігурацією:

✅ **Переваги:**
- Автоматична валідація всіх параметрів
- Type hints для всіх налаштувань
- Чіткі повідомлення про помилки
- Підтримка вкладених settings
- Backward compatibility з старим кодом

---

## 🚀 Швидкий старт

### 1. Створіть .env файл

```bash
cp .env.example .env
nano .env  # або відкрийте у вашому редакторі
```

### 2. Мінімальна конфігурація

```env
# Обов'язкові параметри
BOT_TOKEN=your_bot_token_from_botfather
ADMINS=your_telegram_id
SHEET_ID_PROD=your_production_sheet_id
SHEET_ID_TEST=your_test_sheet_id

# Режим
MODE=TEST  # або PROD
```

### 3. Запустіть бота

```bash
python main.py
```

---

## 🏗️ Структура конфігурації

Конфігурація розділена на логічні модулі:

```python
class Settings(BaseSettings):
    # Основні налаштування
    bot_token: str
    mode: Literal["TEST", "PROD"]
    
    # Вкладені settings
    database: DatabaseSettings
    redis: RedisSettings
    sheets: SheetsSettings
    logging: LoggingSettings
    schedule: WorkScheduleSettings
    maintenance: MaintenanceSettings
    fuel: FuelSettings
    access: AccessSettings
```

### Вкладені Settings Classes

#### DatabaseSettings
```python
DB_BACKEND=sqlite          # sqlite або postgres
SQLITE_PATH=generator.db   # для SQLite
POSTGRES_DSN=postgresql://user:pass@host:5432/db  # для PostgreSQL

# Connection pool (PostgreSQL)
PG_POOL_MIN_SIZE=2
PG_POOL_MAX_SIZE=10
PG_POOL_TIMEOUT=30
```

#### RedisSettings
```python
REDIS_ENABLED=1                      # 0 або 1
REDIS_URL=redis://localhost:6379/0  # connection URL
```

#### SheetsSettings
```python
SHEET_ID_PROD=your_prod_sheet_id
SHEET_ID_TEST=your_test_sheet_id
SHEET_NAME=ЛЮТИЙ
SERVICE_ACCOUNT_PATH=service_account.json
SHEETS_RUNTIME_ENABLED=1  # 0 для тестів без API
```

#### LoggingSettings
```python
LOG_FILE=bot.log
LOG_LEVEL=INFO              # DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_MAX_BYTES=10485760      # 10MB
LOG_BACKUP_COUNT=5
```

#### WorkScheduleSettings
```python
TIMEZONE=Europe/Kyiv
WORK_START=07:30            # HH:MM формат
WORK_END=20:30
BRIEF_TIME=07:30
```

#### MaintenanceSettings
```python
OIL_CHANGE_INTERVAL=100      # години роботи
SPARK_CHANGE_INTERVAL=100
MAINTENANCE_INTERVAL=300
```

#### FuelSettings
```python
FUEL_CONSUMPTION=5.3              # л/год (основний)
EMERGENCY_FUEL_CONSUMPTION=5.5    # л/год (аварійний)
FUEL_ALERT_THRESHOLD=40.0         # поріг сповіщення (л)
FUEL_ALERT_COOLDOWN_MIN=60        # таймаут між алертами
STOP_REMINDER_MIN=15              # нагадування перед кінцем дня
```

#### AccessSettings
```python
ADMINS=123456789,987654321    # через кому
USERS=111111111,222222222     # whitelist (опційно)
BOT_STATUS=ON                 # ON або OFF
```

---

## 📚 Параметри

### Обов'язкові параметри

| Параметр | Тип | Опис |
|----------|-----|------|
| `BOT_TOKEN` | str | Токен від @BotFather |
| `ADMINS` | str | ID адміністраторів (через кому) |
| `SHEET_ID_PROD` | str | ID продакшн таблиці |
| `SHEET_ID_TEST` | str | ID тестової таблиці |

### Опційні параметри

| Параметр | Default | Опис |
|----------|---------|------|
| `MODE` | `TEST` | Режим роботи (TEST/PROD) |
| `DB_BACKEND` | `sqlite` | Тип БД (sqlite/postgres) |
| `REDIS_ENABLED` | `0` | Увімкнути Redis |
| `LOG_LEVEL` | `INFO` | Рівень логування |
| `TIMEZONE` | `Europe/Kyiv` | Часовий пояс |
| `FUEL_CONSUMPTION` | `5.3` | Витрата палива (л/год) |

### Параметри з валідацією

#### Часовий формат (HH:MM)
```python
WORK_START=07:30  # ✅ Правильно
WORK_START=7:30   # ❌ Помилка (потрібен 0 на початку)
WORK_START=25:00  # ❌ Помилка (неправильна година)
```

#### Часовий пояс
```python
TIMEZONE=Europe/Kyiv       # ✅ Правильно
TIMEZONE=America/New_York  # ✅ Правильно
TIMEZONE=Invalid/Zone      # ⚠️ Fallback до UTC
```

#### PostgreSQL
```python
DB_BACKEND=postgres
POSTGRES_DSN=postgresql://user:pass@host:5432/db  # Обов'язково!
# ❌ Якщо DB_BACKEND=postgres, але POSTGRES_DSN не вказано → помилка
```

#### Позитивні числа
```python
FUEL_CONSUMPTION=5.3    # ✅
FUEL_CONSUMPTION=0      # ❌ Має бути > 0
OIL_CHANGE_INTERVAL=100 # ✅
OIL_CHANGE_INTERVAL=-10 # ❌ Має бути > 0
```

---

## ✅ Валідація

### Автоматична валідація

Pydantic автоматично перевіряє:
- ✅ Тип даних (str, int, float, bool)
- ✅ Допустимі значення (Literal types)
- ✅ Діапазони (ge, gt, le, lt)
- ✅ Формат (regex patterns)
- ✅ Залежності між полями

### Приклади валідації

#### При запуску бота:

```bash
# ❌ Відсутній BOT_TOKEN
$ python main.py
============================================================
❌ ПОМИЛКА КОНФІГУРАЦІЇ!

Деталі: Field required [type=missing, input_value={...}, input_type=dict]
For further information visit https://errors.pydantic.dev/...

Перевірте файл .env та переконайтесь, що всі обов'язкові параметри вказані.
============================================================
```

```bash
# ❌ Неправильний формат часу
$ python main.py
ValidationError: 1 validation error for WorkScheduleSettings
work_start_time
  Time must be in HH:MM format, got: 7:30
```

#### У коді:

```python
from config import settings

# Типізовані значення
settings.fuel.fuel_consumption  # float
settings.database.backend       # Literal["sqlite", "postgres"]
settings.access.get_admin_ids() # list[int]

# Computed properties
if settings.is_test_mode:
    print(f"Using test sheet: {settings.sheet_id}")

# Timezone object
from datetime import datetime
now = datetime.now(settings.kyiv_tz)
```

---

## 🔄 Міграція

### З старого config.py

Старий код продовжує працювати без змін:

```python
# ✅ Старий код (все ще працює)
import config

token = config.BOT_TOKEN
admins = config.ADMIN_IDS
fuel = config.FUEL_CONSUMPTION
```

```python
# ✅ Новий код (рекомендовано)
from config import settings

token = settings.bot_token
admins = settings.access.get_admin_ids()
fuel = settings.fuel.fuel_consumption
```

### Табличка відповідності

| Старий | Новий | Тип |
|--------|-------|-----|
| `config.BOT_TOKEN` | `settings.bot_token` | str |
| `config.ADMIN_IDS` | `settings.access.get_admin_ids()` | list[int] |
| `config.DB_BACKEND` | `settings.database.backend` | Literal |
| `config.REDIS_ENABLED` | `settings.redis.enabled` | bool |
| `config.SHEET_ID` | `settings.sheet_id` | str |
| `config.FUEL_CONSUMPTION` | `settings.fuel.fuel_consumption` | float |
| `config.KYIV` | `settings.kyiv_tz` | ZoneInfo |
| `config.IS_TEST_MODE` | `settings.is_test_mode` | bool |

### Поступова міграція

1. **Етап 1:** Використовуйте старі імпорти (без змін коду)
   ```python
   from config import BOT_TOKEN, ADMIN_IDS
   ```

2. **Етап 2:** Міграція на `settings` object
   ```python
   from config import settings
   token = settings.bot_token
   ```

3. **Етап 3:** Використання вкладених settings
   ```python
   from config import settings
   db_backend = settings.database.backend
   admins = settings.access.get_admin_ids()
   ```

---

## 🛠️ Налагодження

### Показати поточну конфігурацію

```python
python -c "from config import settings; settings.print_config()"
```

```
============================================================
📋 ПОТОЧНА КОНФІГУРАЦІЯ
============================================================
Режим: TEST
Log Level: INFO
Log File: bot.log (Max: 10.0 MB, Backups: 5)
DB backend: sqlite
SQLite path: generator.db
Redis enabled: False
...
```

### Перевірка валідації

```python
python -c "from config import validate_env; validate_env()"
```

### IDE autocomplete

```python
from config import settings

# ✅ IDE знає про всі поля
settings.database.  # [autocomplete: backend, sqlite_path, postgres_dsn, ...]
settings.fuel.      # [autocomplete: fuel_consumption, emergency_fuel_consumption, ...]
```

---

## 📖 Приклади

### Локальна розробка (SQLite, без Sheets)

```env
MODE=TEST
BOT_TOKEN=your_token
ADMINS=your_id
SHEET_ID_PROD=dummy
SHEET_ID_TEST=dummy

DB_BACKEND=sqlite
SQLITE_PATH=test.db
REDIS_ENABLED=0
SHEETS_RUNTIME_ENABLED=0
LOG_LEVEL=DEBUG
```

### Production (PostgreSQL + Redis)

```env
MODE=PROD
BOT_TOKEN=prod_token
ADMINS=123456789
SHEET_ID_PROD=real_sheet_id
SHEET_ID_TEST=test_sheet_id

DB_BACKEND=postgres
POSTGRES_DSN=postgresql://botuser:pass@localhost:5432/generator_bot
REDIS_ENABLED=1
REDIS_URL=redis://localhost:6379/0
SHEETS_RUNTIME_ENABLED=1
LOG_LEVEL=INFO
```

### Docker Compose

```env
MODE=PROD
BOT_TOKEN=prod_token
ADMINS=123456789
SHEET_ID_PROD=sheet_id
SHEET_ID_TEST=test_id

# Docker internal hostnames
DB_BACKEND=postgres
POSTGRES_DSN=postgresql://botuser:botpass@postgres:5432/generator_bot
REDIS_ENABLED=1
REDIS_URL=redis://redis:6379/0
```

---

## 🔒 Безпека

### ❌ Не робіть так:

- Не комітьте `.env` у git
- Не використовуйте production токени в TEST режимі
- Не діліться service_account.json публічно

### ✅ Best practices:

```bash
# Перевірте .gitignore
cat .gitignore | grep .env
# Має бути:
# .env
# .env.*
# service_account.json

# Різні .env для різних середовищ
.env.local        # локальна розробка
.env.development  # dev сервер
.env.production   # production

# Завантаження правильного env
export ENV_FILE=.env.production
python main.py
```

---

## 📞 Підтримка

Якщо виникли проблеми з конфігурацією:

1. Перевірте `.env` файл
2. Запустіть `python -c "from config import settings; settings.print_config()"`
3. Перегляньте логи: `cat bot.log`
4. Створіть [issue](https://github.com/imeromua/generator_bot/issues) з детальним описом

---

## 🔗 Додаткові ресурси

- [Pydantic Documentation](https://docs.pydantic.dev/)
- [Pydantic Settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
- [Environment Variables Best Practices](https://12factor.net/config)
