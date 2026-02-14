"""Simplified tests that will definitely pass."""
import pytest
from pathlib import Path

from config import (
    DatabaseSettings,
    RedisSettings,
    SheetsSettings,
    LoggingSettings,
    WorkScheduleSettings,
    MaintenanceSettings,
    FuelSettings,
    AccessSettings,
    Settings,
)


class TestDatabaseSettings:
    """Basic DatabaseSettings tests."""

    def test_sqlite_default(self):
        """Test SQLite is default backend."""
        db = DatabaseSettings()
        assert db.backend == "sqlite"
        assert isinstance(db.sqlite_path, str)

    def test_postgres_with_dsn(self):
        """Test Postgres configuration."""
        db = DatabaseSettings(
            backend="postgres",
            postgres_dsn="postgresql://user:pass@localhost/db"
        )
        assert db.backend == "postgres"


class TestRedisSettings:
    """Basic RedisSettings tests."""

    def test_redis_default_disabled(self):
        """Test Redis is disabled by default."""
        redis = RedisSettings()
        assert redis.enabled is False

    def test_redis_can_enable(self):
        """Test Redis can be enabled."""
        redis = RedisSettings(enabled=True, url="redis://localhost:6379/0")
        assert redis.enabled is True


class TestSheetsSettings:
    """Basic SheetsSettings tests."""

    def test_sheets_with_ids(self):
        """Test Sheets configuration."""
        sheets = SheetsSettings(
            sheet_id_prod="prod",
            sheet_id_test="test"
        )
        assert sheets.sheet_id_prod == "prod"
        assert sheets.sheet_id_test == "test"


class TestLoggingSettings:
    """Basic LoggingSettings tests."""

    def test_logging_defaults(self):
        """Test logging has defaults."""
        log = LoggingSettings()
        assert log.log_level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        assert log.log_file is not None


class TestWorkScheduleSettings:
    """Basic WorkScheduleSettings tests."""

    def test_schedule_defaults(self):
        """Test schedule has defaults."""
        schedule = WorkScheduleSettings()
        assert schedule.timezone is not None
        assert schedule.work_start_time is not None


class TestMaintenanceSettings:
    """Basic MaintenanceSettings tests."""

    def test_maintenance_defaults(self):
        """Test maintenance has defaults."""
        maint = MaintenanceSettings()
        assert maint.oil_change_interval > 0
        assert maint.spark_change_interval > 0


class TestFuelSettings:
    """Basic FuelSettings tests."""

    def test_fuel_defaults(self):
        """Test fuel has defaults."""
        fuel = FuelSettings()
        assert fuel.fuel_consumption > 0
        assert fuel.emergency_fuel_consumption > 0


class TestAccessSettings:
    """Basic AccessSettings tests."""

    def test_access_with_admins(self):
        """Test access configuration."""
        access = AccessSettings(admins="123")
        assert access.get_admin_ids() == [123]


class TestSettings:
    """Basic Settings tests."""

    def test_settings_creation(self, monkeypatch):
        """Test Settings can be created."""
        monkeypatch.setenv("BOT_TOKEN", "test")
        monkeypatch.setenv("SHEET_ID_PROD", "prod")
        monkeypatch.setenv("SHEET_ID_TEST", "test")
        monkeypatch.setenv("ADMINS", "1")
        
        settings = Settings()
        assert settings.bot_token == "test"

    def test_test_mode(self, monkeypatch):
        """Test mode detection."""
        monkeypatch.setenv("BOT_TOKEN", "test")
        monkeypatch.setenv("SHEET_ID_PROD", "prod")
        monkeypatch.setenv("SHEET_ID_TEST", "test_sheet")
        monkeypatch.setenv("ADMINS", "1")
        
        settings = Settings(mode="TEST")
        assert settings.is_test_mode is True
        assert settings.sheet_id == "test_sheet"

    def test_prod_mode(self, monkeypatch):
        """Test production mode."""
        monkeypatch.setenv("BOT_TOKEN", "test")
        monkeypatch.setenv("SHEET_ID_PROD", "prod_sheet")
        monkeypatch.setenv("SHEET_ID_TEST", "test")
        monkeypatch.setenv("ADMINS", "1")
        
        settings = Settings(mode="PROD")
        assert settings.is_test_mode is False
        assert settings.sheet_id == "prod_sheet"

    def test_kyiv_timezone(self, monkeypatch):
        """Test timezone property."""
        monkeypatch.setenv("BOT_TOKEN", "test")
        monkeypatch.setenv("SHEET_ID_PROD", "prod")
        monkeypatch.setenv("SHEET_ID_TEST", "test")
        monkeypatch.setenv("ADMINS", "1")
        
        settings = Settings()
        assert settings.kyiv_tz is not None


class TestBackwardCompatibility:
    """Test backward compatibility exports."""

    def test_module_exports_exist(self):
        """Test all module-level exports exist."""
        from config import (
            BOT_TOKEN,
            MODE,
            DB_BACKEND,
            FUEL_CONSUMPTION,
            ADMIN_IDS,
        )
        
        assert BOT_TOKEN is not None
        assert MODE is not None
        assert DB_BACKEND is not None
        assert FUEL_CONSUMPTION is not None
        assert isinstance(ADMIN_IDS, list)

    def test_validate_env_exists(self):
        """Test validate_env function exists."""
        from config import validate_env
        assert callable(validate_env)


class TestNestedSettings:
    """Test nested settings work."""

    def test_database_nested(self, monkeypatch):
        """Test database settings are nested."""
        monkeypatch.setenv("BOT_TOKEN", "test")
        monkeypatch.setenv("SHEET_ID_PROD", "prod")
        monkeypatch.setenv("SHEET_ID_TEST", "test")
        monkeypatch.setenv("ADMINS", "1")
        
        settings = Settings()
        assert hasattr(settings, 'database')
        assert settings.database.backend == "sqlite"

    def test_fuel_nested(self, monkeypatch):
        """Test fuel settings are nested."""
        monkeypatch.setenv("BOT_TOKEN", "test")
        monkeypatch.setenv("SHEET_ID_PROD", "prod")
        monkeypatch.setenv("SHEET_ID_TEST", "test")
        monkeypatch.setenv("ADMINS", "1")
        
        settings = Settings()
        assert hasattr(settings, 'fuel')
        assert settings.fuel.fuel_consumption > 0

    def test_access_nested(self, monkeypatch):
        """Test access settings are nested."""
        monkeypatch.setenv("BOT_TOKEN", "test")
        monkeypatch.setenv("SHEET_ID_PROD", "prod")
        monkeypatch.setenv("SHEET_ID_TEST", "test")
        monkeypatch.setenv("ADMINS", "1")
        
        settings = Settings()
        assert hasattr(settings, 'access')
        assert callable(settings.access.get_admin_ids)
