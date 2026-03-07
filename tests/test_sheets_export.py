"""Tests for services/sheets_export.py — preview + conflict-aware sync.

Covers:
- load_sheet_state(): parsing sheet rows into normalized field dicts
- aggregate_app_data(): aggregating DB logs into normalized field dicts
- build_sync_preview(): field-level comparison and classification rules
- apply_sync_decisions(): applying changes and resolving conflicts
- _normalize_value(): numeric normalization helper
- _unique_join(): deduplication helper
- _format_fuel(): fuel formatting helper
"""

import os
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

os.environ.setdefault("SQLITE_PATH", ":memory:")

import config
import database.models as db_models
from services.sheets_export import (
    MAIN_GENERATOR_ID,
    SYNC_FIELDS,
    _format_fuel,
    _normalize_value,
    _unique_join,
    aggregate_app_data,
    apply_sync_decisions,
    build_preview_version,
    build_sync_preview,
    collect_batch_updates,
    load_sheet_state,
)


# ---------------------------------------------------------------------------
# DB fixture
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _setup_db(monkeypatch, tmp_path):
    """Fresh in-memory database for each test."""
    db_path = str(tmp_path / "test_sheets_export.db")
    monkeypatch.setattr(config, "SQLITE_PATH", db_path)
    monkeypatch.setattr(config, "DB_BACKEND", "sqlite")
    db_models.init_db()
    yield


# ---------------------------------------------------------------------------
# Helper: build a fake worksheet from a list of rows
# ---------------------------------------------------------------------------


def _make_worksheet(rows: list[list[str]]) -> MagicMock:
    """Return a mock gspread Worksheet whose get_all_values() returns *rows*."""
    ws = MagicMock()
    ws.get_all_values.return_value = rows
    return ws


def _make_sheet_row(
    date_fmt: str = "",
    m_start: str = "",
    m_end: str = "",
    d_start: str = "",
    d_end: str = "",
    e_start: str = "",
    e_end: str = "",
    x_start: str = "",
    x_end: str = "",
    fuel: str = "",
    receipts: str = "",
    drivers: str = "",
    extra: int = 5,
) -> list[str]:
    """Build a sheet row padded to at least 17 columns."""
    # columns 0-8 (A-I), 9-12 (J-M, not synced), 13 (N), 14 (O, not synced), 15 (P), 16 (Q)
    row = [date_fmt, m_start, m_end, d_start, d_end, e_start, e_end, x_start, x_end]
    row += [""] * 4  # J-M (indices 9-12)
    row.append(fuel)  # N (index 13)
    row.append("")  # O (index 14, not synced)
    row.append(receipts)  # P (index 15)
    row.append(drivers)  # Q (index 16)
    row += [""] * extra
    return row


# ===========================================================================
# 1. _format_fuel
# ===========================================================================


class TestFormatFuel:
    def test_zero_returns_empty(self):
        assert _format_fuel(0.0) == ""

    def test_integer_value(self):
        assert _format_fuel(80.0) == "80"

    def test_fractional_value(self):
        assert _format_fuel(80.5) == "80.5"

    def test_near_integer(self):
        # float rounding artefact: 79.9999999 → 80
        assert _format_fuel(79.9999999) == "80"


# ===========================================================================
# 2. _normalize_value
# ===========================================================================


class TestNormalizeValue:
    def test_fuel_integer_string(self):
        assert _normalize_value("fuel", "80") == "80"

    def test_fuel_dot_zero(self):
        assert _normalize_value("fuel", "80.0") == "80"

    def test_fuel_comma_decimal(self):
        assert _normalize_value("fuel", "80,5") == "80.5"

    def test_fuel_empty(self):
        assert _normalize_value("fuel", "") == ""

    def test_non_fuel_field_passthrough(self):
        assert _normalize_value("m_start", "08:00") == "08:00"
        assert _normalize_value("drivers", "Іван, Петро") == "Іван, Петро"

    def test_fuel_non_numeric_passthrough(self):
        assert _normalize_value("fuel", "unknown") == "unknown"


# ===========================================================================
# 3. _unique_join
# ===========================================================================


class TestUniqueJoin:
    def test_empty_list(self):
        assert _unique_join([]) == ""

    def test_single_item(self):
        assert _unique_join(["Alice"]) == "Alice"

    def test_deduplicates(self):
        assert _unique_join(["Alice", "Bob", "Alice"]) == "Alice, Bob"

    def test_strips_whitespace(self):
        assert _unique_join(["  Alice ", "Bob"]) == "Alice, Bob"

    def test_skips_empty_strings(self):
        assert _unique_join(["Alice", "", "Bob"]) == "Alice, Bob"

    def test_preserves_order(self):
        assert _unique_join(["Charlie", "Alice", "Bob"]) == "Charlie, Alice, Bob"


# ===========================================================================
# 4. load_sheet_state
# ===========================================================================


