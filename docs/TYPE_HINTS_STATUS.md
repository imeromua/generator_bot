# 📊 Type Hints Migration Status

Статус додавання type hints до generator_bot.

## 🎯 Ціль

Додати type hints до **всіх** модулів проекту для:
- Кращого IDE autocomplete
- Автоматичної перевірки типів (mypy)
- Легшого refactoring
- Кращої документації коду

## 🟢 Завершено (Complete)

### Configuration
- [✅] `config.py` - Повністю типізовано (Pydantic BaseSettings)
- [✅] `tests/test_config.py` - Тести з type hints
- [✅] `tests/test_config_pydantic.py` - Pydantic-специфічні тести

### Database Core
- [✅] `database/models.py` - Connection management, proxy classes
  - Type hints для CursorProxy, ConnectionProxy
  - Proper return types для connection functions
  - Union types для SQLite/PostgreSQL
- [🔶] `database/db_api.py` - Facade (тільки імпорти, не потребує змін)

## 🟡 В процесі (In Progress)

### Database API
- [ ] `database/api/users.py` - Управління користувачами
- [ ] `database/api/state.py` - Generator state management
- [ ] `database/api/logs.py` - Система логування
- [ ] `database/api/fuel.py` - Управління паливом
- [ ] `database/api/maintenance.py` - Техобслуговування
- [ ] `database/api/drivers.py` - Водії
- [ ] `database/api/personnel.py` - Персонал
- [ ] `database/api/schedule.py` - Розклад
- [ ] `database/api/ui.py` - UI state
- [ ] `database/api/messages.py` - Повідомлення
- [ ] `database/api/generator.py` - Генератори

## 🔴 Не почато (TODO)

### Handlers
- [ ] `handlers/common.py`
- [ ] `handlers/admin.py`
- [ ] `handlers/user.py`
- [ ] `handlers/common_parts/*.py` (5-10 файлів)
- [ ] `handlers/admin_parts/*.py` (5-10 файлів)
- [ ] `handlers/user_parts/*.py` (5-10 файлів)

### Services
- [ ] `services/google_sync.py` - Google Sheets sync
- [ ] `services/scheduler.py` - Background tasks
- [ ] `services/parser.py` - DTEK parser

### Middlewares
- [ ] `middlewares/auth.py`
- [ ] `middlewares/error_handler.py`

### Keyboards
- [ ] `keyboards/*.py` (5-10 файлів)

### Utils
- [ ] `utils/*.py` (3-5 файлів)

### Main
- [ ] `main.py` - Entry point
- [ ] `admin_bot.py` - Admin bot

## 📊 Статистика

```
Загальний прогрес: 5% (2/40 модулів)

По категоріях:
✅ Configuration: 100% (3/3)
✅ Database Core: 100% (1/1)
🔶 Database API: 0% (0/10)
🔴 Handlers: 0% (0/25)
🔴 Services: 0% (0/3)
🔴 Middlewares: 0% (0/2)
🔴 Keyboards: 0% (0/10)
🔴 Utils: 0% (0/5)
🔴 Main: 0% (0/2)
```

## 📖 Гайдлайни для додавання type hints

### Базові правила

1. **Всі функції** повинні мати:
   - Type hints для всіх параметрів
   - Return type annotation
   - Docstring (опціонально, але рекомендовано)

2. **Використовуйте modern syntax:**
   ```python
   # ✅ Good (Python 3.10+)
   def process_data(items: list[str]) -> dict[str, int]:
       pass
   
   # ❌ Old
   from typing import List, Dict
   def process_data(items: List[str]) -> Dict[str, int]:
       pass
   ```

3. **Optional vs None:**
   ```python
   from typing import Optional
   
   # ✅ Коли параметр може бути None
   def get_user(user_id: int) -> Optional[dict]:
       pass
   
   # ✅ Альтернативний синтаксис (Python 3.10+)
   def get_user(user_id: int) -> dict | None:
       pass
   ```

4. **Any vs specific types:**
   ```python
   from typing import Any
   
   # ❌ Уникати Any де можливо
   def process(data: Any) -> Any:
       pass
   
   # ✅ Використовувати конкретні типи
   def process(data: dict[str, str]) -> list[int]:
       pass
   ```

### aiogram-специфічні types

```python
from aiogram import Bot, Dispatcher
from aiogram.types import Message, CallbackQuery, User
from aiogram.fsm.context import FSMContext

# Handler signatures
async def handle_message(message: Message) -> None:
    pass

async def handle_callback(callback: CallbackQuery, state: FSMContext) -> None:
    pass

async def send_notification(bot: Bot, user_id: int, text: str) -> None:
    pass
```

### Database types

```python
import sqlite3
from typing import Union
from database.models import ConnectionProxy

# Connection type
ConnectionType = Union[sqlite3.Connection, ConnectionProxy]

def query_db(conn: ConnectionType) -> list[dict]:
    pass
```

### Complex return types

```python
from typing import TypedDict

class GeneratorState(TypedDict):
    status: str
    current_fuel: float
    motor_hours: float
    active_generator: str

def get_state() -> GeneratorState:
    return {
        "status": "ON",
        "current_fuel": 50.0,
        "motor_hours": 100.0,
        "active_generator": "main",
    }
```

## 🧑‍💻 Contributing

### Процес додавання type hints:

1. **Оберіть модуль** з розділу "Не почато"
2. **Додайте type hints** до всіх функцій та методів
3. **Перевірте mypy:**
   ```bash
   mypy database/api/users.py
   ```
4. **Запустіть тести:**
   ```bash
   pytest tests/test_*.py -v
   ```
5. **Оновіть цей файл** (позначте ✅)
6. **Commit:**
   ```bash
   git commit -m "refactor(module): add type hints to module_name.py"
   ```

### Commit message format:

```
refactor(scope): add type hints to <filename>

- Add type hints for all functions
- Add return type annotations
- Update imports for typing
- Fix mypy errors
```

## 🐛 Known Issues

### mypy помилки для розв'язання

1. **psycopg optional import:**
   ```python
   # type: ignore для optional dependencies
   try:
       import psycopg
   except Exception:
       psycopg = None  # type: ignore
   ```

2. **Dynamic attributes:**
   ```python
   # Використовуйте getattr з type hints
   value: str = getattr(config, "PARAM", "default")
   ```

3. **Union types з None:**
   ```python
   # Перевага: Optional[T]
   from typing import Optional
   result: Optional[dict] = None
   ```

## 🎯 Наступні кроки

1. **Пріоритет 1:** Database API модулі (10 файлів)
2. **Пріоритет 2:** Services (3 файли)
3. **Пріоритет 3:** Middlewares (2 файли)
4. **Пріоритет 4:** Utils (5 файлів)
5. **Пріоритет 5:** Handlers (25+ файлів)

---

**Last Updated:** 2026-02-13  
**Current Phase:** Etap 3 - Type Hints  
**Target Completion:** 60%+ coverage by end of Etap 3
