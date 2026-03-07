"""Модуль експорту з БД в Google Sheets — preview + conflict-aware sync.

Синхронізація розбита на явні етапи:
  1. load_sheet_state()     — читаємо поточний стан Sheets
  2. aggregate_app_data()   — агрегуємо дані з БД/логів
  3. build_sync_preview()   — порівнюємо, класифікуємо зміни (dry-run)
  4. apply_sync_decisions() — застосовуємо затверджені зміни

Колонки, які синхронізуємо (інші — зокрема J:M та O — не чіпаємо):
  A   = дата (ДД.ММ.РРРР)
  B:I = часи старт/стоп змін 1..4 (HH:MM)
  N   = привезено палива за день (ПРИВЕЗЕНО ПАЛИВА)
  P   = номер(и) чека
  Q   = хто привіз паливо (імена)

Правила конфліктів (Sheets — джерело правди):
  - Sheets порожнє, App порожнє  → пропустити (синхронізовано)
  - Sheets порожнє, App має дані → safe_update
  - Sheets має дані, App порожнє → пропустити (зберігаємо Sheets)
  - Обидва мають однакові дані   → пропустити (синхронізовано)
  - Обидва мають різні дані      → conflict (потрібне явне рішення)
"""

import hashlib
import json
import logging
from collections import defaultdict
from datetime import datetime

import config
from database.models import get_connection
from services.google_sync_parts.client import make_client, open_spreadsheet, open_main_worksheet

logger = logging.getLogger(__name__)


_MAX_COL = 27  # A..AA (використовуємо тільки частину колонок)

# ---------------------------------------------------------------------------
# SYNC_FIELDS: ordered list of (field_name, zero-based_col_index, col_letter)
# J:M (9-12) and O (14) are intentionally excluded — calculated columns.
# ---------------------------------------------------------------------------
SYNC_FIELDS: list[tuple[str, int, str]] = [
    ("date",     0,  "A"),
    ("m_start",  1,  "B"),
    ("m_end",    2,  "C"),
    ("d_start",  3,  "D"),
    ("d_end",    4,  "E"),
    ("e_start",  5,  "F"),
    ("e_end",    6,  "G"),
    ("x_start",  7,  "H"),
    ("x_end",    8,  "I"),
    ("fuel",     13, "N"),
    ("receipts", 15, "P"),
    ("drivers",  16, "Q"),
]

# Convenience lookups derived from SYNC_FIELDS
_FIELD_MAP: dict[str, tuple[int, str]] = {name: (idx, letter) for name, idx, letter in SYNC_FIELDS}
_COL_TO_FIELD: dict[int, str] = {idx: name for name, idx, _letter in SYNC_FIELDS}


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _parse_ts(ts_str: str) -> datetime | None:
    """Парсить timestamp з БД (YYYY-MM-DD HH:MM:SS)."""
    if not ts_str:
        return None
    try:
        return datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def _time_to_hhmm(dt: datetime | None) -> str:
    if not dt:
        return ""
    return dt.strftime("%H:%M")


def _unique_join(items: list[str]) -> str:
    """Join unique non-empty strings, preserving order."""
    out = []
    seen = set()
    for x in items:
        x = (x or "").strip()
        if not x or x in seen:
            continue
        out.append(x)
        seen.add(x)
    return ", ".join(out)


def _format_fuel(total_refill: float) -> str:
    """Format fuel amount as string: integer if whole, else 1 decimal place."""
    if not total_refill:
        return ""
    if abs(total_refill - round(total_refill)) < 1e-6:
        return str(int(round(total_refill)))
    return str(round(total_refill, 1))


def _normalize_value(field_name: str, value: str) -> str:
    """Normalize a field value for comparison to avoid false conflicts.

    For numeric fields (fuel) both '80' and '80.0' normalize to '80'.
    """
    val = (value or "").strip()
    if field_name == "fuel" and val:
        try:
            f = float(val.replace(",", ".").replace("\u00a0", ""))
            if abs(f - round(f)) < 1e-6:
                return str(int(round(f)))
            return str(round(f, 1))
        except Exception:
            pass
    return val


