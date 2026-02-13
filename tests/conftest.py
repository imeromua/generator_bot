"""Pytest configuration and fixtures."""
import pytest
import os
from pathlib import Path


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Clean environment variables before each test."""
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
        "REDIS_ENABLED",
        "REDIS_URL",
        "SHEET_ID_PROD",
        "SHEET_ID_TEST",
        "LOG_LEVEL",
        "FUEL_CONSUMPTION",
        "EMERGENCY_FUEL_CONSUMPTION",
    ]
    
    for var in env_vars_to_clean:
        monkeypatch.delenv(var, raising=False)
    
    yield


@pytest.fixture
def temp_env_file(tmp_path):
    """Create a temporary .env file for testing."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "BOT_TOKEN=test_token_123\n"
        "MODE=TEST\n"
        "ADMINS=123,456\n"
    )
    return env_file
