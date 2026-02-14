"""Configuration module using Pydantic for type-safe settings.

This module loads configuration from environment variables (.env file)
and provides type-safe access to all bot settings.

All settings are validated at startup with Pydantic, providing:
- Type safety
- Validation
- Clear error messages
- Nested configuration
- Backward compatibility

Important:
- The module must be importable even when required environment variables are not set
  (e.g. during test collection).
- Validation of required runtime variables is performed by validate_env().
"""

from pathlib import Path
from typing import Literal, Optional
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_SETTINGS_BASE_CONFIG = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)
_SETTINGS_NESTED_CONFIG = SettingsConfigDict(
    env_file=".env",
    env_nested_delimiter="__",
    extra="ignore",
    populate_by_name=True,
)


class DatabaseSettings(BaseSettings):
    """Database configuration."""

    backend: Literal["sqlite", "postgres"] = Field(default="sqlite", alias="DB_BACKEND")
    sqlite_path: str = Field(default="generator.db", alias="SQLITE_PATH")
    postgres_dsn: str = Field(default="", alias="POSTGRES_DSN")
    postgres_admin_dsn: str = Field(default="", alias="POSTGRES_ADMIN_DSN")

    # PostgreSQL Connection Pool
    pg_pool_min_size: int = Field(default=2, ge=1, alias="PG_POOL_MIN_SIZE")
    pg_pool_max_size: int = Field(default=10, ge=1, alias="PG_POOL_MAX_SIZE")
    pg_pool_timeout: int = Field(default=30, ge=1, alias="PG_POOL_TIMEOUT")
    pg_pool_max_idle: int = Field(default=300, ge=1, alias="PG_POOL_MAX_IDLE")

    @field_validator("backend")
    @classmethod
    def validate_backend(cls, v: str) -> str:
        """Normalize backend to lowercase."""
        return v.strip().lower()

    @model_validator(mode="after")
    def validate_postgres_config(self) -> "DatabaseSettings":
        """Check psycopg is installed when using postgres."""
        if self.backend == "postgres":
            if not self.postgres_dsn:
                raise ValueError("POSTGRES_DSN is required when DB_BACKEND=postgres")
            try:
                import psycopg  # noqa: F401
            except ImportError as e:
                raise ImportError(
                    "DB_BACKEND=postgres requires 'psycopg' module. "
                    "Install with: pip install psycopg[binary]"
                ) from e
        return self

    model_config = _SETTINGS_BASE_CONFIG


class RedisSettings(BaseSettings):
    """Redis configuration."""

    enabled: bool = Field(default=False, alias="REDIS_ENABLED")
    url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")

    @model_validator(mode="after")
    def validate_redis_url(self) -> "RedisSettings":
        """Ensure REDIS_URL is set when enabled."""
        if self.enabled and not self.url:
            raise ValueError("REDIS_URL is required when REDIS_ENABLED=true")
        return self

    model_config = _SETTINGS_BASE_CONFIG


class SheetsSettings(BaseSettings):
    """Google Sheets configuration."""

    runtime_enabled: bool = Field(default=True, alias="SHEETS_RUNTIME_ENABLED")
    service_account_path: Path = Field(default=Path("service_account.json"), alias="SERVICE_ACCOUNT_PATH")

    # Keep defaults to allow importing module during tests without env.
    sheet_id_prod: str = Field(default="", alias="SHEET_ID_PROD")
    sheet_id_test: str = Field(default="", alias="SHEET_ID_TEST")

    sheet_name: str = Field(default="ЛЮТИЙ", alias="SHEET_NAME")
    logs_sheet_name: str = Field(default="ПОДІЇ", alias="LOGS_SHEET_NAME")

    model_config = _SETTINGS_BASE_CONFIG