# ---------------------------------------------------------------------------
# Stage 1: load_sheet_state
# ---------------------------------------------------------------------------

def load_sheet_state(worksheet) -> dict[str, dict]:
    """Read current state from Google Sheets worksheet.

    Returns:
        dict mapping date_iso (YYYY-MM-DD) to::

            {
                "row_index": int,          # 1-based sheet row number
                "fields": {field_name: str_value, ...}
            }

        Only SYNC_FIELDS columns are included; J:M and O are ignored.
    """
    all_values = worksheet.get_all_values()
    state: dict[str, dict] = {}

    for idx, row in enumerate(all_values[2:], start=3):  # data rows start at row 3
        if not row or not (row[0] or "").strip():
            continue
        date_cell = (row[0] or "").strip()
        try:
            dt = datetime.strptime(date_cell, "%d.%m.%Y")
            date_iso = dt.strftime("%Y-%m-%d")
        except Exception:
            continue

        fields: dict[str, str] = {}
        for field_name, col_idx, _col_letter in SYNC_FIELDS:
            fields[field_name] = (row[col_idx] or "").strip() if col_idx < len(row) else ""

        state[date_iso] = {"row_index": idx, "fields": fields}

    return state


# ---------------------------------------------------------------------------
# Stage 2: aggregate_app_data
# ---------------------------------------------------------------------------

