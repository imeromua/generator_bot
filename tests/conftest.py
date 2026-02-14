"""Pytest configuration and fixtures."""
import pytest
import os
from pathlib import Path


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    """Clean environment variables and .env file before each test."""
    # Remove .env file if it exists to prevent interference
    env_file = Path(".env")
    if env_file.exists():
        env_file.unlink()
    
    # Remove all bot-related env vars to ensure test isolation
    env_vars_to_clean = [
        "BOT_TOKEN",
        "MODE",
        "ADMINS",
        "USERS",
        "BOT_STATUS",
        "DB_BACKEND",
        "SQLITE_PATH",
        "POSTGRES_DSN",
        "POSTGRES_ADMIN_DSN",
        "PG_POOL_MIN_SIZE",
        "PG_POOL_MAX_SIZE",
        "PG_POOL_TIMEOUT",
        "PG_POOL_MAX_IDLE",
        "REDIS_ENABLED",
        "REDIS_URL",
        "SHEET_ID_PROD",
        "SHEET_ID_TEST",
        "SHEETS_RUNTIME_ENABLED",
        "SERVICE_ACCOUNT_PATH",
        "SHEET_NAME",
        "LOGS_SHEET_NAME",
        "LOG_FILE",
        "LOG_LEVEL",
        "LOG_MAX_BYTES",
        "LOG_BACKUP_COUNT",
        "TIMEZONE",
        "WORK_START",
        "WORK_END",
        "BRIEF_TIME",
        "OIL_CHANGE_INTERVAL",
        "SPARK_CHANGE_INTERVAL",
        "MAINTENANCE_INTERVAL",
        "OIL_LIMIT",
        "FUEL_CONSUMPTION",
        "FUEL_RATE",
        "EMERGENCY_FUEL_CONSUMPTION",
        "FUEL_ALERT_THRESHOLD",
        "FUEL_ALERT_COOLDOWN_MIN",
        "STOP_REMINDER_MIN",
    ]
    
    for var in env_vars_to_clean:
        monkeypatch.delenv(var, raising=False)
    
    yield
    
    # Cleanup after test
    if env_file.exists():
        env_file.unlink()


@pytest.fixture
def temp_env_file(tmp_path):
    """Create a temporary .env file for testing."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "BOT_TOKEN=test_token_123\n"
        "MODE=TEST\n"
        "ADMINS=123,456\n"
        "SHEET_ID_PROD=test_prod\n"
        "SHEET_ID_TEST=test_test\n"
    )
    return env_file


@pytest.fixture
def mock_required_env(monkeypatch):
    """Set required environment variables for Settings initialization."""
    monkeypatch.setenv("BOT_TOKEN", "test_token")
    monkeypatch.setenv("SHEET_ID_PROD", "prod_sheet")
    monkeypatch.setenv("SHEET_ID_TEST", "test_sheet")
    monkeypatch.setenv("ADMINS", "123456789")
    return monkeypatch