class TestLoadSheetState:
    def test_empty_worksheet(self):
        ws = _make_worksheet([["Header row 1"], ["Header row 2"]])
        state = load_sheet_state(ws)
        assert state == {}

    def test_parses_date_and_fields(self):
        header1 = [""] * 17
        header2 = [""] * 17
        data_row = _make_sheet_row(
            date_fmt="07.03.2026",
            m_start="08:00",
            m_end="20:00",
            fuel="80",
            receipts="001",
            drivers="Іван",
        )
        ws = _make_worksheet([header1, header2, data_row])
        state = load_sheet_state(ws)
        assert "2026-03-07" in state
        entry = state["2026-03-07"]
        assert entry["row_index"] == 3
        assert entry["fields"]["m_start"] == "08:00"
        assert entry["fields"]["m_end"] == "20:00"
        assert entry["fields"]["fuel"] == "80"
        assert entry["fields"]["receipts"] == "001"
        assert entry["fields"]["drivers"] == "Іван"

    def test_skips_rows_with_invalid_date(self):
        header1 = [""] * 17
        header2 = [""] * 17
        bad_row = _make_sheet_row(date_fmt="not-a-date")
        ws = _make_worksheet([header1, header2, bad_row])
        state = load_sheet_state(ws)
        assert state == {}

    def test_skips_rows_with_empty_date(self):
        header1 = [""] * 17
        header2 = [""] * 17
        empty_row = _make_sheet_row(date_fmt="")
        ws = _make_worksheet([header1, header2, empty_row])
        state = load_sheet_state(ws)
        assert state == {}

    def test_row_index_starts_at_3(self):
        """Row index should be 1-based and start at 3 (rows 1 & 2 are headers)."""
        header1 = [""] * 17
        header2 = [""] * 17
        row3 = _make_sheet_row(date_fmt="01.03.2026")
        row4 = _make_sheet_row(date_fmt="02.03.2026")
        ws = _make_worksheet([header1, header2, row3, row4])
        state = load_sheet_state(ws)
        assert state["2026-03-01"]["row_index"] == 3
        assert state["2026-03-02"]["row_index"] == 4

    def test_jm_and_o_columns_not_in_fields(self):
        """Calculated columns J-M and O must not appear in fields."""
        header1 = [""] * 17
        header2 = [""] * 17
        data_row = _make_sheet_row(date_fmt="07.03.2026")
        ws = _make_worksheet([header1, header2, data_row])
        state = load_sheet_state(ws)
        fields = state["2026-03-07"]["fields"]
        sync_field_names = {name for name, _, _ in SYNC_FIELDS}
        for field_name in fields:
            assert field_name in sync_field_names

    def test_short_row_pads_missing_columns(self):
        """A row shorter than expected should not raise; missing fields default to ''."""
        header1 = [""] * 17
        header2 = [""] * 17
        short_row = ["07.03.2026", "08:00"]  # only 2 columns
        ws = _make_worksheet([header1, header2, short_row])
        state = load_sheet_state(ws)
        assert "2026-03-07" in state
        assert state["2026-03-07"]["fields"]["fuel"] == ""


# ===========================================================================
# 5. aggregate_app_data
# ===========================================================================


class TestAggregateAppData:
    def _insert_log(self, event_type, timestamp, value=None, driver=None, receipt=None, user="test"):
        from database.models import get_connection

        conn = get_connection()
        conn.execute(
            "INSERT INTO logs (event_type, timestamp, user_name, value, driver_name, receipt_number) VALUES (?,?,?,?,?,?)",
            (event_type, timestamp, user, value, driver, receipt),
        )
        conn.commit()
        conn.close()

    def test_empty_db_returns_empty(self):
        result = aggregate_app_data()
        assert result == {}

    def test_single_shift_start(self):
        self._insert_log("m_start", "2026-03-07 08:00:00")
        result = aggregate_app_data()
        assert "2026-03-07" in result
        assert result["2026-03-07"]["fields"]["m_start"] == "08:00"
        assert result["2026-03-07"]["fields"]["m_end"] == ""

    def test_shift_start_and_end(self):
        self._insert_log("m_start", "2026-03-07 08:00:00")
        self._insert_log("m_end", "2026-03-07 20:00:00")
        result = aggregate_app_data()
        fields = result["2026-03-07"]["fields"]
        assert fields["m_start"] == "08:00"
        assert fields["m_end"] == "20:00"

    def test_refill_fuel_integer(self):
        self._insert_log("refill", "2026-03-07 10:00:00", value="80", driver="Іван", receipt="001")
        result = aggregate_app_data()
        fields = result["2026-03-07"]["fields"]
        assert fields["fuel"] == "80"
        assert fields["receipts"] == "001"
        assert fields["drivers"] == "Іван"

    def test_refill_fuel_fractional(self):
        self._insert_log("refill", "2026-03-07 10:00:00", value="80.5", driver="Іван", receipt="001")
        result = aggregate_app_data()
        assert result["2026-03-07"]["fields"]["fuel"] == "80.5"

    def test_multiple_refills_summed(self):
        self._insert_log("refill", "2026-03-07 10:00:00", value="50", driver="Іван", receipt="001")
        self._insert_log("refill", "2026-03-07 15:00:00", value="30", driver="Петро", receipt="002")
        fields = aggregate_app_data()["2026-03-07"]["fields"]
        assert fields["fuel"] == "80"
        assert fields["receipts"] == "001, 002"
        assert fields["drivers"] == "Іван, Петро"

    def test_duplicate_drivers_deduplicated(self):
        self._insert_log("refill", "2026-03-07 10:00:00", value="50", driver="Іван", receipt="001")
        self._insert_log("refill", "2026-03-07 15:00:00", value="30", driver="Іван", receipt="002")
        fields = aggregate_app_data()["2026-03-07"]["fields"]
        assert fields["drivers"] == "Іван"

    def test_from_date_filters(self):
        self._insert_log("m_start", "2026-03-06 08:00:00")
        self._insert_log("m_start", "2026-03-07 08:00:00")
        result = aggregate_app_data(from_date="2026-03-07")
        assert "2026-03-06" not in result
        assert "2026-03-07" in result

    def test_date_formatted_correctly(self):
        self._insert_log("m_start", "2026-03-07 08:00:00")
        result = aggregate_app_data()
        assert result["2026-03-07"]["fields"]["date"] == "07.03.2026"

    def test_all_four_shifts(self):
        for shift, ts in [("m", "08:00"), ("d", "10:00"), ("e", "14:00"), ("x", "18:00")]:
            self._insert_log(f"{shift}_start", f"2026-03-07 {ts}:00")
        fields = aggregate_app_data()["2026-03-07"]["fields"]
        assert fields["m_start"] == "08:00"
        assert fields["d_start"] == "10:00"
        assert fields["e_start"] == "14:00"
        assert fields["x_start"] == "18:00"


# ===========================================================================
# 6. build_sync_preview — field-level comparison rules
# ===========================================================================


def _make_app_data(date_iso: str, **field_overrides) -> dict:
    """Build a minimal app_data dict for one date."""
    dt = datetime.strptime(date_iso, "%Y-%m-%d")
    defaults = {
        "date": dt.strftime("%d.%m.%Y"),
        "m_start": "",
        "m_end": "",
        "d_start": "",
        "d_end": "",
        "e_start": "",
        "e_end": "",
        "x_start": "",
        "x_end": "",
        "fuel": "",
        "receipts": "",
        "drivers": "",
    }
    defaults.update(field_overrides)
    return {date_iso: {"fields": defaults}}


