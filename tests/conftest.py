"""Pytest configuration and shared fixtures."""
import asyncio
import os
import sys
from pathlib import Path
from typing import AsyncGenerator, Generator
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session", autouse=True)
def setup_test_env() -> Generator[None, None, None]:
    """Setup test environment variables."""
    # Store original env
    original_env = os.environ.copy()

    # Set test environment
    test_env = {
        "BOT_TOKEN": "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
        "SHEET_ID_PROD": "test_sheet_id_prod",
        "SHEET_ID_TEST": "test_sheet_id_test",
        "ADMINS": "123456789,987654321",
        "MODE": "TEST",
        "DB_BACKEND": "sqlite",
        "SQLITE_PATH": ":memory:",
        "REDIS_ENABLED": "0",
        "SHEETS_RUNTIME_ENABLED": "0",
        "TIMEZONE": "Europe/Kyiv",
        "WORK_START": "07:30",
        "WORK_END": "20:30",
        "FUEL_CONSUMPTION": "0.8",
        "EMERGENCY_FUEL_CONSUMPTION": "0.9",
        "LOG_LEVEL": "ERROR",  # Suppress logs in tests
    }

    os.environ.update(test_env)

    yield

    # Restore original environment
    os.environ.clear()
    os.environ.update(original_env)


@pytest_asyncio.fixture
async def bot() -> AsyncGenerator[Bot, None]:
    """Create mock bot instance."""
    bot_instance = AsyncMock(spec=Bot)
    bot_instance.id = 123456789
    bot_instance.token = "test_token"
    bot_instance.session = AsyncMock()
    yield bot_instance
    await bot_instance.session.close()


@pytest_asyncio.fixture
async def dispatcher() -> AsyncGenerator[Dispatcher, None]:
    """Create dispatcher with memory storage."""
    dp = Dispatcher(storage=MemoryStorage())
    yield dp
    await dp.storage.close()


@pytest.fixture
def mock_db() -> Generator[MagicMock, None, None]:
    """Mock database operations."""
    mock = MagicMock()
    mock.init_db = MagicMock()
    mock.get_state = MagicMock(return_value={
        "status": "OFF",
        "current_fuel": 50.0,
        "motor_hours": 100.0,
        "active_generator": "main",
    })
    mock.set_state = MagicMock()
    mock.add_log = MagicMock()
    mock.get_last_logs = MagicMock(return_value=[])
    yield mock


@pytest.fixture
def mock_sheets() -> Generator[MagicMock, None, None]:
    """Mock Google Sheets operations."""
    mock = MagicMock()
    mock.sync_bidirectional = AsyncMock(return_value={
        "exported": 0,
        "imported": 0,
        "conflicts": 0,
        "warnings": [],
    })
    mock.get_worksheet = MagicMock()
    yield mock


@pytest.fixture
def sample_user_id() -> int:
    """Sample user ID for testing."""
    return 123456789


@pytest.fixture
def sample_admin_id() -> int:
    """Sample admin ID for testing."""
    return 987654321


@pytest.fixture
def sample_generator_state() -> dict:
    """Sample generator state for testing."""
    return {
        "status": "OFF",
        "current_fuel": 50.0,
        "motor_hours": 100.0,
        "motor_hours_emergency": 50.0,
        "last_start": None,
        "active_shift": None,
        "active_operator": None,
        "active_generator": "main",
        "last_fuel_alert": None,
        "sync_lock": False,
    }


@pytest.fixture
def sample_log_entry() -> dict:
    """Sample log entry for testing."""
    return {
        "log_id": 1,
        "timestamp": "2026-02-13T19:00:00",
        "event_type": "m_start",
        "actor": "Test User",
        "value": None,
        "driver": None,
        "receipt_number": None,
        "generator_id": "main",
    }
