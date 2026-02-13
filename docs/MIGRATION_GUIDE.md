# 🔄 Migration Guide: Pydantic Configuration

Посібник з міграції на нову систему конфігурації.

## 🔍 Що змінилося?

### До (Old Config)

```python
import os
from dotenv import load_dotenv

load_dotenv()

# Ручна перевірка та конверсія
BOT_TOKEN = os.getenv("BOT_TOKEN")
try:
    FUEL_CONSUMPTION = float(os.getenv("FUEL_CONSUMPTION", "5.3"))
except ValueError:
    FUEL_CONSUMPTION = 5.3

ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMINS", "").split(",") if x.strip()]

def validate_env():
    """Manual validation."""
    if not BOT_TOKEN:
        sys.exit(1)
```

### Після (Pydantic Config)

```python
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    bot_token: str = Field(alias="BOT_TOKEN")
    fuel_consumption: float = Field(default=5.3, gt=0, alias="FUEL_CONSUMPTION")
    
    @field_validator("fuel_consumption")
    @classmethod
    def validate_fuel(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Must be positive")
        return v

# Автоматична валідація при ініціалізації
settings = Settings()
```

## ✨ Переваги

### 1️⃣ Автоматична валідація

**До:**
```python
try:
    value = float(os.getenv("VALUE"))
    if value <= 0:
        raise ValueError
except:
    value = default
```

**Після:**
```python
value: float = Field(default=1.0, gt=0)
# Валідація автоматично!
```

### 2️⃣ Типізація

**До:**
```python
FUEL_CONSUMPTION  # Невідомий тип
```

**Після:**
```python
fuel_consumption: float  # Чіткий тип, mypy перевірить
```

### 3️⃣ Кращі повідомлення про помилки

**До:**
```
❌ ПОМИЛКА КОНФІГУРАЦІЇ!
Відсутні: BOT_TOKEN
```

**Після:**
```
1 validation error for Settings
bot_token
  Field required [type=missing, input_value={...}]
  For further information visit https://errors.pydantic.dev/...
```

### 4️⃣ Структуровані налаштування

**До:**
```python
DB_BACKEND
POSTGRES_DSN
PG_POOL_MIN_SIZE
PG_POOL_MAX_SIZE
# Всі на одному рівні
```

**Після:**
```python
settings.database.backend
settings.database.postgres_dsn
settings.database.pg_pool_min_size
settings.database.pg_pool_max_size
# Логічно згруповані!
```

---

## 🚀 Міграція коду

### Зворотна сумісність

✅ **Хороша новина:** Всі старі import працюють!

```python
# Старий спосіб - все ще працює
import config

bot_token = config.BOT_TOKEN
admin_ids = config.ADMIN_IDS
fuel = config.FUEL_CONSUMPTION

# Новий спосіб - рекомендовано
from config import settings

bot_token = settings.bot_token
admin_ids = settings.access.get_admin_ids()
fuel = settings.fuel.fuel_consumption
```

### Покрокова міграція

#### Варіант 1: Поступова (рекомендовано)

1. **Нічого не міняйте** - старий код працює
2. **Поступово оновлюйте** нові модулі:

```python
# Новий модуль
from config import settings

class NewHandler:
    def __init__(self):
        # Використовуємо новий API
        self.fuel = settings.fuel.fuel_consumption
```

3. **Перевірте** що все працює
4. **За бажанням** оновіть старі модулі

#### Варіант 2: Повна міграція

```bash
# Find and replace
find . -name "*.py" -type f -exec sed -i 's/import config/from config import settings/g' {} \;
find . -name "*.py" -type f -exec sed -i 's/config\.BOT_TOKEN/settings.bot_token/g' {} \;
# ... etc
```

⚠️ **Увага:** Перевірте кожну заміну вручну!

---

## 📖 Mapping Guide

Таблиця відповідності старих і нових назв:

### Core
| Старий | Новий |
|------|------|
| `config.BOT_TOKEN` | `settings.bot_token` |
| `config.MODE` | `settings.mode` |
| `config.IS_TEST_MODE` | `settings.is_test_mode` |

### Database
| Старий | Новий |
|------|------|
| `config.DB_BACKEND` | `settings.database.backend` |
| `config.SQLITE_PATH` | `settings.database.sqlite_path` |
| `config.POSTGRES_DSN` | `settings.database.postgres_dsn` |
| `config.PG_POOL_MIN_SIZE` | `settings.database.pg_pool_min_size` |
| `config.PG_POOL_MAX_SIZE` | `settings.database.pg_pool_max_size` |

### Redis
| Старий | Новий |
|------|------|
| `config.REDIS_ENABLED` | `settings.redis.enabled` |
| `config.REDIS_URL` | `settings.redis.url` |