def _make_sheet_state(date_iso: str, row_index: int = 5, **field_overrides) -> dict:
    """Build a minimal sheet_state dict for one date."""
    dt = datetime.strptime(date_iso, "%Y-%m-%d")
    defaults = {
        "date": dt.strftime("%d.%m.%Y"),
        "m_start": "",
        "m_end": "",
        "d_start": "",
        "d_end": "",
        "e_start": "",
        "e_end": "",
        "x_start": "",
        "x_end": "",
        "fuel": "",
        "receipts": "",
        "drivers": "",
    }
    defaults.update(field_overrides)
    return {date_iso: {"row_index": row_index, "fields": defaults}}


class TestBuildSyncPreview:
    DATE = "2026-03-07"

    # --- new rows ---

    def test_date_not_in_sheet_goes_to_new_rows(self):
        app = _make_app_data(self.DATE, m_start="08:00")
        preview = build_sync_preview({}, app)
        assert len(preview["new_rows"]) == 1
        assert preview["new_rows"][0]["date"] == self.DATE
        assert preview["safe_updates"] == []
        assert preview["conflicts"] == []

    def test_new_row_contains_all_fields(self):
        app = _make_app_data(self.DATE, m_start="08:00", fuel="80")
        preview = build_sync_preview({}, app)
        fields = preview["new_rows"][0]["fields"]
        assert fields["m_start"] == "08:00"
        assert fields["fuel"] == "80"

    # --- both empty → skip ---

    def test_both_empty_no_change(self):
        app = _make_app_data(self.DATE)  # all fields empty
        sheet = _make_sheet_state(self.DATE)  # all fields empty
        preview = build_sync_preview(sheet, app)
        assert preview["new_rows"] == []
        assert preview["safe_updates"] == []
        assert preview["conflicts"] == []

    # --- sheet empty, app has value → safe_update ---

    def test_sheet_empty_app_value_is_safe_update(self):
        app = _make_app_data(self.DATE, fuel="80")
        sheet = _make_sheet_state(self.DATE, fuel="")
        preview = build_sync_preview(sheet, app)
        assert len(preview["safe_updates"]) == 1
        su = preview["safe_updates"][0]
        assert su["field"] == "fuel"
        assert su["column"] == "N"
        assert su["sheet_value"] == ""
        assert su["app_value"] == "80"
        assert su["status"] == "safe_update"
        assert preview["conflicts"] == []

    def test_safe_update_for_shift_time(self):
        app = _make_app_data(self.DATE, m_start="08:00")
        sheet = _make_sheet_state(self.DATE, m_start="")
        preview = build_sync_preview(sheet, app)
        assert any(u["field"] == "m_start" for u in preview["safe_updates"])

    # --- sheet has value, app empty → keep sheet (skip) ---

    def test_sheet_value_app_empty_is_skipped(self):
        app = _make_app_data(self.DATE, fuel="")
        sheet = _make_sheet_state(self.DATE, fuel="90")
        preview = build_sync_preview(sheet, app)
        assert preview["safe_updates"] == []
        assert preview["conflicts"] == []
        assert preview["new_rows"] == []

    # --- both same → skip ---

    def test_both_same_no_change(self):
        app = _make_app_data(self.DATE, fuel="80", m_start="08:00")
        sheet = _make_sheet_state(self.DATE, fuel="80", m_start="08:00")
        preview = build_sync_preview(sheet, app)
        assert preview["safe_updates"] == []
        assert preview["conflicts"] == []

    # --- both differ → conflict ---

    def test_both_differ_is_conflict(self):
        app = _make_app_data(self.DATE, fuel="80")
        sheet = _make_sheet_state(self.DATE, fuel="75")
        preview = build_sync_preview(sheet, app)
        assert len(preview["conflicts"]) == 1
        c = preview["conflicts"][0]
        assert c["field"] == "fuel"
        assert c["sheet_value"] == "75"
        assert c["app_value"] == "80"
        assert c["status"] == "conflict"
        assert preview["safe_updates"] == []

    def test_conflict_has_row_index(self):
        app = _make_app_data(self.DATE, fuel="80")
        sheet = _make_sheet_state(self.DATE, row_index=7, fuel="75")
        preview = build_sync_preview(sheet, app)
        assert preview["conflicts"][0]["row_index"] == 7

    def test_conflict_has_column_letter(self):
        app = _make_app_data(self.DATE, receipts="NEW-001")
        sheet = _make_sheet_state(self.DATE, receipts="OLD-001")
        preview = build_sync_preview(sheet, app)
        assert preview["conflicts"][0]["column"] == "P"

    # --- numeric normalization avoids false conflicts ---

    def test_fuel_80_vs_80_dot_0_no_conflict(self):
        app = _make_app_data(self.DATE, fuel="80")
        sheet = _make_sheet_state(self.DATE, fuel="80.0")
        preview = build_sync_preview(sheet, app)
        assert preview["conflicts"] == []
        assert preview["safe_updates"] == []

    def test_fuel_comma_decimal_normalized(self):
        app = _make_app_data(self.DATE, fuel="80.5")
        sheet = _make_sheet_state(self.DATE, fuel="80,5")
        preview = build_sync_preview(sheet, app)
        assert preview["conflicts"] == []

    # --- multiple fields in same date ---

    def test_multiple_fields_classified_independently(self):
        app = _make_app_data(self.DATE, fuel="80", m_start="08:00", drivers="Іван")
        sheet = _make_sheet_state(self.DATE, fuel="75", m_start="", drivers="Іван")
        preview = build_sync_preview(sheet, app)
        # fuel: conflict (both differ)
        assert any(c["field"] == "fuel" for c in preview["conflicts"])
        # m_start: safe_update (sheet empty, app has value)
        assert any(u["field"] == "m_start" for u in preview["safe_updates"])
        # drivers: same → no change
        assert not any(c["field"] == "drivers" for c in preview["conflicts"])
        assert not any(u["field"] == "drivers" for u in preview["safe_updates"])

    # --- date field not compared field-by-field ---

    def test_date_field_not_in_safe_updates_or_conflicts(self):
        app = _make_app_data(self.DATE)
        sheet = _make_sheet_state(self.DATE)
        preview = build_sync_preview(sheet, app)
        assert not any(item.get("field") == "date" for item in preview["safe_updates"])
        assert not any(item.get("field") == "date" for item in preview["conflicts"])

    # --- multiple dates ---

    def test_multiple_dates(self):
        app = {
            "2026-03-06": {"fields": {n: "" for n, _, _ in SYNC_FIELDS}},
            "2026-03-07": {"fields": {n: "" for n, _, _ in SYNC_FIELDS}},
        }
        app["2026-03-06"]["fields"]["date"] = "06.03.2026"
        app["2026-03-06"]["fields"]["fuel"] = "50"
        app["2026-03-07"]["fields"]["date"] = "07.03.2026"
        app["2026-03-07"]["fields"]["fuel"] = "80"

        sheet = _make_sheet_state("2026-03-06", row_index=3, fuel="50")
        # 2026-03-07 not in sheet → new_row

        preview = build_sync_preview(sheet, app)
        assert len(preview["new_rows"]) == 1
        assert preview["new_rows"][0]["date"] == "2026-03-07"
        # 2026-03-06: fuel same → no change
        assert not any(c["date"] == "2026-03-06" for c in preview["conflicts"])
        assert not any(u["date"] == "2026-03-06" for u in preview["safe_updates"])


