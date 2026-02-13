"""Comprehensive tests for Pydantic-based configuration models."""
import pytest
from pathlib import Path
import os

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
    """Detailed tests for DatabaseSettings Pydantic model."""

    def test_default_values(self):
        """Test all default values are set correctly."""
        db = DatabaseSettings()
        assert db.backend == "sqlite"
        assert db.sqlite_path == "generator.db"
        assert db.postgres_dsn == ""
        assert db.postgres_admin_dsn == ""
        assert db.pg_pool_min_size == 2
        assert db.pg_pool_max_size == 10

    def test_postgres_requires_dsn(self):
        """Test PostgreSQL requires DSN."""
        with pytest.raises(ValueError, match="POSTGRES_DSN is required"):
            DatabaseSettings(backend="postgres", postgres_dsn="")

    def test_backend_normalization(self):
        """Test backend values are normalized to lowercase."""
        db = DatabaseSettings(backend="SQLITE")
        assert db.backend == "sqlite"

    def test_pool_constraints(self):
        """Test pool size constraints."""
        db = DatabaseSettings(
            pg_pool_min_size=5,
            pg_pool_max_size=20
        )
        assert db.pg_pool_min_size == 5
        assert db.pg_pool_max_size == 20


class TestRedisSettings:
    """Tests for RedisSettings Pydantic model."""

    def test_default_values(self):
        """Test Redis defaults to disabled."""
        redis = RedisSettings()
        assert redis.enabled is False
        assert redis.url == "redis://localhost:6379/0"

    def test_enabled_requires_url(self):
        """Test Redis requires URL when enabled."""
        with pytest.raises(ValueError, match="REDIS_URL is required"):
            RedisSettings(enabled=True, url="")

    def test_disabled_doesnt_require_url(self):
        """Test disabled Redis doesn't need URL."""
        redis = RedisSettings(enabled=False, url="")
        assert redis.enabled is False


class TestSheetsSettings:
    """Tests for SheetsSettings Pydantic model."""

    def test_requires_sheet_ids(self):
        """Test sheet IDs are required."""
        with pytest.raises(Exception):  # ValidationError
            SheetsSettings()

    def test_service_account_path(self):
        """Test service account path uses default."""
        sheets = SheetsSettings(
            sheet_id_prod="prod_id",
            sheet_id_test="test_id"
        )
        assert sheets.service_account_path == Path("service_account.json")


class TestLoggingSettings:
    """Tests for LoggingSettings Pydantic model."""

    def test_default_values(self):
        """Test logging defaults."""
        log = LoggingSettings()
        assert log.log_level == "INFO"
        assert log.log_file == "bot.log"
        assert log.log_max_bytes == 10 * 1024 * 1024
        assert log.log_backup_count == 5

    def test_log_level_normalization(self):
        """Test log level is normalized to uppercase."""
        log_debug = LoggingSettings(log_level="debug")
        assert log_debug.log_level == "DEBUG"
        
        log_info = LoggingSettings(log_level="info")
        assert log_info.log_level == "INFO"

    def test_log_level_validation(self):
        """Test invalid log level raises error."""
        with pytest.raises(Exception):  # ValidationError
            LoggingSettings(log_level="CUSTOM")

    def test_size_constraints(self):
        """Test log file size configuration."""
        log = LoggingSettings(log_max_bytes=5242880)  # 5MB
        assert log.log_max_bytes == 5242880


class TestWorkScheduleSettings:
    """Tests for WorkScheduleSettings Pydantic model."""

    def test_default_values(self):
        """Test work schedule defaults."""
        schedule = WorkScheduleSettings()
        assert schedule.timezone == "Europe/Kyiv"
        assert schedule.work_start_time == "07:30"
        assert schedule.work_end_time == "20:30"
        assert schedule.morning_brief_time == "07:30"

    def test_timezone_validation(self):
        """Test timezone accepts valid values."""
        schedule = WorkScheduleSettings(timezone="UTC")
        assert schedule.timezone == "UTC"

    def test_time_format_validation(self):
        """Test time format validation."""
        schedule = WorkScheduleSettings(
            work_start_time="09:00",
            work_end_time="18:00"
        )
        assert schedule.work_start_time == "09:00"
        assert schedule.work_end_time == "18:00"