def _aggregate_logs_by_date(from_date: str | None = None):
    """Групує логи по датах для експорту в основну вкладку.

    Якщо from_date задано, залишаються тільки дні >= from_date.
    """
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT event_type, timestamp, user_name, value, driver_name, receipt_number
        FROM logs
        ORDER BY timestamp ASC
    """)
    rows = cur.fetchall()
    conn.close()

    days = defaultdict(
        lambda: {
            "shifts": {"m": {}, "d": {}, "e": {}, "x": {}},
            "refills": [],  # [(amount, driver, receipt), ...]
        }
    )

    for event, ts_str, user, value, driver, receipt in rows:
        dt = _parse_ts(ts_str)
        if not dt:
            continue

        date_str = dt.strftime("%Y-%m-%d")
        day = days[date_str]

        if event.endswith("_start"):
            shift = event.split("_")[0]
            day["shifts"][shift]["start"] = dt
            day["shifts"][shift]["start_user"] = (user or "").strip()

        elif event.endswith("_end"):
            shift = event.split("_")[0]
            day["shifts"][shift]["end"] = dt
            day["shifts"][shift]["end_user"] = (user or "").strip()

        elif event == "refill":
            try:
                amount = float(value or 0)
            except Exception:
                amount = 0.0
            day["refills"].append((amount, (driver or "").strip(), (receipt or "").strip()))

    if from_date:
        days = {d: data for d, data in days.items() if d >= from_date}

    return days


def aggregate_app_data(from_date: str | None = None) -> dict[str, dict]:
    """Aggregate app/DB data into a normalized field dict per date.

    Returns:
        dict mapping date_iso (YYYY-MM-DD) to::

            {"fields": {field_name: str_value, ...}}

        All field values are strings; fuel is formatted as an integer string
        when it has no fractional part (e.g. ``"80"``), otherwise 1 decimal
        (e.g. ``"80.5"``).
    """
    raw = _aggregate_logs_by_date(from_date=from_date)
    result: dict[str, dict] = {}

    _col_time_map = {
        "m": ("m_start", "m_end"),
        "d": ("d_start", "d_end"),
        "e": ("e_start", "e_end"),
        "x": ("x_start", "x_end"),
    }

    for date_str in sorted(raw.keys()):
        day = raw[date_str]
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        fields: dict[str, str] = {}

        # A: date
        fields["date"] = dt.strftime("%d.%m.%Y")

        # B-I: shift times
        for shift, (f_start, f_end) in _col_time_map.items():
            s = day["shifts"].get(shift, {})
            fields[f_start] = _time_to_hhmm(s.get("start"))
            fields[f_end] = _time_to_hhmm(s.get("end"))

        # N: total delivered fuel
        total_refill = sum(r[0] for r in day["refills"]) if day["refills"] else 0.0
        fields["fuel"] = _format_fuel(total_refill)

        # P: unique receipt numbers joined by comma
        receipts = [rec for _amt, _drv, rec in day["refills"]] if day["refills"] else []
        fields["receipts"] = _unique_join(receipts)

        # Q: unique driver/person names joined by comma
        drivers = [drv for _amt, drv, _rec in day["refills"]] if day["refills"] else []
        fields["drivers"] = _unique_join(drivers)

        result[date_str] = {"fields": fields}

    return result


# ---------------------------------------------------------------------------
# Preview versioning
# ---------------------------------------------------------------------------

def build_preview_version(sheet_state: dict[str, dict], app_data: dict[str, dict]) -> str:
    """Build a deterministic version token from sheet_state and app_data snapshots.

    The token is a hex digest of the JSON-serialized, sort-key-normalized
    combination of both inputs.  Any change to either side (new date, field
    value update, etc.) produces a different token.

    Args:
        sheet_state: output of :func:`load_sheet_state`.
        app_data:    output of :func:`aggregate_app_data`.

    Returns:
        A 16-character lowercase hex string that uniquely represents the
        comparison basis used by :func:`build_sync_preview`.
    """
    snapshot = {
        "sheet_state": {
            k: {"row_index": v["row_index"], "fields": dict(sorted(v["fields"].items()))}
            for k, v in sorted(sheet_state.items())
        },
        "app_data": {
            k: {"fields": dict(sorted(v["fields"].items()))}
            for k, v in sorted(app_data.items())
        },
    }
    serialized = json.dumps(snapshot, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialized.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Stage 3: build_sync_preview (dry-run)
# ---------------------------------------------------------------------------

def build_sync_preview(
    sheet_state: dict[str, dict],
    app_data: dict[str, dict],
) -> dict[str, list]:
    """Compare app data with current Sheets state and classify changes.

    Args:
        sheet_state: output of :func:`load_sheet_state`.
        app_data:    output of :func:`aggregate_app_data`.

    Returns:
        A preview dict with three groups:

        - **new_rows** — dates that do not yet exist in the sheet::

              [{"date": "YYYY-MM-DD", "fields": {field: value, ...}}, ...]

        - **safe_updates** — fields where Sheets is empty and app has a value::

              [{"date", "row_index", "field", "column",
                "sheet_value", "app_value", "status": "safe_update"}, ...]

        - **conflicts** — fields where both sides have non-empty, differing values::

              [{"date", "row_index", "field", "column",
                "sheet_value", "app_value", "status": "conflict"}, ...]

    Conflict-resolution rules (Sheets = source of truth):

    ============  ==========  ==============================
    Sheets        App         Action
    ============  ==========  ==============================
    empty         empty       skip (in sync)
    empty         has value   safe_update
    has value     empty       skip (keep Sheets)
    same value    same value  skip (in sync)
    differs       differs     conflict (explicit decision needed)
    ============  ==========  ==============================
    """
    new_rows: list[dict] = []
    safe_updates: list[dict] = []
    conflicts: list[dict] = []

    # Fields to compare per existing row (date is the row key, not compared field-by-field)
    compare_fields = [name for name, _idx, _letter in SYNC_FIELDS if name != "date"]

    for date_iso in sorted(app_data.keys()):
        app_fields = app_data[date_iso]["fields"]

        if date_iso not in sheet_state:
            new_rows.append({"date": date_iso, "fields": dict(app_fields)})
            continue

        row_info = sheet_state[date_iso]
        row_index = row_info["row_index"]
        sheet_fields = row_info["fields"]

        for field_name in compare_fields:
            _col_idx, col_letter = _FIELD_MAP[field_name]
            sheet_val = _normalize_value(field_name, sheet_fields.get(field_name, ""))
            app_val = _normalize_value(field_name, str(app_fields.get(field_name) or ""))

            if not sheet_val and not app_val:
                continue  # both empty → in sync

            if sheet_val and not app_val:
                continue  # Sheets has value, app empty → keep Sheets (source of truth)

            entry = {
                "date": date_iso,
                "row_index": row_index,
                "field": field_name,
                "column": col_letter,
                "sheet_value": sheet_val,
                "app_value": app_val,
            }

            if not sheet_val and app_val:
                safe_updates.append({**entry, "status": "safe_update"})
            elif sheet_val != app_val:
                conflicts.append({**entry, "status": "conflict"})
            # else: equal → in sync, skip

    return {"new_rows": new_rows, "safe_updates": safe_updates, "conflicts": conflicts}


# ---------------------------------------------------------------------------
# Stage 4 helpers: collect_batch_updates, apply_sync_decisions
# ---------------------------------------------------------------------------

# Contiguous column groups used to build efficient range updates for new rows.
# Each entry is (start_col_letter, end_col_letter, [field_names_in_order]).
_NEW_ROW_RANGE_GROUPS: list[tuple[str, str, list[str]]] = [
    ("A", "I", ["date", "m_start", "m_end", "d_start", "d_end", "e_start", "e_end", "x_start", "x_end"]),
    ("N", "N", ["fuel"]),
    ("P", "Q", ["receipts", "drivers"]),
]


def collect_batch_updates(
    preview: dict[str, list],
    decisions: list[dict] | None = None,
    current_row_count: int | None = None,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Collect all approved writes as batch-update entries without touching the worksheet.

    This is the pure-logic core of :func:`apply_sync_decisions`.  It is kept
    separate so callers can inspect the planned writes before committing them.

    Args:
        preview:           output of :func:`build_sync_preview`.
        decisions:         conflict-resolution decisions (same format as
                           :func:`apply_sync_decisions`).
        current_row_count: total rows currently in the sheet; used to compute
                           row indices for new rows.  Inferred from preview when
                           omitted.

    Returns:
        A 3-tuple ``(batch_updates, applied, skipped)`` where:

        - **batch_updates** — list of ``{"range": str, "values": [[str, ...]]}``
          dicts ready to pass to ``worksheet.batch_update()``.  New rows are
          represented as grouped range entries (A:I, N, P:Q per row) to
          minimise the number of entries.  Individual cell updates are used for
          safe_updates and approved conflict writes.
        - **applied** — change records with ``status`` set to the applied action.
        - **skipped** — change records with ``status = "skipped_keep_sheet"``.
    """
    decisions = decisions or []
    applied: list[dict] = []
    skipped: list[dict] = []
    batch_updates: list[dict] = []

    # --- Parse decisions ---
    global_decision: str | None = None
    per_field: dict[tuple[str, str], str] = {}  # (date_iso, field_name) -> decision

    for dec in decisions:
        dval = dec.get("decision", "")
        if dval in ("keep_app_all", "keep_sheet_all"):
            global_decision = dval
        elif "date" in dec and "field" in dec:
            per_field[(dec["date"], dec["field"])] = dval

    # --- Determine starting row for new rows ---
    if current_row_count is None:
        existing_indices = [
            item["row_index"]
            for group in (preview.get("safe_updates", []), preview.get("conflicts", []))
            for item in group
        ]
        current_row_count = max(existing_indices, default=2)

    # --- 1. Collect new rows (grouped range writes per contiguous column block) ---
    for new_row in preview.get("new_rows", []):
        current_row_count += 1
        row_idx = current_row_count
        date_iso = new_row["date"]
        fields = new_row["fields"]

        # Batch entries: 3 grouped range writes per row (A:I, N, P:Q)
        for col_start, col_end, field_names in _NEW_ROW_RANGE_GROUPS:
            values = [str(fields.get(fn) or "") for fn in field_names]
            rng = f"{col_start}{row_idx}:{col_end}{row_idx}"
            batch_updates.append({"range": rng, "values": [values]})

        # Applied records: one entry per field (for API response / audit trail)
        # This is intentionally finer-grained than the batch entries above.
        for field_name, _col_idx, col_letter in SYNC_FIELDS:
            val = str(fields.get(field_name) or "")
            applied.append({
                "date": date_iso,
                "row_index": row_idx,
                "field": field_name,
                "column": col_letter,
                "sheet_value": "",
                "app_value": val,
                "status": "new_row",
            })

    # --- 2. Collect safe updates (one entry per cell) ---
    for item in preview.get("safe_updates", []):
        rng = f"{item['column']}{item['row_index']}:{item['column']}{item['row_index']}"
        batch_updates.append({"range": rng, "values": [[item["app_value"]]]})
        applied.append({**item, "status": "applied_safe_update"})

    # --- 3. Collect conflict resolutions ---
    for item in preview.get("conflicts", []):
        key = (item["date"], item["field"])
        decision = per_field.get(key) or global_decision

        if decision in ("keep_app", "keep_app_all"):
            rng = f"{item['column']}{item['row_index']}:{item['column']}{item['row_index']}"
            batch_updates.append({"range": rng, "values": [[item["app_value"]]]})
            applied.append({**item, "status": "applied_keep_app"})
        else:
            skipped.append({**item, "status": "skipped_keep_sheet"})

    return batch_updates, applied, skipped


