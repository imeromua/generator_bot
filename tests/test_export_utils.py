"""Tests for utils/export_utils.py — iOS-friendly XLSX download headers."""

import sys
import os
import urllib.parse
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

os.environ.setdefault("SQLITE_PATH", ":memory:")

from utils.export_utils import build_xlsx_headers, _sanitize_filename, XLSX_CONTENT_TYPE


class TestSanitizeFilename:
    def test_removes_colon(self):
        assert ":" not in _sanitize_filename("report:2026.xlsx")

    def test_removes_slash(self):
        assert "/" not in _sanitize_filename("dir/file.xlsx")

    def test_removes_backslash(self):
        assert "\\" not in _sanitize_filename("dir\\file.xlsx")

    def test_removes_question_mark(self):
        assert "?" not in _sanitize_filename("file?.xlsx")

    def test_removes_asterisk(self):
        assert "*" not in _sanitize_filename("file*.xlsx")

    def test_removes_square_brackets(self):
        result = _sanitize_filename("file[1].xlsx")
        assert "[" not in result
        assert "]" not in result

    def test_keeps_ukrainian_characters(self):
        name = "Звіт_main.xlsx"
        assert _sanitize_filename(name) == name

    def test_keeps_digits_and_underscores(self):
        name = "report_main_20260317.xlsx"
        assert _sanitize_filename(name) == name

    def test_replaces_multiple_unsafe_chars(self):
        result = _sanitize_filename("a:b/c*.xlsx")
        assert result == "a_b_c_.xlsx"


class TestBuildXlsxHeaders:
    def test_content_type_is_correct(self):
        headers = build_xlsx_headers("report.xlsx")
        assert headers["Content-Type"] == XLSX_CONTENT_TYPE

    def test_content_disposition_has_attachment(self):
        headers = build_xlsx_headers("report.xlsx")
        assert headers["Content-Disposition"].startswith("attachment;")

    def test_content_disposition_has_filename(self):
        headers = build_xlsx_headers("report.xlsx")
        assert 'filename="report.xlsx"' in headers["Content-Disposition"]

    def test_content_disposition_has_rfc5987_filename_star(self):
        headers = build_xlsx_headers("report.xlsx")
        assert "filename*=UTF-8''" in headers["Content-Disposition"]

    def test_rfc5987_encoding_for_ukrainian_filename(self):
        filename = "Звіт_main_20260317.xlsx"
        headers = build_xlsx_headers(filename)
        cd = headers["Content-Disposition"]
        expected_encoded = urllib.parse.quote(filename, safe="")
        assert expected_encoded in cd

    def test_cache_control_must_revalidate(self):
        headers = build_xlsx_headers("report.xlsx")
        cc = headers["Cache-Control"]
        assert "no-cache" in cc
        assert "no-store" in cc
        assert "must-revalidate" in cc

    def test_pragma_no_cache(self):
        headers = build_xlsx_headers("report.xlsx")
        assert headers["Pragma"] == "no-cache"

    def test_expires_zero(self):
        headers = build_xlsx_headers("report.xlsx")
        assert headers["Expires"] == "0"

    def test_x_content_type_options_nosniff(self):
        headers = build_xlsx_headers("report.xlsx")
        assert headers["X-Content-Type-Options"] == "nosniff"

    def test_no_cors_header_by_default(self):
        headers = build_xlsx_headers("report.xlsx")
        assert "Access-Control-Allow-Origin" not in headers

    def test_cors_header_when_allow_cors_true(self):
        headers = build_xlsx_headers("report.xlsx", allow_cors=True)
        assert headers.get("Access-Control-Allow-Origin") == "*"

    def test_unsafe_chars_in_filename_are_sanitized(self):
        headers = build_xlsx_headers("report:2026/01.xlsx")
        cd = headers["Content-Disposition"]
        # Unsafe chars must not appear inside the quoted filename value
        import re
        match = re.search(r'filename="([^"]*)"', cd)
        assert match is not None
        safe_name = match.group(1)
        assert ":" not in safe_name
        assert "/" not in safe_name

    def test_ascii_filename_in_content_disposition(self):
        headers = build_xlsx_headers("generator_report_quick_20260317.xlsx")
        cd = headers["Content-Disposition"]
        assert 'filename="generator_report_quick_20260317.xlsx"' in cd