class TestMaintenanceSettings:
    """Tests for MaintenanceSettings Pydantic model."""

    def test_default_values(self):
        """Test maintenance defaults."""
        maint = MaintenanceSettings()
        assert maint.oil_change_interval == 100
        assert maint.spark_change_interval == 100
        assert maint.maintenance_interval == 300
        assert maint.oil_limit == 100

    def test_positive_intervals(self):
        """Test positive interval values."""
        maint = MaintenanceSettings(
            oil_change_interval=150,
            spark_change_interval=200
        )
        assert maint.oil_change_interval == 150
        assert maint.spark_change_interval == 200

    def test_oil_limit_compatibility(self):
        """Test oil_limit defaults to oil_change_interval."""
        maint = MaintenanceSettings(oil_change_interval=100)
        assert maint.oil_limit == 100


class TestFuelSettings:
    """Tests for FuelSettings Pydantic model."""

    def test_default_values(self):
        """Test fuel settings defaults."""
        fuel = FuelSettings()
        assert fuel.fuel_consumption == 5.3
        assert fuel.emergency_fuel_consumption == 5.3
        assert fuel.fuel_alert_threshold == 40.0

    def test_fuel_rate_alias(self):
        """Test fuel_rate is an alias for fuel_consumption."""
        fuel = FuelSettings(fuel_rate=7.5)
        assert fuel.fuel_consumption == 7.5

    def test_emergency_fuel_default(self):
        """Test emergency fuel defaults to main consumption."""
        fuel = FuelSettings(fuel_consumption=1.2)
        assert fuel.emergency_fuel_consumption == 1.2

    def test_positive_values(self):
        """Test fuel values can be positive floats."""
        fuel = FuelSettings(
            fuel_consumption=0.5,
            emergency_fuel_consumption=0.7
        )
        assert fuel.fuel_consumption == 0.5
        assert fuel.emergency_fuel_consumption == 0.7


class TestAccessSettings:
    """Tests for AccessSettings Pydantic model."""

    def test_admin_ids_parsing(self):
        """Test admin IDs are parsed correctly."""
        access = AccessSettings(admins="111,222,333")
        assert access.get_admin_ids() == [111, 222, 333]

    def test_whitelist_parsing(self):
        """Test whitelist parsing."""
        access = AccessSettings(admins="1", users="444,555")
        result = access.get_whitelist()
        assert result == [444, 555]

    def test_empty_lists(self):
        """Test empty admin/user lists."""
        access = AccessSettings(admins="1")  # admins is required
        assert access.users == ""

    def test_invalid_id_format(self):
        """Test invalid ID format raises error."""
        with pytest.raises(ValueError, match="Invalid user ID list format"):
            AccessSettings(admins="invalid,ids")

    def test_registration_open_property(self):
        """Test registration_open property logic."""
        access_on = AccessSettings(admins="1", bot_status="ON")
        access_off = AccessSettings(admins="1", bot_status="OFF")
        
        assert access_on.registration_open is True
        assert access_off.registration_open is False


class TestMainSettings:
    """Tests for main Settings class."""

    def test_is_test_mode(self, monkeypatch):
        """Test is_test_mode property."""
        monkeypatch.setenv("BOT_TOKEN", "token")
        monkeypatch.setenv("SHEET_ID_PROD", "prod")
        monkeypatch.setenv("SHEET_ID_TEST", "test")
        monkeypatch.setenv("ADMINS", "1")
        
        settings_test = Settings(mode="TEST")
        assert settings_test.is_test_mode is True
        
        settings_prod = Settings(mode="PROD")
        assert settings_prod.is_test_mode is False

    def test_sheet_id_selection(self, monkeypatch):
        """Test sheet_id property selects correct ID based on mode."""
        monkeypatch.setenv("BOT_TOKEN", "token")
        monkeypatch.setenv("ADMINS", "1")
        
        # Test mode uses test sheet
        settings_test = Settings(
            mode="TEST",
            sheets={"sheet_id_prod": "prod_sheet", "sheet_id_test": "test_sheet"}
        )
        assert settings_test.sheet_id == "test_sheet"
        
        # Prod mode uses prod sheet
        settings_prod = Settings(
            mode="PROD",
            sheets={"sheet_id_prod": "prod_sheet", "sheet_id_test": "test_sheet"}
        )
        assert settings_prod.sheet_id == "prod_sheet"

    def test_kyiv_tz_property(self, monkeypatch):
        """Test kyiv_tz returns timezone object."""
        monkeypatch.setenv("BOT_TOKEN", "token")
        monkeypatch.setenv("SHEET_ID_PROD", "prod")
        monkeypatch.setenv("SHEET_ID_TEST", "test")
        monkeypatch.setenv("ADMINS", "1")
        settings = Settings()
        assert settings.kyiv_tz is not None

    def test_print_config(self, monkeypatch, capsys):
        """Test print_config method."""
        monkeypatch.setenv("BOT_TOKEN", "token")
        monkeypatch.setenv("SHEET_ID_PROD", "prod")
        monkeypatch.setenv("SHEET_ID_TEST", "test")
        monkeypatch.setenv("ADMINS", "1")
        settings = Settings()
        settings.print_config()
        captured = capsys.readouterr()
        assert "КОНФІГУРАЦІЯ" in captured.out


