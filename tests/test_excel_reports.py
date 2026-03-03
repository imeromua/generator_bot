"""Tests for reports/excel_reports.py — month range and report generation."""

import os
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

os.environ.setdefault("SQLITE_PATH", ":memory:")

import config
import database.models as db_models
from reports.excel_reports import ExcelReportGenerator, generate_excel_report


@pytest.fixture(autouse=True)
def _setup_db(monkeypatch, tmp_path):
    """Fresh in-memory database for each test."""
    db_path = str(tmp_path / "test_excel.db")
    monkeypatch.setattr(config, "SQLITE_PATH", db_path)
    monkeypatch.setattr(config, "DB_BACKEND", "sqlite")
    db_models.init_db()
    yield


class TestMonthRange:
    def _gen(self):
        return ExcelReportGenerator()

    def test_february_2026(self):
        gen = self._gen()
        start_dt, end_dt = gen._month_range(2026, 2)
        assert start_dt == datetime(2026, 2, 1, 0, 0, 0, tzinfo=config.KYIV)
        assert end_dt == datetime(2026, 2, 28, 23, 59, 59, tzinfo=config.KYIV)

    def test_february_2024_leap_year(self):
        gen = self._gen()
        start_dt, end_dt = gen._month_range(2024, 2)
        assert start_dt == datetime(2024, 2, 1, 0, 0, 0, tzinfo=config.KYIV)
        assert end_dt == datetime(2024, 2, 29, 23, 59, 59, tzinfo=config.KYIV)

    def test_december_2026(self):
        gen = self._gen()
        start_dt, end_dt = gen._month_range(2026, 12)
        assert start_dt == datetime(2026, 12, 1, 0, 0, 0, tzinfo=config.KYIV)
        assert end_dt == datetime(2026, 12, 31, 23, 59, 59, tzinfo=config.KYIV)

    def test_returns_timezone_aware(self):
        gen = self._gen()
        start_dt, end_dt = gen._month_range(2026, 5)
        assert start_dt.tzinfo is not None
        assert end_dt.tzinfo is not None


class TestGenerateExcelReportWithYearMonth:
    def test_quick_report_with_year_month_does_not_raise(self):
        result = generate_excel_report('quick', 30, year=2026, month=2)
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_detailed_report_with_year_month_does_not_raise(self):
        result = generate_excel_report('detailed', 30, year=2026, month=2)
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_technical_report_with_year_month_does_not_raise(self):
        result = generate_excel_report('technical', 30, year=2026, month=2)
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_financial_report_with_year_month_does_not_raise(self):
        result = generate_excel_report('financial', 30, year=2026, month=2)
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_personnel_report_with_year_month_does_not_raise(self):
        result = generate_excel_report('personnel', 30, year=2026, month=2)
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_quick_report_legacy_days_still_works(self):
        result = generate_excel_report('quick', 30)
        assert isinstance(result, bytes)
        assert len(result) > 0