# ===========================================================================
# 7. apply_sync_decisions
# ===========================================================================


def _make_mock_worksheet() -> MagicMock:
    ws = MagicMock()
    ws.update = MagicMock()
    ws.batch_update = MagicMock()
    return ws


class TestApplySyncDecisions:
    DATE = "2026-03-07"

    def _make_safe_update(self, field="fuel", column="N", sheet_val="", app_val="80", row_index=5):
        return {
            "date": self.DATE,
            "row_index": row_index,
            "field": field,
            "column": column,
            "sheet_value": sheet_val,
            "app_value": app_val,
            "status": "safe_update",
        }

    def _make_conflict(self, field="fuel", column="N", sheet_val="75", app_val="80", row_index=5):
        return {
            "date": self.DATE,
            "row_index": row_index,
            "field": field,
            "column": column,
            "sheet_value": sheet_val,
            "app_value": app_val,
            "status": "conflict",
        }

    # --- safe_updates always applied ---

    def test_safe_update_is_always_applied(self):
        ws = _make_mock_worksheet()
        su = self._make_safe_update(field="fuel", column="N", app_val="80", row_index=5)
        result = apply_sync_decisions(ws, {"safe_updates": [su], "conflicts": [], "new_rows": []})
        assert len(result["applied"]) == 1
        assert result["applied"][0]["status"] == "applied_safe_update"
        ws.batch_update.assert_called_once_with(
            [{"range": "N5:N5", "values": [["80"]]}],
            value_input_option="USER_ENTERED",
        )

    # --- new_rows always applied ---

    def test_new_row_is_always_applied(self):
        ws = _make_mock_worksheet()
        new_row = {
            "date": self.DATE,
            "fields": {n: "" for n, _, _ in SYNC_FIELDS},
        }
        new_row["fields"]["fuel"] = "80"
        new_row["fields"]["date"] = "07.03.2026"
        result = apply_sync_decisions(
            ws,
            {"new_rows": [new_row], "safe_updates": [], "conflicts": []},
            current_row_count=10,
        )
        assert any(r["status"] == "new_row" for r in result["applied"])
        # All SYNC_FIELDS columns should have been written via batch_update
        ws.batch_update.assert_called_once()
        call_args = ws.batch_update.call_args
        batch_entries = call_args[0][0]
        written_ranges = [entry["range"] for entry in batch_entries]
        # Expect grouped range entries for new row 11 (A:I, N, P:Q)
        assert any("A11" in r for r in written_ranges)
        assert any("N11" in r for r in written_ranges)
        assert any("P11" in r for r in written_ranges)

    # --- conflicts: default keep_sheet ---

    def test_conflict_without_decision_is_skipped(self):
        ws = _make_mock_worksheet()
        conflict = self._make_conflict()
        result = apply_sync_decisions(ws, {"safe_updates": [], "conflicts": [conflict], "new_rows": []})
        assert len(result["skipped"]) == 1
        assert result["skipped"][0]["status"] == "skipped_keep_sheet"
        ws.batch_update.assert_not_called()

    # --- keep_app per-field decision ---

    def test_keep_app_per_field_applies_app_value(self):
        ws = _make_mock_worksheet()
        conflict = self._make_conflict(field="fuel", column="N", sheet_val="75", app_val="80", row_index=5)
        decisions = [{"date": self.DATE, "field": "fuel", "decision": "keep_app"}]
        result = apply_sync_decisions(ws, {"safe_updates": [], "conflicts": [conflict], "new_rows": []}, decisions=decisions)
        assert len(result["applied"]) == 1
        assert result["applied"][0]["status"] == "applied_keep_app"
        ws.batch_update.assert_called_once_with(
            [{"range": "N5:N5", "values": [["80"]]}],
            value_input_option="USER_ENTERED",
        )

    # --- keep_sheet per-field decision ---

    def test_keep_sheet_per_field_skips(self):
        ws = _make_mock_worksheet()
        conflict = self._make_conflict()
        decisions = [{"date": self.DATE, "field": "fuel", "decision": "keep_sheet"}]
        result = apply_sync_decisions(ws, {"safe_updates": [], "conflicts": [conflict], "new_rows": []}, decisions=decisions)
        assert len(result["skipped"]) == 1
        ws.batch_update.assert_not_called()

    # --- keep_app_all global decision ---

    def test_keep_app_all_applies_all_conflicts(self):
        ws = _make_mock_worksheet()
        c1 = self._make_conflict(field="fuel", column="N", app_val="80")
        c2 = self._make_conflict(field="m_start", column="B", sheet_val="07:00", app_val="08:00")
        decisions = [{"decision": "keep_app_all"}]
        result = apply_sync_decisions(ws, {"safe_updates": [], "conflicts": [c1, c2], "new_rows": []}, decisions=decisions)
        assert len(result["applied"]) == 2
        assert all(r["status"] == "applied_keep_app" for r in result["applied"])
        ws.batch_update.assert_called_once()
        entries = ws.batch_update.call_args[0][0]
        assert len(entries) == 2

    # --- keep_sheet_all global decision ---

    def test_keep_sheet_all_skips_all_conflicts(self):
        ws = _make_mock_worksheet()
        c1 = self._make_conflict(field="fuel", column="N")
        c2 = self._make_conflict(field="receipts", column="P", sheet_val="001", app_val="002")
        decisions = [{"decision": "keep_sheet_all"}]
        result = apply_sync_decisions(ws, {"safe_updates": [], "conflicts": [c1, c2], "new_rows": []}, decisions=decisions)
        assert len(result["skipped"]) == 2
        ws.batch_update.assert_not_called()

    # --- per-field overrides global ---

    def test_per_field_overrides_global_keep_sheet_all(self):
        ws = _make_mock_worksheet()
        c_fuel = self._make_conflict(field="fuel", column="N", app_val="80")
        c_receipts = self._make_conflict(field="receipts", column="P", sheet_val="001", app_val="002")
        decisions = [
            {"decision": "keep_sheet_all"},  # global: keep sheet
            {"date": self.DATE, "field": "fuel", "decision": "keep_app"},  # override: use app for fuel
        ]
        result = apply_sync_decisions(
            ws,
            {"safe_updates": [], "conflicts": [c_fuel, c_receipts], "new_rows": []},
            decisions=decisions,
        )
        applied_fields = {r["field"] for r in result["applied"]}
        skipped_fields = {r["field"] for r in result["skipped"]}
        assert "fuel" in applied_fields
        assert "receipts" in skipped_fields

    # --- current_row_count inferred when not given ---

    def test_current_row_count_inferred_from_preview(self):
        ws = _make_mock_worksheet()
        su = self._make_safe_update(row_index=10)
        new_row = {
            "date": "2026-03-08",
            "fields": {n: "" for n, _, _ in SYNC_FIELDS},
        }
        result = apply_sync_decisions(
            ws,
            {"safe_updates": [su], "conflicts": [], "new_rows": [new_row]},
        )
        # new row should be placed at row 11 (max existing 10 + 1)
        new_row_records = [r for r in result["applied"] if r["status"] == "new_row"]
        assert new_row_records[0]["row_index"] == 11

    # --- empty preview → nothing applied ---

    def test_empty_preview_no_writes(self):
        ws = _make_mock_worksheet()
        result = apply_sync_decisions(ws, {"safe_updates": [], "conflicts": [], "new_rows": []})
        assert result["applied"] == []
        assert result["skipped"] == []
        ws.batch_update.assert_not_called()