class LoggingSettings(BaseSettings):
    """Logging configuration."""

    log_file: str = Field(default="bot.log", alias="LOG_FILE")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(default="INFO", alias="LOG_LEVEL")
    log_max_bytes: int = Field(default=10485760, ge=1024, alias="LOG_MAX_BYTES")  # 10MB
    log_backup_count: int = Field(default=5, ge=0, alias="LOG_BACKUP_COUNT")

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Normalize log level to uppercase."""
        return v.upper()

    model_config = _SETTINGS_BASE_CONFIG


class WorkScheduleSettings(BaseSettings):
    """Work schedule configuration."""

    timezone: str = Field(default="Europe/Kyiv", alias="TIMEZONE")
    work_start_time: str = Field(default="07:30", alias="WORK_START")
    work_end_time: str = Field(default="20:30", alias="WORK_END")
    morning_brief_time: str = Field(default="07:30", alias="BRIEF_TIME")

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v: str) -> str:
        """Validate timezone string."""
        try:
            ZoneInfo(v)
        except Exception:
            print(f"⚠️ Invalid timezone '{v}', falling back to UTC")
            return "UTC"
        return v

    @field_validator("work_start_time", "work_end_time", "morning_brief_time")
    @classmethod
    def validate_time_format(cls, v: str) -> str:
        """Validate HH:MM time format."""
        if ":" not in v:
            raise ValueError(f"Time must be in HH:MM format, got: {v}")
        parts = v.split(":")
        if len(parts) != 2:
            raise ValueError(f"Time must be in HH:MM format, got: {v}")
        try:
            hours, minutes = int(parts[0]), int(parts[1])
            if not (0 <= hours < 24 and 0 <= minutes < 60):
                raise ValueError(f"Invalid time: {v}")
        except ValueError as e:
            raise ValueError(f"Invalid time format: {v}") from e
        return v

    model_config = _SETTINGS_BASE_CONFIG


class MaintenanceSettings(BaseSettings):
    """Maintenance intervals configuration."""

    oil_change_interval: int = Field(default=100, gt=0, alias="OIL_CHANGE_INTERVAL")
    spark_change_interval: int = Field(default=100, gt=0, alias="SPARK_CHANGE_INTERVAL")
    maintenance_interval: int = Field(default=300, gt=0, alias="MAINTENANCE_INTERVAL")

    # Backward compatibility
    oil_limit: Optional[int] = Field(default=None, gt=0, alias="OIL_LIMIT")

    @model_validator(mode="after")
    def set_oil_limit_compat(self) -> "MaintenanceSettings":
        """Set MAINTENANCE_LIMIT for backward compatibility."""
        if self.oil_limit is None:
            self.oil_limit = self.oil_change_interval
        return self

    model_config = _SETTINGS_BASE_CONFIG


class FuelSettings(BaseSettings):
    """Fuel consumption and alerts configuration."""

    # Main generator
    fuel_consumption: float = Field(default=5.3, gt=0, alias="FUEL_CONSUMPTION")
    fuel_rate: Optional[float] = Field(default=None, gt=0, alias="FUEL_RATE")  # Alias for backward compat

    # Emergency generator
    emergency_fuel_consumption: Optional[float] = Field(default=None, gt=0, alias="EMERGENCY_FUEL_CONSUMPTION")

    # Alerts
    fuel_alert_threshold: float = Field(default=40.0, gt=0, alias="FUEL_ALERT_THRESHOLD")
    fuel_alert_cooldown_min: int = Field(default=60, gt=0, alias="FUEL_ALERT_COOLDOWN_MIN")
    stop_reminder_min: int = Field(default=15, gt=0, alias="STOP_REMINDER_MIN")

    @model_validator(mode="after")
    def handle_fuel_aliases(self) -> "FuelSettings":
        """Handle FUEL_RATE alias and set emergency defaults."""
        if self.fuel_rate is not None:
            self.fuel_consumption = self.fuel_rate

        if self.emergency_fuel_consumption is None:
            self.emergency_fuel_consumption = self.fuel_consumption

        return self

    model_config = _SETTINGS_BASE_CONFIG


class AccessSettings(BaseSettings):
    """Access control configuration."""

    # Keep defaults to allow module import during tests.
    admins: str = Field(default="", alias="ADMINS")  # Comma-separated list
    bot_status: Literal["ON", "OFF"] = Field(default="ON", alias="BOT_STATUS")
    users: str = Field(default="", alias="USERS")  # Comma-separated whitelist

    @field_validator("admins", "users")
    @classmethod
    def validate_id_list(cls, v: str) -> str:
        """Validate comma-separated ID list."""
        if not v.strip():
            return ""
        try:
            [int(x.strip()) for x in v.split(",") if x.strip()]
        except ValueError as e:
            raise ValueError(f"Invalid user ID list format: {v}") from e
        return v

    def get_admin_ids(self) -> list[int]:
        """Parse admin IDs from string."""
        if not self.admins.strip():
            return []
        return [int(x.strip()) for x in self.admins.split(",") if x.strip()]

    def get_whitelist(self) -> list[int]:
        """Parse whitelist IDs from string."""
        if not self.users.strip():
            return []
        return [int(x.strip()) for x in self.users.split(",") if x.strip()]

    @property
    def registration_open(self) -> bool:
        """Check if registration is open."""
        return self.bot_status == "ON"

    model_config = _SETTINGS_BASE_CONFIG


class Settings(BaseSettings):
    """Main application settings."""

    # Core (keep defaults to make module import safe; validate_env() enforces them for runtime)
    bot_token: str = Field(default="", alias="BOT_TOKEN")
    mode: Literal["TEST", "PROD"] = Field(default="TEST", alias="MODE")

    # Nested settings
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    sheets: SheetsSettings = Field(default_factory=SheetsSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    schedule: WorkScheduleSettings = Field(default_factory=WorkScheduleSettings)
    maintenance: MaintenanceSettings = Field(default_factory=MaintenanceSettings)
    fuel: FuelSettings = Field(default_factory=FuelSettings)
    access: AccessSettings = Field(default_factory=AccessSettings)

    @property
    def is_test_mode(self) -> bool:
        """Check if running in test mode."""
        return self.mode == "TEST"

    @property
    def sheet_id(self) -> str:
        """Get current sheet ID based on mode."""
        return self.sheets.sheet_id_test if self.is_test_mode else self.sheets.sheet_id_prod

    @property
    def kyiv_tz(self) -> ZoneInfo:
        """Get configured timezone as ZoneInfo."""
        return ZoneInfo(self.schedule.timezone)

    def validate_all(self) -> None:
        """Validate all configuration (for backward compatibility with validate_env())."""
        if self.is_test_mode:
            print("⚠️  УВАГА: Бот запущено в ТЕСТОВОМУ режимі (SHEET_ID_TEST)")

    def print_config(self) -> None:
        """Print current configuration (for debugging)."""
        print("\n" + "=" * 60)
        print("📋 ПОТОЧНА КОНФІГУРАЦІЯ")
        print("=" * 60)
        print(f"Режим: {'TEST' if self.is_test_mode else 'PROD'}")
        print(f"Log Level: {self.logging.log_level}")
        print(
            f"Log File: {self.logging.log_file} "
            f"(Max: {self.logging.log_max_bytes/1024/1024:.1f} MB, "
            f"Backups: {self.logging.log_backup_count})"
        )
        print(f"DB backend: {self.database.backend}")
        if self.database.backend == "sqlite":
            print(f"SQLite path: {self.database.sqlite_path}")
        if self.database.backend == "postgres":
            print(f"Postgres DSN: {'(set)' if self.database.postgres_dsn else '(missing)'}")
            print(
                f"Connection pool: min={self.database.pg_pool_min_size}, "
                f"max={self.database.pg_pool_max_size}, "
                f"timeout={self.database.pg_pool_timeout}s, "
                f"max_idle={self.database.pg_pool_max_idle}s"
            )
        print(f"Redis enabled: {self.redis.enabled}")
        print(f"Sheets runtime enabled: {self.sheets.runtime_enabled}")
        print(f"Service account path: {self.sheets.service_account_path}")
        print(f"Таблиця: {self.sheets.sheet_name}")
        print(f"ID таблиці: {self.sheet_id}")
        print(f"Вкладка логів: {self.sheets.logs_sheet_name}")
        print(f"Адміни: {self.access.get_admin_ids()}")
        print(f"Витрата палива (основний): {self.fuel.fuel_consumption} л/год")
        print(f"Витрата палива (аварійний): {self.fuel.emergency_fuel_consumption} л/год")
        print("Інтервали ТО:")
        print(f"  Мастило: {self.maintenance.oil_change_interval} год")
        print(f"  Свічки: {self.maintenance.spark_change_interval} год")
        print(f"  Планове ТО: {self.maintenance.maintenance_interval} год")
        print(f"Таймзона: {self.kyiv_tz}")
        print("=" * 60 + "\n")

    model_config = _SETTINGS_NESTED_CONFIG


# ==========================================
# Global settings instance (singleton)
# ==========================================
_SETTINGS_LOAD_ERROR: Exception | None = None
try:
    settings = Settings()
except Exception as e:
    # Do not fail module import (important for test collection).
    # Runtime should call validate_env() and receive a clear error.
    _SETTINGS_LOAD_ERROR = e
    settings = Settings(
        bot_token="",
        sheets=SheetsSettings(sheet_id_prod="", sheet_id_test=""),
        access=AccessSettings(admins=""),
    )


# ==========================================
# Backward compatibility exports
# ==========================================

# Core
BOT_TOKEN = settings.bot_token
MODE = settings.mode
IS_TEST_MODE = settings.is_test_mode

# Database
DB_BACKEND = settings.database.backend
SQLITE_PATH = settings.database.sqlite_path
POSTGRES_DSN = settings.database.postgres_dsn
POSTGRES_ADMIN_DSN = settings.database.postgres_admin_dsn
PG_POOL_MIN_SIZE = settings.database.pg_pool_min_size
PG_POOL_MAX_SIZE = settings.database.pg_pool_max_size
PG_POOL_TIMEOUT = settings.database.pg_pool_timeout
PG_POOL_MAX_IDLE = settings.database.pg_pool_max_idle

# Redis
REDIS_ENABLED = settings.redis.enabled
REDIS_URL = settings.redis.url

# Sheets
SHEETS_RUNTIME_ENABLED = settings.sheets.runtime_enabled
SERVICE_ACCOUNT_PATH = str(settings.sheets.service_account_path)
SHEET_ID = settings.sheet_id
SHEET_NAME = settings.sheets.sheet_name
LOGS_SHEET_NAME = settings.sheets.logs_sheet_name

# Logging
LOG_FILE = settings.logging.log_file
LOG_LEVEL = settings.logging.log_level
LOG_MAX_BYTES = settings.logging.log_max_bytes
LOG_BACKUP_COUNT = settings.logging.log_backup_count

# Schedule
TIMEZONE = settings.schedule.timezone
KYIV = settings.kyiv_tz
WORK_START_TIME = settings.schedule.work_start_time
WORK_END_TIME = settings.schedule.work_end_time
MORNING_BRIEF_TIME = settings.schedule.morning_brief_time

# Maintenance
OIL_CHANGE_INTERVAL = settings.maintenance.oil_change_interval
SPARK_CHANGE_INTERVAL = settings.maintenance.spark_change_interval
MAINTENANCE_INTERVAL = settings.maintenance.maintenance_interval
MAINTENANCE_LIMIT = settings.maintenance.oil_limit or settings.maintenance.oil_change_interval

# Fuel
FUEL_CONSUMPTION = settings.fuel.fuel_consumption
EMERGENCY_FUEL_CONSUMPTION = settings.fuel.emergency_fuel_consumption or settings.fuel.fuel_consumption
FUEL_ALERT_THRESHOLD_L = settings.fuel.fuel_alert_threshold
FUEL_ALERT_COOLDOWN_MIN = settings.fuel.fuel_alert_cooldown_min
STOP_REMINDER_MIN_BEFORE_END = settings.fuel.stop_reminder_min

# Access
ADMIN_IDS = settings.access.get_admin_ids()
BOT_STATUS = settings.access.bot_status
REGISTRATION_OPEN = settings.access.registration_open
WHITELIST = settings.access.get_whitelist()


def validate_env() -> None:
    """Validate environment configuration (backward compatibility).

    Pydantic validates on Settings init, but we additionally enforce required
    runtime variables here.
    """
    if _SETTINGS_LOAD_ERROR is not None:
        raise RuntimeError(f"Configuration error: {_SETTINGS_LOAD_ERROR}") from _SETTINGS_LOAD_ERROR

    errors: list[str] = []

    if not settings.bot_token.strip():
        errors.append("BOT_TOKEN is required")

    # Sheets IDs are required only when sheets runtime is enabled.
    if settings.sheets.runtime_enabled:
        if not settings.sheets.sheet_id_prod.strip():
            errors.append("SHEET_ID_PROD is required when SHEETS_RUNTIME_ENABLED=true")
        if not settings.sheets.sheet_id_test.strip():
            errors.append("SHEET_ID_TEST is required when SHEETS_RUNTIME_ENABLED=true")

    if not settings.access.admins.strip():
        errors.append("ADMINS is required")

    if errors:
        raise RuntimeError("Invalid environment:\n- " + "\n- ".join(errors))

    settings.validate_all()


def _env_bool(name: str, default: bool = False) -> bool:
    """Legacy helper for boolean env vars (kept for compatibility)."""
    import os

    v = os.getenv(name)
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "y", "on")


if __name__ == "__main__":
    settings.print_config()