class TestBackwardCompatibility:
    """Tests for backward compatibility module-level exports."""

    def test_core_exports(self):
        """Test core module-level exports exist."""
        from config import BOT_TOKEN, MODE, IS_TEST_MODE
        assert BOT_TOKEN is not None
        assert MODE in ["TEST", "PROD"]
        assert isinstance(IS_TEST_MODE, bool)

    def test_database_exports(self):
        """Test database-related exports."""
        from config import DB_BACKEND, SQLITE_PATH
        assert DB_BACKEND in ["sqlite", "postgres"]
        assert SQLITE_PATH is not None

    def test_fuel_exports(self):
        """Test fuel-related exports."""
        from config import FUEL_CONSUMPTION, EMERGENCY_FUEL_CONSUMPTION
        assert FUEL_CONSUMPTION > 0
        assert EMERGENCY_FUEL_CONSUMPTION > 0

    def test_admin_ids_export(self):
        """Test ADMIN_IDS export."""
        from config import ADMIN_IDS
        assert isinstance(ADMIN_IDS, list)

    def test_timezone_exports(self):
        """Test timezone exports."""
        from config import KYIV, TIMEZONE
        assert TIMEZONE is not None
        assert KYIV is not None

    def test_validate_env_function(self):
        """Test validate_env function exists."""
        from config import validate_env
        assert callable(validate_env)


class TestValidationErrors:
    """Tests for validation error handling."""

    def test_missing_required_field(self, monkeypatch):
        """Test missing BOT_TOKEN raises error."""
        monkeypatch.delenv("BOT_TOKEN", raising=False)
        with pytest.raises(Exception):  # ValidationError
            Settings()

    def test_invalid_mode(self, monkeypatch):
        """Test invalid MODE is rejected."""
        monkeypatch.setenv("BOT_TOKEN", "token")
        monkeypatch.setenv("SHEET_ID_PROD", "prod")
        monkeypatch.setenv("SHEET_ID_TEST", "test")
        monkeypatch.setenv("ADMINS", "1")
        
        with pytest.raises(Exception):  # ValidationError for invalid literal
            Settings(mode="INVALID")

    def test_postgres_without_dsn_raises(self, monkeypatch):
        """Test postgres without DSN raises error."""
        monkeypatch.setenv("BOT_TOKEN", "token")
        monkeypatch.setenv("SHEET_ID_PROD", "prod")
        monkeypatch.setenv("SHEET_ID_TEST", "test")
        monkeypatch.setenv("ADMINS", "1")
        
        with pytest.raises(ValueError, match="POSTGRES_DSN is required"):
            Settings(database={"backend": "postgres", "postgres_dsn": ""})


class TestConfigIntegration:
    """Integration tests for configuration loading."""

    def test_load_from_env_file(self, tmp_path, monkeypatch):
        """Test loading configuration from environment."""
        monkeypatch.setenv("BOT_TOKEN", "env_file_token")
        monkeypatch.setenv("MODE", "TEST")
        monkeypatch.setenv("ADMINS", "123,456")
        monkeypatch.setenv("SHEET_ID_PROD", "prod")
        monkeypatch.setenv("SHEET_ID_TEST", "test")
        
        test_settings = Settings()
        assert test_settings.bot_token == "env_file_token"
        assert test_settings.mode == "TEST"

    def test_env_override(self, monkeypatch):
        """Test environment variables override defaults."""
        monkeypatch.setenv("BOT_TOKEN", "override_token")
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        monkeypatch.setenv("FUEL_CONSUMPTION", "1.5")
        monkeypatch.setenv("SHEET_ID_PROD", "prod")
        monkeypatch.setenv("SHEET_ID_TEST", "test")
        monkeypatch.setenv("ADMINS", "1")
        
        settings = Settings()
        assert settings.bot_token == "override_token"
        assert settings.logging.log_level == "DEBUG"
        assert settings.fuel.fuel_consumption == 1.5