# ===========================================================================
# 8. Integration: full pipeline with mock worksheet
# ===========================================================================


class TestFullPipelineIntegration:
    """End-to-end tests using a real (in-memory) DB and a mock worksheet."""

    def _insert_log(self, event_type, timestamp, value=None, driver=None, receipt=None, user="test"):
        from database.models import get_connection

        conn = get_connection()
        conn.execute(
            "INSERT INTO logs (event_type, timestamp, user_name, value, driver_name, receipt_number) VALUES (?,?,?,?,?,?)",
            (event_type, timestamp, user, value, driver, receipt),
        )
        conn.commit()
        conn.close()

    def test_new_date_results_in_new_row_applied(self):
        self._insert_log("m_start", "2026-03-07 08:00:00")
        self._insert_log("refill", "2026-03-07 10:00:00", value="80", driver="Іван", receipt="001")

        ws = _make_worksheet([["H1"] * 17, ["H2"] * 17])  # no data rows

        sheet_state = load_sheet_state(ws)
        app_data = aggregate_app_data()
        preview = build_sync_preview(sheet_state, app_data)

        assert len(preview["new_rows"]) == 1
        assert preview["safe_updates"] == []
        assert preview["conflicts"] == []

        ws2 = _make_mock_worksheet()
        result = apply_sync_decisions(ws2, preview, current_row_count=2)
        assert any(r["field"] == "fuel" and r["app_value"] == "80" for r in result["applied"])
        assert any(r["field"] == "m_start" and r["app_value"] == "08:00" for r in result["applied"])

    def test_existing_date_all_same_no_writes(self):
        self._insert_log("m_start", "2026-03-07 08:00:00")
        self._insert_log("refill", "2026-03-07 10:00:00", value="80", driver="Іван", receipt="001")

        header1 = [""] * 17
        header2 = [""] * 17
        data_row = _make_sheet_row(
            date_fmt="07.03.2026",
            m_start="08:00",
            fuel="80",
            receipts="001",
            drivers="Іван",
        )
        ws = _make_worksheet([header1, header2, data_row])

        sheet_state = load_sheet_state(ws)
        app_data = aggregate_app_data()
        preview = build_sync_preview(sheet_state, app_data)

        assert preview["new_rows"] == []
        assert preview["safe_updates"] == []
        assert preview["conflicts"] == []

    def test_conflict_not_auto_applied(self):
        self._insert_log("refill", "2026-03-07 10:00:00", value="80", driver="Іван", receipt="001")

        header1 = [""] * 17
        header2 = [""] * 17
        data_row = _make_sheet_row(date_fmt="07.03.2026", fuel="75")  # sheet has 75, app has 80
        ws = _make_worksheet([header1, header2, data_row])

        sheet_state = load_sheet_state(ws)
        app_data = aggregate_app_data()
        preview = build_sync_preview(sheet_state, app_data)

        assert len(preview["conflicts"]) >= 1
        assert any(c["field"] == "fuel" for c in preview["conflicts"])

        ws2 = _make_mock_worksheet()
        result = apply_sync_decisions(ws2, preview, decisions=[])
        # conflict not applied (no decision)
        assert not any(r.get("field") == "fuel" for r in result["applied"])
        # fuel column N write should NOT have happened
        if ws2.batch_update.called:
            all_ranges = [
                e["range"]
                for call in ws2.batch_update.call_args_list
                for e in call[0][0]
            ]
            fuel_ranges = [r for r in all_ranges if r.startswith("N")]
            assert fuel_ranges == []

    def test_conflict_resolved_keep_app(self):
        self._insert_log("refill", "2026-03-07 10:00:00", value="80", driver="Іван", receipt="001")

        header1 = [""] * 17
        header2 = [""] * 17
        data_row = _make_sheet_row(date_fmt="07.03.2026", fuel="75")
        ws = _make_worksheet([header1, header2, data_row])

        sheet_state = load_sheet_state(ws)
        app_data = aggregate_app_data()
        preview = build_sync_preview(sheet_state, app_data)

        ws2 = _make_mock_worksheet()
        decisions = [{"date": "2026-03-07", "field": "fuel", "decision": "keep_app"}]
        result = apply_sync_decisions(ws2, preview, decisions=decisions)

        applied_fuel = [r for r in result["applied"] if r["field"] == "fuel"]
        assert len(applied_fuel) == 1
        assert applied_fuel[0]["app_value"] == "80"
        assert applied_fuel[0]["status"] == "applied_keep_app"