### Sheets
| Старий | Новий |
|------|------|
| `config.SHEET_ID` | `settings.sheet_id` *(property)* |
| `config.SHEET_NAME` | `settings.sheets.sheet_name` |
| `config.LOGS_SHEET_NAME` | `settings.sheets.logs_sheet_name` |
| `config.SHEETS_RUNTIME_ENABLED` | `settings.sheets.runtime_enabled` |
| `config.SERVICE_ACCOUNT_PATH` | `settings.sheets.service_account_path` |

### Logging
| Старий | Новий |
|------|------|
| `config.LOG_LEVEL` | `settings.logging.log_level` |
| `config.LOG_FILE` | `settings.logging.log_file` |
| `config.LOG_MAX_BYTES` | `settings.logging.log_max_bytes` |
| `config.LOG_BACKUP_COUNT` | `settings.logging.log_backup_count` |

### Schedule
| Старий | Новий |
|------|------|
| `config.TIMEZONE` | `settings.schedule.timezone` |
| `config.KYIV` | `settings.kyiv_tz` *(property)* |
| `config.WORK_START_TIME` | `settings.schedule.work_start_time` |
| `config.WORK_END_TIME` | `settings.schedule.work_end_time` |
| `config.MORNING_BRIEF_TIME` | `settings.schedule.morning_brief_time` |

### Maintenance
| Старий | Новий |
|------|------|
| `config.OIL_CHANGE_INTERVAL` | `settings.maintenance.oil_change_interval` |
| `config.SPARK_CHANGE_INTERVAL` | `settings.maintenance.spark_change_interval` |
| `config.MAINTENANCE_INTERVAL` | `settings.maintenance.maintenance_interval` |
| `config.MAINTENANCE_LIMIT` | `settings.maintenance.oil_limit` |

### Fuel
| Старий | Новий |
|------|------|
| `config.FUEL_CONSUMPTION` | `settings.fuel.fuel_consumption` |
| `config.EMERGENCY_FUEL_CONSUMPTION` | `settings.fuel.emergency_fuel_consumption` |
| `config.FUEL_ALERT_THRESHOLD_L` | `settings.fuel.fuel_alert_threshold` |
| `config.FUEL_ALERT_COOLDOWN_MIN` | `settings.fuel.fuel_alert_cooldown_min` |
| `config.STOP_REMINDER_MIN_BEFORE_END` | `settings.fuel.stop_reminder_min` |

### Access
| Старий | Новий |
|------|------|
| `config.ADMIN_IDS` | `settings.access.get_admin_ids()` |
| `config.WHITELIST` | `settings.access.get_whitelist()` |
| `config.BOT_STATUS` | `settings.access.bot_status` |
| `config.REGISTRATION_OPEN` | `settings.access.registration_open` |

---

## ❓ Часті питання

### 1. Чи потрібно міняти .env?

❌ **Ні!** `.env` файл залишається без змін.

### 2. Чи потрібно міняти весь код одразу?

❌ **Ні!** Старий код працює завдяки backward compatibility exports.

### 3. Як перевірити, що все працює?

```bash
# Показати конфігурацію
python -m config

# Запустити тести
pytest tests/test_config.py

# Запустити бота
python main.py
```

### 4. Що робити при помилці validation?

```
Validation error: ...
```

1. Прочитайте повідомлення - воно чітко вказує на проблему
2. Перевірте `.env`
3. Подивітьсь [docs/CONFIG.md](CONFIG.md)

### 5. Чи можна використовувати обидва стилі одночасно?

✅ **Так!** Можна міксувати:

```python
import config
from config import settings

# Обидва працюють
bot_token1 = config.BOT_TOKEN
bot_token2 = settings.bot_token
assert bot_token1 == bot_token2
```

---

## 🐞 Troubleshooting

### Помилка: ModuleNotFoundError: No module named 'pydantic_settings'

```bash
pip install pydantic-settings
# або
pip install -r requirements.txt
```

### Помилка: AttributeError: 'Settings' object has no attribute '...'

Ви намагаєтесь використати новий API для неіснуючого поля.

Подивіться [Mapping Guide](#-mapping-guide) вище.

### Помилка: Tests failing after migration

```bash
# Оновіть test fixtures
# Див. tests/conftest.py
```

---

## 📚 Додаткові ресурси

- [docs/CONFIG.md](CONFIG.md) - Повний посібник з конфігурації
- [tests/test_config.py](../tests/test_config.py) - Приклади використання
- [Pydantic Settings Docs](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)

---

## ✅ Checklist

- [ ] Встановити `pydantic-settings`
- [ ] Перевірити конфігурацію: `python -m config`
- [ ] Запустити тести: `pytest`
- [ ] Перевірити бота: `python main.py`
- [ ] (Опціонально) Оновити код на новий API
- [ ] Прочитати [CONFIG.md](CONFIG.md)
