# 🛠️ Development Guide

Посібник для розробників generator_bot.

## 📋 Зміст

- [Підготовка середовища](#підготовка-середовища)
- [Структура проекту](#структура-проекту)
- [Тестування](#тестування)
- [Якість коду](#якість-коду)
- [Стандарти коду](#стандарти-коду)
- [Git Workflow](#git-workflow)

---

## 🛠️ Підготовка середовища

### Вимоги

- Python 3.11+ або 3.12+
- Git
- PostgreSQL 15+ (опціонально, можна SQLite)
- Redis 7+ (опціонально)

### Клонування репозиторію

```bash
git clone https://github.com/imeromua/generator_bot.git
cd generator_bot
```

### Встановлення залежностей

```bash
# Створити віртуальне середовище
python -m venv venv

# Активувати
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows

# Встановити залежності + dev tools
pip install -e ".[dev]"

# Встановити pre-commit hooks
pre-commit install
```

### Налаштування конфігурації

```bash
cp .env.example .env
nano .env  # Відредагувати параметри
```

**Мінімальна конфігурація для розробки:**

```env
BOT_TOKEN=your_test_bot_token
SHEET_ID_TEST=your_test_sheet_id
SHEET_ID_PROD=your_prod_sheet_id
ADMINS=your_telegram_id
MODE=TEST
DB_BACKEND=sqlite
SQLITE_PATH=generator_test.db
SHEETS_RUNTIME_ENABLED=0  # Вимкнути sheets для швидшого тестування
```

---

## 📁 Структура проекту

```
generator_bot/
├── .github/
│   └── workflows/
│       └── ci.yml              # GitHub Actions CI/CD
├── database/
│   ├── api/                 # Database API modules
│   ├── models.py            # Core database models
│   └── db_api.py            # Unified DB API
├── docs/
│   ├── DEPLOYMENT.md        # Deployment guide
│   └── DEVELOPMENT.md       # This file
├── handlers/
│   ├── admin.py             # Admin handlers
│   ├── admin_parts/         # Admin sub-modules
│   ├── common.py            # Common handlers
│   ├── common_parts/        # Common sub-modules
│   ├── user.py              # User handlers
│   └── user_parts/          # User sub-modules
├── keyboards/
│   └── ...                  # Inline keyboards
├── middlewares/
│   ├── auth.py              # Authentication
│   └── error_handler.py     # Error handling
├── services/
│   ├── google_sync.py       # Google Sheets sync
│   ├── scheduler.py         # Background tasks
│   └── parser.py            # DTEK parser
├── tests/
│   ├── conftest.py          # Pytest fixtures
│   ├── test_config.py       # Config tests
│   └── ...                  # More tests
├── utils/
│   └── ...                  # Utility functions
├── admin_bot.py             # Admin bot (separate)
├── config.py                # Configuration
├── main.py                  # Main entry point
├── pyproject.toml           # Project config
├── requirements.txt         # Dependencies
├── Dockerfile               # Docker image
├── docker-compose.yml       # Local development
└── .pre-commit-config.yaml  # Pre-commit hooks
```

### Модулі

- **database/** - Вся робота з базою даних (SQLite/PostgreSQL)
- **handlers/** - Telegram bot handlers (обробка повідомлень та callback)
- **services/** - Бізнес-логіка (синхронізація, планувальник)
- **middlewares/** - aiogram middlewares
- **keyboards/** - Inline клавіатури
- **utils/** - Допоміжні функції
- **tests/** - Unit та integration тести

---

## ✅ Тестування

### Запуск тестів

```bash
# Всі тести
pytest

# З виведенням print()
pytest -s

# Конкретний файл
pytest tests/test_config.py

# Конкретний тест
pytest tests/test_config.py::TestConfigLoading::test_bot_token_loaded

# З markers
pytest -m unit              # Тільки unit тести
pytest -m integration       # Тільки integration
pytest -m "not slow"        # Без повільних тестів
```

### Coverage

```bash
# Запустити з coverage
pytest --cov

# Генерувати HTML звіт
pytest --cov --cov-report=html

# Відкрити звіт
open htmlcov/index.html  # Mac/Linux
start htmlcov/index.html # Windows

# Перевірити конкретний модуль
pytest --cov=database --cov-report=term-missing
```

### Написання тестів

**Fixture приклад:**

```python
import pytest
from unittest.mock import AsyncMock

@pytest_asyncio.fixture
async def mock_bot():
    """Mock Telegram bot."""
    bot = AsyncMock()
    bot.send_message = AsyncMock()
    return bot

@pytest.mark.asyncio
async def test_something(mock_bot):
    """Test with async mock."""
    await mock_bot.send_message(chat_id=123, text="test")
    mock_bot.send_message.assert_called_once()
```

---

## 🧹 Якість коду

### Linting

```bash
# Ruff - швидкий linter
ruff check .
ruff check . --fix  # Автоматичне виправлення

# Black - форматування
black .
black --check .  # Перевірка без змін

# isort - сортування importів
isort .
isort --check-only .

# mypy - типізація
mypy .
mypy database/  # Конкретна папка
```

### Pre-commit Hooks

Автоматично запускаються перед кожним commit:

```bash
# Встановити hooks
pre-commit install

# Запустити вручну на всіх файлах
pre-commit run --all-files

# Оновити hooks
pre-commit autoupdate

# Пропустити hooks (не рекомендується)
git commit --no-verify
```

**Що перевіряють hooks:**
- Trailing whitespace
- End of file
- YAML/JSON syntax
- Black formatting
- isort import order
- Ruff linting
- mypy type checks
- Bandit security

---

## 📏 Стандарти коду

### Python Style Guide

- **PEP 8** - базовий style guide
- **Black** - автоматичне форматування (120 символів)
- **Type hints** - обов'язково для нового коду

### Naming Conventions

```python
# Функції та змінні: snake_case
def calculate_fuel_consumption(hours: float) -> float:
    total_fuel = hours * FUEL_RATE
    return total_fuel

# Класи: PascalCase
class GeneratorState:
    pass

# Константи: UPPER_CASE
MAX_RETRIES = 3
DEFAULT_TIMEOUT = 30

# Private: префікс _
def _internal_helper():
    pass

# Async функції: так само snake_case
async def fetch_data() -> dict:
    pass
```

### Docstrings

```python
def complex_function(param1: str, param2: int) -> bool:
    """Короткий опис функції.

    Детальний опис того, що робить функція.

    Args:
        param1: Опис першого параметру
        param2: Опис другого параметру

    Returns:
        Опис повертаємого значення

    Raises:
        ValueError: Коли param2 негативний
    """
    if param2 < 0:
        raise ValueError("param2 must be positive")
    return True
```

### Type Hints

```python
from typing import Optional, List, Dict, Any, Union
from collections.abc import Callable, Awaitable

# Прості типи
def get_user_id(user_id: int) -> str:
    return str(user_id)

# Optional
def find_user(user_id: int) -> Optional[dict]:
    return None

# List/Dict
def get_admins() -> List[int]:
    return [123, 456]

def get_state() -> Dict[str, Any]:
    return {"status": "ON", "fuel": 50.0}

# Async
async def fetch_data() -> Dict[str, Any]:
    return {}

# Callback types
Async Handler = Callable[[int, str], Awaitable[None]]

async def register_handler(handler: AsyncHandler) -> None:
    await handler(123, "test")
```

---

## 🌱 Git Workflow

### Branching Strategy

- **main** - production-ready code
- **feature/*** - новий функціонал
- **fix/*** - bug fixes
- **refactor/*** - рефакторинг
- **docs/*** - документація

### Commit Messages

Використовуємо [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(scope): додано новий функціонал
fix(scope): виправлено помилку
refactor(scope): рефакторинг коду
docs(scope): оновлено документацію
test(scope): додано тести
ci(scope): зміни в CI/CD
```

**Приклади:**

```bash
git commit -m "feat(database): add PostgreSQL connection pooling"
git commit -m "fix(handlers): resolve race condition in fuel tracking"
git commit -m "docs(deployment): add AWS deployment guide"
git commit -m "test(database): add unit tests for state management"
```

### Pull Request Workflow

1. **Створити feature branch**
```bash
git checkout -b feature/my-new-feature
```

2. **Розробка + тести**
```bash
# Зробити зміни
# Додати тести
pytest
pre-commit run --all-files
```

3. **Commit та push**
```bash
git add .
git commit -m "feat(scope): description"
git push origin feature/my-new-feature
```

4. **Створити Pull Request**
   - Описати зміни
   - Переконатись, що CI пройшов
   - Чекати code review

5. **Merge в main**
   - Squash and merge (для чистого history)

---

## 📚 Корисні команди

```bash
# Перевірка коду (все разом)
make lint  # або вручну:
ruff check . && black --check . && isort --check-only . && mypy .

# Автофікс
make format  # або:
ruff check . --fix && black . && isort .

# Тести + coverage
make test  # або:
pytest --cov --cov-report=html

# Повна перевірка (pre-commit + tests)
make check  # або:
pre-commit run --all-files && pytest

# Очистити кеші
make clean  # або:
find . -type d -name "__pycache__" -exec rm -rf {} +
find . -type d -name ".pytest_cache" -exec rm -rf {} +
find . -type d -name ".mypy_cache" -exec rm -rf {} +
rm -rf htmlcov/ .coverage coverage.xml
```

---

## 🐛 Дебагінг

### VSCode

Створіть `.vscode/launch.json`:

```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Python: Bot",
      "type": "python",
      "request": "launch",
      "program": "${workspaceFolder}/main.py",
      "console": "integratedTerminal",
      "envFile": "${workspaceFolder}/.env"
    },
    {
      "name": "Python: Tests",
      "type": "python",
      "request": "launch",
      "module": "pytest",
      "args": ["-v", "-s"],
      "console": "integratedTerminal"
    }
  ]
}
```

### PyCharm

1. Run/Debug Configurations
2. Add new Python configuration
3. Script path: `main.py`
4. Environment variables: Load from `.env`

---

## 🤝 Contributing

1. Fork репозиторій
2. Створити feature branch
3. Зробити зміни + додати тести
4. Переконатись, що всі перевірки пройшли
5. Створити Pull Request

**Вимоги до PR:**
- Чіткий опис змін
- Тести для нового коду
- Оновлена документація
- CI пройшов успішно
- Code review approved

---

## 📞 Підтримка

- Issues: https://github.com/imeromua/generator_bot/issues
- Discussions: https://github.com/imeromua/generator_bot/discussions