# ===========================================================================
# 9. build_preview_version — determinism and change detection
# ===========================================================================


class TestBuildPreviewVersion:
    """Tests for the build_preview_version() helper."""

    def _make_sheet_state(self, dates_fields: dict[str, dict]) -> dict:
        return {
            date: {"row_index": i + 3, "fields": fields}
            for i, (date, fields) in enumerate(dates_fields.items())
        }

    def _make_app_data(self, dates_fields: dict[str, dict]) -> dict:
        return {date: {"fields": fields} for date, fields in dates_fields.items()}

    def test_same_inputs_produce_same_version(self):
        """Identical inputs must produce the same token (determinism)."""
        sheet_state = self._make_sheet_state({"2026-03-07": {"fuel": "80", "m_start": "08:00"}})
        app_data = self._make_app_data({"2026-03-07": {"fuel": "80", "m_start": "08:00"}})
        v1 = build_preview_version(sheet_state, app_data)
        v2 = build_preview_version(sheet_state, app_data)
        assert v1 == v2

    def test_different_sheet_value_produces_different_version(self):
        """A change in sheet_state must produce a different token."""
        app_data = self._make_app_data({"2026-03-07": {"fuel": "80"}})
        ss1 = self._make_sheet_state({"2026-03-07": {"fuel": "75"}})
        ss2 = self._make_sheet_state({"2026-03-07": {"fuel": "80"}})
        assert build_preview_version(ss1, app_data) != build_preview_version(ss2, app_data)

    def test_different_app_value_produces_different_version(self):
        """A change in app_data must produce a different token."""
        sheet_state = self._make_sheet_state({"2026-03-07": {"fuel": "80"}})
        ad1 = self._make_app_data({"2026-03-07": {"fuel": "80"}})
        ad2 = self._make_app_data({"2026-03-07": {"fuel": "90"}})
        assert build_preview_version(sheet_state, ad1) != build_preview_version(sheet_state, ad2)

    def test_new_date_in_app_produces_different_version(self):
        """Adding a new date to app_data must produce a different token."""
        sheet_state = self._make_sheet_state({"2026-03-07": {"fuel": "80"}})
        ad1 = self._make_app_data({"2026-03-07": {"fuel": "80"}})
        ad2 = self._make_app_data({
            "2026-03-07": {"fuel": "80"},
            "2026-03-08": {"fuel": "50"},
        })
        assert build_preview_version(sheet_state, ad1) != build_preview_version(sheet_state, ad2)

    def test_empty_inputs_produce_stable_version(self):
        """Empty inputs should produce a consistent non-empty token."""
        v = build_preview_version({}, {})
        assert isinstance(v, str)
        assert len(v) == 16
        assert v == build_preview_version({}, {})

    def test_version_is_16_hex_chars(self):
        """Token should be a 16-character lowercase hex string."""
        sheet_state = self._make_sheet_state({"2026-03-07": {"fuel": "80"}})
        app_data = self._make_app_data({"2026-03-07": {"fuel": "80"}})
        v = build_preview_version(sheet_state, app_data)
        assert len(v) == 16
        assert all(c in "0123456789abcdef" for c in v)


# ===========================================================================
# 10. collect_batch_updates — batched write behavior
# ===========================================================================


class TestCollectBatchUpdates:
    """Unit tests for the collect_batch_updates() helper."""

    DATE = "2026-03-07"

    def _make_safe_update(self, field="fuel", column="N", app_val="80", row_index=5):
        return {
            "date": self.DATE,
            "row_index": row_index,
            "field": field,
            "column": column,
            "sheet_value": "",
            "app_value": app_val,
            "status": "safe_update",
        }

    def _make_conflict(self, field="fuel", column="N", sheet_val="75", app_val="80", row_index=5):
        return {
            "date": self.DATE,
            "row_index": row_index,
            "field": field,
            "column": column,
            "sheet_value": sheet_val,
            "app_value": app_val,
            "status": "conflict",
        }

    def test_empty_preview_returns_empty_batch(self):
        batch, applied, skipped = collect_batch_updates(
            {"new_rows": [], "safe_updates": [], "conflicts": []}
        )
        assert batch == []
        assert applied == []
        assert skipped == []

    def test_safe_update_produces_single_cell_entry(self):
        su = self._make_safe_update(column="N", app_val="80", row_index=5)
        batch, applied, skipped = collect_batch_updates(
            {"new_rows": [], "safe_updates": [su], "conflicts": []}
        )
        assert len(batch) == 1
        assert batch[0]["range"] == "N5:N5"
        assert batch[0]["values"] == [["80"]]
        assert len(applied) == 1
        assert applied[0]["status"] == "applied_safe_update"

    def test_conflict_without_decision_skipped_not_in_batch(self):
        conflict = self._make_conflict()
        batch, applied, skipped = collect_batch_updates(
            {"new_rows": [], "safe_updates": [], "conflicts": [conflict]}
        )
        assert batch == []
        assert applied == []
        assert len(skipped) == 1

    def test_keep_app_conflict_produces_cell_entry(self):
        conflict = self._make_conflict(column="N", app_val="80", row_index=5)
        decisions = [{"date": self.DATE, "field": "fuel", "decision": "keep_app"}]
        batch, applied, skipped = collect_batch_updates(
            {"new_rows": [], "safe_updates": [], "conflicts": [conflict]},
            decisions=decisions,
        )
        assert len(batch) == 1
        assert batch[0]["range"] == "N5:N5"
        assert batch[0]["values"] == [["80"]]
        assert applied[0]["status"] == "applied_keep_app"

    def test_new_row_produces_grouped_range_entries(self):
        """New rows should produce 3 grouped range entries (A:I, N, P:Q)."""
        new_row = {
            "date": self.DATE,
            "fields": {n: "" for n, _, _ in SYNC_FIELDS},
        }
        new_row["fields"]["date"] = "07.03.2026"
        new_row["fields"]["fuel"] = "80"
        new_row["fields"]["receipts"] = "001"
        new_row["fields"]["drivers"] = "Іван"

        batch, applied, skipped = collect_batch_updates(
            {"new_rows": [new_row], "safe_updates": [], "conflicts": []},
            current_row_count=2,
        )
        # 3 entries: A3:I3, N3:N3, P3:Q3
        assert len(batch) == 3
        ranges = {e["range"] for e in batch}
        assert "A3:I3" in ranges
        assert "N3:N3" in ranges
        assert "P3:Q3" in ranges

    def test_new_row_ai_range_contains_correct_values(self):
        new_row = {
            "date": self.DATE,
            "fields": {n: "" for n, _, _ in SYNC_FIELDS},
        }
        new_row["fields"]["date"] = "07.03.2026"
        new_row["fields"]["m_start"] = "08:00"

        batch, _, _ = collect_batch_updates(
            {"new_rows": [new_row], "safe_updates": [], "conflicts": []},
            current_row_count=2,
        )
        ai_entry = next(e for e in batch if e["range"] == "A3:I3")
        values = ai_entry["values"][0]
        assert values[0] == "07.03.2026"   # A = date
        assert values[1] == "08:00"         # B = m_start

    def test_multiple_safe_updates_all_in_single_batch_list(self):
        su1 = self._make_safe_update(column="N", app_val="80", row_index=5)
        su2 = self._make_safe_update(field="m_start", column="B", app_val="08:00", row_index=5)
        batch, applied, _ = collect_batch_updates(
            {"new_rows": [], "safe_updates": [su1, su2], "conflicts": []}
        )
        assert len(batch) == 2
        assert len(applied) == 2

    def test_row_count_inferred_from_preview(self):
        """New row index is inferred from max existing row_index when current_row_count omitted."""
        su = self._make_safe_update(row_index=10)
        new_row = {"date": "2026-03-08", "fields": {n: "" for n, _, _ in SYNC_FIELDS}}
        batch, applied, _ = collect_batch_updates(
            {"new_rows": [new_row], "safe_updates": [su], "conflicts": []}
        )
        # New row should be at row 11 — check that range ends with ':X11'
        new_row_ranges = [e["range"] for e in batch if e["range"].endswith("11")]
        assert len(new_row_ranges) > 0, "New row should be placed at row 11"