def apply_sync_decisions(
    worksheet,
    preview: dict[str, list],
    decisions: list[dict] | None = None,
    current_row_count: int | None = None,
) -> dict[str, list]:
    """Apply approved changes to the worksheet using batched range updates.

    All writes are collected via :func:`collect_batch_updates` and sent to the
    Google Sheets API in a single ``batch_update`` call, reducing the number of
    API round-trips compared to per-cell ``update`` calls.

    Args:
        worksheet:         gspread Worksheet object.
        preview:           output of :func:`build_sync_preview`.
        decisions:         list of conflict-resolution decisions.  Each item is
                           either a per-field decision::

                               {"date": "YYYY-MM-DD", "field": "fuel",
                                "decision": "keep_app" | "keep_sheet"}

                           or a global decision applied to *all* unresolved
                           conflicts::

                               {"decision": "keep_app_all"}
                               {"decision": "keep_sheet_all"}

                           Per-field decisions take precedence over global ones.
        current_row_count: total number of rows currently in the sheet (used to
                           append new rows).  If omitted it is inferred from
                           the highest ``row_index`` found in the preview.

    Processing order:

    1. **new_rows** — always applied (no conflict possible); written as grouped
       range updates (A:I, N, P:Q per row).
    2. **safe_updates** — always applied (Sheets was empty); one entry per cell.
    3. **conflicts** — applied only when an explicit ``keep_app`` decision
       exists; otherwise the Sheets value is preserved.

    Returns:
        ``{"applied": [...], "skipped": [...]}`` where each item is a field
        change record with a ``status`` field indicating what happened.
    """
    batch_updates, applied, skipped = collect_batch_updates(
        preview,
        decisions=decisions,
        current_row_count=current_row_count,
    )

    if batch_updates:
        worksheet.batch_update(batch_updates, value_input_option="USER_ENTERED")

    return {"applied": applied, "skipped": skipped}


