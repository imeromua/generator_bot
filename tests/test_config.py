"""Tests for config module."""
import os

import pytest

import config


class TestConfigLoading:
    """Test configuration loading from environment."""

    def test_bot_token_loaded(self):
        """Test that BOT_TOKEN is loaded from environment."""
        assert config.BOT_TOKEN is not None
        assert isinstance(config.BOT_TOKEN, str)
        assert len(config.BOT_TOKEN) > 0

    def test_admin_ids_parsed(self):
        """Test that ADMIN_IDS are parsed correctly."""
        assert isinstance(config.ADMIN_IDS, list)
        assert len(config.ADMIN_IDS) > 0
        assert all(isinstance(admin_id, int) for admin_id in config.ADMIN_IDS)

    def test_fuel_consumption_is_float(self):
        """Test that FUEL_CONSUMPTION is a float."""
        assert isinstance(config.FUEL_CONSUMPTION, float)
        assert config.FUEL_CONSUMPTION > 0

    def test_emergency_fuel_consumption(self):
        """Test that EMERGENCY_FUEL_CONSUMPTION is configured."""
        assert isinstance(config.EMERGENCY_FUEL_CONSUMPTION, float)
        assert config.EMERGENCY_FUEL_CONSUMPTION > 0

    def test_timezone_configured(self):
        """Test that timezone is properly configured."""
        assert config.TIMEZONE == "Europe/Kyiv"
        assert config.KYIV is not None


class TestConfigValidation:
    """Test configuration validation."""

    def test_validate_env_success(self):
        """Test that validation passes with correct env."""
        # Should not raise any exception
        try:
            config.validate_env()
        except SystemExit:
            pytest.fail("validate_env() raised SystemExit unexpectedly")

    def test_db_backend_value(self):
        """Test that DB_BACKEND has valid value."""
        assert config.DB_BACKEND in ["sqlite", "postgres"]

    def test_test_mode_active(self):
        """Test that we're in test mode."""
        assert config.IS_TEST_MODE is True
        assert config.MODE == "TEST"


class TestConfigDefaults:
    """Test default configuration values."""

    def test_work_hours_format(self):
        """Test that work hours are in correct format."""
        assert isinstance(config.WORK_START_TIME, str)
        assert isinstance(config.WORK_END_TIME, str)
        assert ":" in config.WORK_START_TIME
        assert ":" in config.WORK_END_TIME

    def test_fuel_alert_threshold(self):
        """Test fuel alert threshold is positive."""
        assert config.FUEL_ALERT_THRESHOLD_L > 0

    def test_oil_change_interval(self):
        """Test oil change interval is positive."""
        assert config.OIL_CHANGE_INTERVAL > 0

    def test_spark_change_interval(self):
        """Test spark change interval is positive."""
        assert config.SPARK_CHANGE_INTERVAL > 0


@pytest.mark.unit
class TestConfigHelpers:
    """Test configuration helper functions."""

    def test_env_bool_helper(self):
        """Test _env_bool helper function."""
        # Test truthy values
        os.environ["TEST_BOOL_TRUE"] = "1"
        assert config._env_bool("TEST_BOOL_TRUE") is True

        os.environ["TEST_BOOL_TRUE"] = "true"
        assert config._env_bool("TEST_BOOL_TRUE") is True

        # Test falsy values
        os.environ["TEST_BOOL_FALSE"] = "0"
        assert config._env_bool("TEST_BOOL_FALSE") is False

        os.environ["TEST_BOOL_FALSE"] = "false"
        assert config._env_bool("TEST_BOOL_FALSE") is False

        # Test default
        assert config._env_bool("NONEXISTENT_VAR", default=True) is True
        assert config._env_bool("NONEXISTENT_VAR", default=False) is False

        # Cleanup
        del os.environ["TEST_BOOL_TRUE"]
        del os.environ["TEST_BOOL_FALSE"]