# ===========================================================================
# 11. apply_sync_decisions — single batch_update call behavior
# ===========================================================================


class TestApplySyncDecisionsBatched:
    """Tests that apply_sync_decisions() uses a single batch_update() call."""

    DATE = "2026-03-07"

    def test_single_batch_update_call_for_mixed_writes(self):
        """All writes (safe_update + conflict) should be in one batch_update call."""
        ws = _make_mock_worksheet()
        su = {
            "date": self.DATE, "row_index": 5, "field": "fuel", "column": "N",
            "sheet_value": "", "app_value": "80", "status": "safe_update",
        }
        conflict = {
            "date": self.DATE, "row_index": 5, "field": "m_start", "column": "B",
            "sheet_value": "07:00", "app_value": "08:00", "status": "conflict",
        }
        decisions = [{"date": self.DATE, "field": "m_start", "decision": "keep_app"}]
        apply_sync_decisions(
            ws,
            {"new_rows": [], "safe_updates": [su], "conflicts": [conflict]},
            decisions=decisions,
        )
        # Despite two separate writes, only one batch_update call
        ws.batch_update.assert_called_once()
        entries = ws.batch_update.call_args[0][0]
        assert len(entries) == 2

    def test_no_batch_update_when_nothing_to_write(self):
        """batch_update must not be called when there are no writes."""
        ws = _make_mock_worksheet()
        apply_sync_decisions(ws, {"new_rows": [], "safe_updates": [], "conflicts": []})
        ws.batch_update.assert_not_called()

    def test_new_row_uses_grouped_ranges(self):
        """New rows use grouped range entries (fewer entries than per-cell)."""
        ws = _make_mock_worksheet()
        new_row = {
            "date": self.DATE,
            "fields": {n: "" for n, _, _ in SYNC_FIELDS},
        }
        new_row["fields"]["date"] = "07.03.2026"
        apply_sync_decisions(
            ws,
            {"new_rows": [new_row], "safe_updates": [], "conflicts": []},
            current_row_count=2,
        )
        ws.batch_update.assert_called_once()
        entries = ws.batch_update.call_args[0][0]
        # 3 grouped entries (A:I, N, P:Q) — not 12 individual cell writes
        assert len(entries) == 3


# ===========================================================================
# 12. Emergency generator exclusion — business rule enforcement
#
# Google Sheets sync is for the MAIN generator only (generator_id = 'main').
# Emergency generator records must NEVER appear in preview/apply payloads,
# create new rows, produce safe_updates or conflicts, or affect preview_version.
# ===========================================================================