# ---------------------------------------------------------------------------
# Public: full_export (backward-compatible, now uses the new pipeline)
# ---------------------------------------------------------------------------

def full_export():
    """Export from DB to Google Sheets using the preview + conflict-aware pipeline.

    - new_rows (dates not yet in Sheets): always applied.
    - safe_updates (Sheets empty, app has value): always applied.
    - conflicts (both sides differ): skipped; returned for UI review.

    Returns:
        ``{"updated": [...], "skipped": [...], "conflicts": [...]}``

        ``updated``  — sorted list of date strings that were written.
        ``skipped``  — sorted list of date strings whose conflicts were left
                       unchanged (Sheets preserved).
        ``conflicts``— list of conflict detail dicts for UI/manual resolution.
    """
    logger.info("📤 Починаємо експорт з БД в Sheets (preview + conflict-aware)...")

    client = make_client()
    ss = open_spreadsheet(client)
    main_sheet = open_main_worksheet(ss)

    # Stage 1: read current sheet state
    sheet_state = load_sheet_state(main_sheet)

    # Stage 2: aggregate app/DB data
    app_data = aggregate_app_data(from_date=None)

    if not app_data:
        logger.info("ℹ️ Немає даних у логах для експорту")
        return {"updated": [], "skipped": [], "conflicts": []}

    # Stage 3: dry-run preview
    preview = build_sync_preview(sheet_state, app_data)

    logger.info(
        "📊 Preview: нових рядків=%s, безпечних оновлень=%s, конфліктів=%s",
        len(preview["new_rows"]),
        len(preview["safe_updates"]),
        len(preview["conflicts"]),
    )
    for c in preview["conflicts"]:
        logger.warning(
            "⚠️ Конфлікт %s [%s] поле=%s: Sheets=%r App=%r",
            c["date"], c["column"], c["field"], c["sheet_value"], c["app_value"],
        )

    # Stage 4: apply — no decisions passed, so conflicts are left untouched
    current_row_count = max(
        (info["row_index"] for info in sheet_state.values()),
        default=2,
    )
    result = apply_sync_decisions(
        main_sheet,
        preview,
        decisions=[],
        current_row_count=current_row_count,
    )

    updated_dates = sorted({r["date"] for r in result["applied"]})
    skipped_dates = sorted({r["date"] for r in result["skipped"]})
    conflict_details = [
        {
            "date": c["date"],
            "row_index": c["row_index"],
            "field": c["field"],
            "column": c["column"],
            "sheet_value": c["sheet_value"],
            "app_value": c["app_value"],
            "status": "conflict",
        }
        for c in preview["conflicts"]
    ]

    logger.info(
        "✅ Експорт завершено! Оновлено: %s; конфліктів (пропущено): %s",
        len(updated_dates),
        len(conflict_details),
    )
    return {"updated": updated_dates, "skipped": skipped_dates, "conflicts": conflict_details}