class TestEmergencyGeneratorExclusion:
    """Enforce the business rule: only main-generator data reaches Google Sheets.

    Emergency generator logs (generator_id != MAIN_GENERATOR_ID) are
    completely excluded from the Sheets sync pipeline by design.
    """

    EMERGENCY_ID = "emergency"
    DATE = "2026-03-07"

    def _insert_log(
        self,
        event_type,
        timestamp,
        value=None,
        driver=None,
        receipt=None,
        user="test",
        generator_id="main",
    ):
        from database.models import get_connection

        conn = get_connection()
        conn.execute(
            "INSERT INTO logs"
            " (event_type, timestamp, user_name, value, driver_name, receipt_number, generator_id)"
            " VALUES (?,?,?,?,?,?,?)",
            (event_type, timestamp, user, value, driver, receipt, generator_id),
        )
        conn.commit()
        conn.close()

    # ------------------------------------------------------------------
    # aggregate_app_data excludes emergency logs entirely
    # ------------------------------------------------------------------

    def test_emergency_only_logs_return_empty(self):
        """When only emergency logs exist, aggregate_app_data() returns {}."""
        self._insert_log("m_start", f"{self.DATE} 08:00:00", generator_id=self.EMERGENCY_ID)
        self._insert_log(
            "refill", f"{self.DATE} 10:00:00",
            value="80", driver="Аварійний", receipt="E-001",
            generator_id=self.EMERGENCY_ID,
        )
        result = aggregate_app_data()
        assert result == {}, (
            "Emergency generator data must never appear in aggregate_app_data()"
        )

    def test_emergency_logs_ignored_when_main_also_exists(self):
        """Emergency logs for the same date as main logs are fully ignored."""
        # Main generator: shift and refill
        self._insert_log("m_start", f"{self.DATE} 08:00:00", generator_id=MAIN_GENERATOR_ID)
        self._insert_log(
            "refill", f"{self.DATE} 10:00:00",
            value="80", driver="Іван", receipt="001",
            generator_id=MAIN_GENERATOR_ID,
        )
        # Emergency generator: different values for the same date
        self._insert_log("m_start", f"{self.DATE} 06:00:00", generator_id=self.EMERGENCY_ID)
        self._insert_log(
            "refill", f"{self.DATE} 07:00:00",
            value="999", driver="АварійнийВодій", receipt="E-999",
            generator_id=self.EMERGENCY_ID,
        )

        result = aggregate_app_data()
        assert self.DATE in result
        fields = result[self.DATE]["fields"]

        # Shift time comes from main only (08:00, not 06:00)
        assert fields["m_start"] == "08:00", "Emergency shift time must not affect main shift"

        # Fuel comes from main only (80, not 80+999=1079)
        assert fields["fuel"] == "80", "Emergency refill must not be summed into main fuel"

        # Receipts and drivers from main only
        assert "E-999" not in fields["receipts"], "Emergency receipt must not appear"
        assert "АварійнийВодій" not in fields["drivers"], "Emergency driver must not appear"

    # ------------------------------------------------------------------
    # build_sync_preview: emergency-only data creates no new rows
    # ------------------------------------------------------------------

    def test_emergency_only_data_does_not_create_new_rows(self):
        """Emergency-only logs must not create new rows in the Sheets preview."""
        self._insert_log("m_start", f"{self.DATE} 08:00:00", generator_id=self.EMERGENCY_ID)
        self._insert_log(
            "refill", f"{self.DATE} 10:00:00",
            value="50", driver="Аварійний", receipt="E-001",
            generator_id=self.EMERGENCY_ID,
        )

        app_data = aggregate_app_data()
        assert app_data == {}, "Precondition: no main data"

        preview = build_sync_preview({}, app_data)
        assert preview["new_rows"] == [], "Emergency data must not create new rows"
        assert preview["safe_updates"] == []
        assert preview["conflicts"] == []

    # ------------------------------------------------------------------
    # build_sync_preview: emergency-only data creates no safe_updates
    # ------------------------------------------------------------------

    def test_emergency_data_does_not_produce_safe_updates(self):
        """An existing sheet row with emergency-only data produces no safe_updates."""
        self._insert_log(
            "refill", f"{self.DATE} 10:00:00",
            value="50", driver="Аварійний", receipt="E-001",
            generator_id=self.EMERGENCY_ID,
        )

        app_data = aggregate_app_data()  # empty — emergency excluded
        # Sheet has existing row, app has nothing (emergency excluded)
        sheet = _make_sheet_state(self.DATE, fuel="")
        preview = build_sync_preview(sheet, app_data)

        assert preview["safe_updates"] == [], "Emergency data must not produce safe_updates"

    # ------------------------------------------------------------------
    # build_sync_preview: emergency-only differences do not create conflicts
    # ------------------------------------------------------------------

    def test_emergency_data_does_not_produce_conflicts(self):
        """Emergency data that differs from Sheets must not produce conflicts."""
        self._insert_log(
            "refill", f"{self.DATE} 10:00:00",
            value="99", driver="Аварійний", receipt="E-001",
            generator_id=self.EMERGENCY_ID,
        )

        app_data = aggregate_app_data()  # empty — emergency excluded
        # Sheet has value; emergency data has different value but is excluded
        sheet = _make_sheet_state(self.DATE, fuel="75")
        preview = build_sync_preview(sheet, app_data)

        assert preview["conflicts"] == [], "Emergency differences must not create conflicts"

    # ------------------------------------------------------------------
    # apply_sync_decisions: emergency data is never written to Sheets
    # ------------------------------------------------------------------

    def test_emergency_data_never_written_during_apply(self):
        """apply_sync_decisions must not write emergency data to the worksheet."""
        self._insert_log("m_start", f"{self.DATE} 08:00:00", generator_id=self.EMERGENCY_ID)
        self._insert_log(
            "refill", f"{self.DATE} 10:00:00",
            value="80", driver="Аварійний", receipt="E-001",
            generator_id=self.EMERGENCY_ID,
        )

        ws = _make_worksheet([["H1"] * 17, ["H2"] * 17])
        sheet_state = load_sheet_state(ws)
        app_data = aggregate_app_data()  # empty
        preview = build_sync_preview(sheet_state, app_data)

        ws2 = MagicMock()
        ws2.batch_update = MagicMock()
        apply_sync_decisions(ws2, preview, decisions=[])

        ws2.batch_update.assert_not_called(), (
            "No writes should occur when only emergency data exists"
        )

    # ------------------------------------------------------------------
    # build_preview_version: only emergency-data change does not bump version
    # ------------------------------------------------------------------

    def test_preview_version_unchanged_when_only_emergency_data_changes(self):
        """preview_version must not change when only emergency logs are added/modified."""
        # Version with no logs
        app_data_before = aggregate_app_data()
        sheet_state = {}
        version_before = build_preview_version(sheet_state, app_data_before)

        # Add emergency-only log — main data unchanged
        self._insert_log("m_start", f"{self.DATE} 08:00:00", generator_id=self.EMERGENCY_ID)

        app_data_after = aggregate_app_data()
        version_after = build_preview_version(sheet_state, app_data_after)

        assert version_before == version_after, (
            "preview_version must not change when only emergency-generator data changes"
        )

    # ------------------------------------------------------------------
    # Mixed scenario: main data unchanged by presence of emergency data
    # ------------------------------------------------------------------

    def test_preview_version_changes_only_for_main_data(self):
        """preview_version changes when main data is added, regardless of emergency data."""
        sheet_state = {}

        # Add emergency-only log — version should NOT change
        self._insert_log("m_start", f"{self.DATE} 08:00:00", generator_id=self.EMERGENCY_ID)
        app_data_emergency_only = aggregate_app_data()
        v_emergency = build_preview_version(sheet_state, app_data_emergency_only)

        # Add main log — version SHOULD change
        self._insert_log("m_start", f"{self.DATE} 08:00:00", generator_id=MAIN_GENERATOR_ID)
        app_data_with_main = aggregate_app_data()
        v_with_main = build_preview_version(sheet_state, app_data_with_main)

        assert v_emergency != v_with_main, (
            "preview_version must change when main-generator data is added"
        )