# ---------------------------------------------------------------------------
# Legacy helper (kept for internal/backward-compat callers of _build_export_rows)
# ---------------------------------------------------------------------------

def _build_export_rows(days_data):
    """Build flat export rows for legacy usage."""
    rows = []

    for date_str in sorted(days_data.keys()):
        day = days_data[date_str]
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        row = [""] * _MAX_COL

        row[0] = dt.strftime("%d.%m.%Y")

        col_time = {"m": (1, 2), "d": (3, 4), "e": (5, 6), "x": (7, 8)}
        for shift, (c_start, c_end) in col_time.items():
            s = day["shifts"].get(shift, {})
            row[c_start] = _time_to_hhmm(s.get("start"))
            row[c_end] = _time_to_hhmm(s.get("end"))

        total_refill = sum(r[0] for r in day["refills"]) if day["refills"] else 0.0
        if total_refill:
            if abs(total_refill - round(total_refill)) < 1e-6:
                row[13] = int(round(total_refill))
            else:
                row[13] = round(total_refill, 1)
        else:
            row[13] = ""

        receipts = [rec for _amt, _drv, rec in day["refills"]] if day["refills"] else []
        row[15] = _unique_join(receipts)

        drivers = [drv for _amt, drv, _rec in day["refills"]] if day["refills"] else []
        row[16] = _unique_join(drivers)

        rows.append(row)

    return rows
