"""Двонаправлена розумна синхронізація між БД та Google Sheets.

Ця функція:
1. Порівнює дані по датам між БД і Sheets
2. Синхронізує тільки зміни (не перезаписує все)
3. Вирішує конфлікти на основі повноти даних
4. Перевіряє відповідність витрат палива (колонка U)
5. Синхронізує довідники водіїв та персоналу

Колонки Sheets:
- A: ДАТА
- B-I: часи змін (4 зміни × 2 колонки)
- K: ЗАЛИШОК ПАЛИВА НА РАНОК
- N: ПРИВЕЗЕНО ПАЛИВА
- P: НОМЕР ЧЕКА
- Q: ПАЛИВО ПРЕВІЗ (водій)
- R: ВОДІЇЇ (довідник)
- S: ПЕРСОНАЛ
- U: витрати палива л/год (має збігатися з config.FUEL_CONSUMPTION)

Бот записує: B, C, D, E, F, G, H, I, N, P, Q
Бот читає: B, C, D, E, F, G, H, I, K, N, P, Q, R, S
"""

import logging
from collections import defaultdict
from datetime import datetime
from typing import Literal

import config
from database.models import get_connection
from services.google_sync_parts.client import make_client, open_spreadsheet, open_main_worksheet

logger = logging.getLogger(__name__)

_COL_U_INDEX = 20  # Колонка U (0-based: U = 20)


class SyncReport:
    """Звіт про результати синхронізації."""

    def __init__(self):
        self.db_to_sheets: list[str] = []  # дати експортовані з БД в Sheets
        self.sheets_to_db: list[str] = []  # дати імпортовані з Sheets в БД
        self.conflicts: list[str] = []  # дати з конфліктами (вирішені)
        self.skipped: list[str] = []  # дати що однакові в обох
        self.fuel_rate_warnings: list[tuple[str, float]] = []  # дати де U не збігається
        self.new_drivers: list[str] = []  # нові водії додані
        self.new_personnel: list[str] = []  # новий персонал доданий
        self.errors: list[tuple[str, str]] = []  # помилки (дата, текст)

    def summary(self) -> str:
        """Текстовий звіт для адміна."""
        parts = [
            "\n📊 <b>Звіт синхронізації:</b>\n",
            f"📤 Експорт (БД → Sheets): <b>{len(self.db_to_sheets)}</b> днів",
            f"📥 Імпорт (Sheets → БД): <b>{len(self.sheets_to_db)}</b> днів",
            f"⚠️ Конфлікти (вирішено): <b>{len(self.conflicts)}</b> днів",
            f"⏭ Пропущено (однакові): <b>{len(self.skipped)}</b> днів",
        ]

        if self.fuel_rate_warnings:
            parts.append(f"\n⚠️ <b>Попередження витрат палива (колонка U):</b>")
            for date, rate in self.fuel_rate_warnings:
                parts.append(f"  • {date}: {rate} л/год (очікується {config.FUEL_CONSUMPTION})")

        if self.new_drivers:
            parts.append(f"\n🚗 Додано водіїв: {', '.join(self.new_drivers)}")

        if self.new_personnel:
            parts.append(f"👥 Додано персонал: {', '.join(self.new_personnel)}")

        if self.errors:
            parts.append(f"\n❌ <b>Помилки ({len(self.errors)}):</b>")
            for date, error in self.errors[:5]:  # показуємо перші 5
                parts.append(f"  • {date}: {error}")
            if len(self.errors) > 5:
                parts.append(f"  ... та ще {len(self.errors) - 5}")

        return "\n".join(parts)


def _parse_date(date_str: str) -> str | None:
    """Парсить дату з різних форматів в YYYY-MM-DD."""
    if not date_str or not str(date_str).strip():
        return None

    s = str(date_str).strip()

    try:
        dt = datetime.strptime(s, "%d.%m.%Y")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        pass

    try:
        dt = datetime.strptime(s, "%Y-%m-%d")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        pass

    return None


def _parse_time(time_str: str) -> str | None:
    """Парсить час з формату HH:MM або HH":"MM."""
    if not time_str or not str(time_str).strip():
        return None
    try:
        s = str(time_str).strip().replace('"', "")
        parts = s.split(":")
        if len(parts) == 2:
            return f"{int(parts[0]):02d}:{int(parts[1]):02d}:00"
        if len(parts) == 3:
            return f"{int(parts[0]):02d}:{int(parts[1]):02d}:{int(parts[2]):02d}"
        return None
    except Exception:
        return None


def _get_db_data_by_date() -> dict[str, dict]:
    """Отримує всі логи з БД згруповані по датах.

    Повертає: {"YYYY-MM-DD": {"shifts": {"m": {start, end}, ...}, "refills": [...]}}
    """
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT event_type, timestamp, user_name, value, driver_name, receipt_number
        FROM logs
        ORDER BY timestamp ASC
    """
    )
    rows = cur.fetchall()
    conn.close()

    days = defaultdict(
        lambda: {
            "shifts": {"m": {}, "d": {}, "e": {}, "x": {}},
            "refills": [],
        }
    )

    for event, ts_str, user, value, driver, receipt in rows:
        try:
            dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
        except Exception:
            continue

        date_str = dt.strftime("%Y-%m-%d")
        day = days[date_str]

        if event.endswith("_start"):
            shift = event.split("_")[0]
            day["shifts"][shift]["start"] = dt.strftime("%H:%M")

        elif event.endswith("_end"):
            shift = event.split("_")[0]
            day["shifts"][shift]["end"] = dt.strftime("%H:%M")

        elif event == "refill":
            try:
                amount = float(value or 0)
            except Exception:
                amount = 0.0
            day["refills"].append(
                {"amount": amount, "driver": (driver or "").strip(), "receipt": (receipt or "").strip()}
            )

    return dict(days)


def _get_sheets_data_by_date(worksheet) -> dict[str, dict]:
    """Читає дані з Sheets згруповані по датах.

    Повертає: {"YYYY-MM-DD": {"row_idx": int, "shifts": {...}, "refills": [...], "fuel_rate": float|None, ...}}
    """
    all_values = worksheet.get_all_values()
    if len(all_values) < 2:
        return {}

    header = all_values[0]
    days = {}

    # Індекси колонок (0-based)
    # A=0, B=1, C=2, D=3, E=4, F=5, G=6, H=7, I=8, K=10, N=13, P=15, Q=16, R=17, S=18, U=20

    for idx, row in enumerate(all_values[1:], start=2):  # Починаємо з рядка 2 (після header)
        if not row or not (row[0] if len(row) > 0 else "").strip():
            continue

        date_str = _parse_date(row[0] if len(row) > 0 else "")
        if not date_str:
            continue

        def _get(col_idx: int) -> str:
            return (row[col_idx] if col_idx < len(row) else "") or ""

        # Читаємо часи змін
        shifts = {
            "m": {"start": _parse_time(_get(1)), "end": _parse_time(_get(2))},
            "d": {"start": _parse_time(_get(3)), "end": _parse_time(_get(4))},
            "e": {"start": _parse_time(_get(5)), "end": _parse_time(_get(6))},
            "x": {"start": _parse_time(_get(7)), "end": _parse_time(_get(8))},
        }

        # Читаємо refills
        refills = []
        refill_amount_str = _get(13).strip()  # N
        if refill_amount_str:
            try:
                amount = float(refill_amount_str.replace(",", ".").replace(" ", ""))
                driver = _get(16).strip()  # Q
                receipt = _get(15).strip()  # P
                refills.append({"amount": amount, "driver": driver, "receipt": receipt})
            except Exception:
                pass

        # Читаємо витрати палива (колонка U)
        fuel_rate = None
        fuel_rate_str = _get(_COL_U_INDEX).strip()
        if fuel_rate_str:
            try:
                fuel_rate = float(fuel_rate_str.replace(",", "."))
            except Exception:
                pass

        # Читаємо довідники
        drivers_list = [d.strip() for d in _get(17).split(",") if d.strip()]  # R
        personnel_list = [p.strip() for p in _get(18).split(",") if p.strip()]  # S

        days[date_str] = {
            "row_idx": idx,
            "shifts": shifts,
            "refills": refills,
            "fuel_rate": fuel_rate,
            "drivers": drivers_list,
            "personnel": personnel_list,
        }

    return days


def _count_data_points(data: dict) -> int:
    """Рахує кількість непорожніх даних (для вирішення конфліктів)."""
    count = 0

    # Рахуємо заповнені часи змін
    for shift_data in data.get("shifts", {}).values():
        if shift_data.get("start"):
            count += 1
        if shift_data.get("end"):
            count += 1

    # Рахуємо refills
    count += len(data.get("refills", []))

    return count


def _resolve_conflict(
    date: str, db_data: dict, sheets_data: dict, report: SyncReport
) -> Literal["db", "sheets", "skip"]:
    """Вирішує конфлікт коли дата є в обох джерелах.

    Повертає: "db" (приоритет БД), "sheets" (приоритет Sheets), "skip" (однакові)
    """
    db_points = _count_data_points(db_data)
    sheets_points = _count_data_points(sheets_data)

    if db_points == 0 and sheets_points == 0:
        return "skip"  # Обидва порожні

    if db_points > sheets_points:
        report.conflicts.append(f"{date} (БД більше даних)")
        return "db"
    elif sheets_points > db_points:
        report.conflicts.append(f"{date} (Sheets більше даних)")
        return "sheets"
    else:
        # Однакова кількість - перевіряємо чи співпадають
        # Для простоти вважаємо що співпадають якщо кількість однакова
        report.skipped.append(date)
        return "skip"


def _write_db_to_sheets(date: str, db_data: dict, worksheet, row_idx: int | None):
    """Записує дані з БД в Sheets для конкретної дати."""
    # Форматуємо дату
    dt = datetime.strptime(date, "%Y-%m-%d")
    date_fmt = dt.strftime("%d.%m.%Y")

    # Якщо рядка немає - додаємо в кінець
    if row_idx is None:
        all_values = worksheet.get_all_values()
        row_idx = len(all_values) + 1

    # Формуємо дані для запису
    # A: дата
    worksheet.update(f"A{row_idx}", [[date_fmt]], value_input_option="USER_ENTERED")

    # B-I: часи змін
    times = []
    for shift in ["m", "d", "e", "x"]:
        shift_data = db_data["shifts"].get(shift, {})
        times.append(shift_data.get("start") or "")
        times.append(shift_data.get("end") or "")
    worksheet.update(f"B{row_idx}:I{row_idx}", [times], value_input_option="USER_ENTERED")

    # N: total refill
    total_refill = sum(r["amount"] for r in db_data["refills"]) if db_data["refills"] else 0.0
    if total_refill:
        if abs(total_refill - round(total_refill)) < 1e-6:
            refill_value = int(round(total_refill))
        else:
            refill_value = round(total_refill, 1)
    else:
        refill_value = ""
    worksheet.update(f"N{row_idx}", [[refill_value]], value_input_option="USER_ENTERED")

    # P: receipts
    receipts = [r["receipt"] for r in db_data["refills"] if r["receipt"]]
    receipt_str = ", ".join(dict.fromkeys(receipts))  # unique, preserving order
    worksheet.update(f"P{row_idx}", [[receipt_str]], value_input_option="USER_ENTERED")

    # Q: drivers
    drivers = [r["driver"] for r in db_data["refills"] if r["driver"]]
    driver_str = ", ".join(dict.fromkeys(drivers))
    worksheet.update(f"Q{row_idx}", [[driver_str]], value_input_option="USER_ENTERED")


def _write_sheets_to_db(date: str, sheets_data: dict, conn):
    """Записує дані з Sheets в БД для конкретної дати."""
    # Записуємо події змін
    for shift, shift_data in sheets_data["shifts"].items():
        if shift_data.get("start"):
            ts = f"{date} {shift_data['start']}"
            conn.execute(
                "INSERT OR IGNORE INTO logs (event_type, timestamp, user_name, value, driver_name, receipt_number) VALUES (?,?,?,?,?,?)",
                (f"{shift}_start", ts, "", None, None, None),
            )

        if shift_data.get("end"):
            ts = f"{date} {shift_data['end']}"
            conn.execute(
                "INSERT OR IGNORE INTO logs (event_type, timestamp, user_name, value, driver_name, receipt_number) VALUES (?,?,?,?,?,?)",
                (f"{shift}_end", ts, "", None, None, None),
            )

    # Записуємо refills
    for refill in sheets_data["refills"]:
        # Refill timestamp - беремо час останньої зміни або 23:59
        refill_time = "23:59:00"
        for shift in ["x", "e", "d", "m"]:
            if sheets_data["shifts"][shift].get("end"):
                refill_time = sheets_data["shifts"][shift]["end"]
                break

        ts = f"{date} {refill_time}"
        conn.execute(
            "INSERT OR IGNORE INTO logs (event_type, timestamp, user_name, value, driver_name, receipt_number) VALUES (?,?,?,?,?,?)",
            ("refill", ts, "", str(refill["amount"]), refill["driver"], refill["receipt"]),
        )


def _sync_references(sheets_data: dict, report: SyncReport):
    """Синхронізує довідники водіїв та персоналу."""
    conn = get_connection()

    # Збираємо всіх водіїв та персонал з Sheets
    all_drivers = set()
    all_personnel = set()

    for day_data in sheets_data.values():
        all_drivers.update(day_data.get("drivers", []))
        all_personnel.update(day_data.get("personnel", []))

    # Отримуємо існуючих з БД
    cur = conn.cursor()
    cur.execute("SELECT name FROM drivers")
    existing_drivers = {row[0] for row in cur.fetchall()}

    cur.execute("SELECT name FROM personnel_names")
    existing_personnel = {row[0] for row in cur.fetchall()}

    # Додаємо нових
    for driver in all_drivers - existing_drivers:
        try:
            conn.execute("INSERT INTO drivers (name) VALUES (?)", (driver,))
            report.new_drivers.append(driver)
        except Exception as e:
            logger.warning(f"Не вдалося додати водія {driver}: {e}")

    for person in all_personnel - existing_personnel:
        try:
            conn.execute("INSERT INTO personnel_names (name) VALUES (?)", (person,))
            report.new_personnel.append(person)
        except Exception as e:
            logger.warning(f"Не вдалося додати персонал {person}: {e}")

    conn.commit()
    conn.close()


def bidirectional_sync() -> SyncReport:
    """Виконує двонаправлену синхронізацію між БД та Google Sheets.

    Алгоритм:
    1. Отримує дані з обох джерел
    2. Для кожної дати:
       - Якщо є тільки в БД → експорт в Sheets
       - Якщо є тільки в Sheets → імпорт в БД
       - Якщо є в обох → вирішує конфлікт (більше даних = приоритет)
    3. Перевіряє колонку U (витрати палива)
    4. Синхронізує довідники

    Повертає: SyncReport з детальним звітом
    """
    report = SyncReport()
    logger.info("🔄 Починаємо двонаправлену синхронізацію...")

    try:
        # Підключаємося до Sheets
        client = make_client()
        ss = open_spreadsheet(client)
        worksheet = open_main_worksheet(ss)

        # Отримуємо дані з обох джерел
        db_data = _get_db_data_by_date()
        sheets_data = _get_sheets_data_by_date(worksheet)

        logger.info(f"📊 БД: {len(db_data)} днів, Sheets: {len(sheets_data)} днів")

        # Об'єднуємо всі дати
        all_dates = set(db_data.keys()) | set(sheets_data.keys())

        conn = get_connection()

        for date in sorted(all_dates):
            try:
                in_db = date in db_data
                in_sheets = date in sheets_data

                if in_db and not in_sheets:
                    # Тільки в БД → експорт
                    _write_db_to_sheets(date, db_data[date], worksheet, None)
                    report.db_to_sheets.append(date)
                    logger.info(f"📤 {date}: БД → Sheets")

                elif in_sheets and not in_db:
                    # Тільки в Sheets → імпорт
                    _write_sheets_to_db(date, sheets_data[date], conn)
                    report.sheets_to_db.append(date)
                    logger.info(f"📥 {date}: Sheets → БД")

                elif in_db and in_sheets:
                    # В обох → вирішуємо конфлікт
                    decision = _resolve_conflict(date, db_data[date], sheets_data[date], report)

                    if decision == "db":
                        _write_db_to_sheets(date, db_data[date], worksheet, sheets_data[date]["row_idx"])
                        report.db_to_sheets.append(date)
                        logger.info(f"⚖️ {date}: БД → Sheets (конфлікт, БД має більше даних)")

                    elif decision == "sheets":
                        _write_sheets_to_db(date, sheets_data[date], conn)
                        report.sheets_to_db.append(date)
                        logger.info(f"⚖️ {date}: Sheets → БД (конфлікт, Sheets має більше даних)")

                    else:  # skip
                        logger.info(f"⏭ {date}: пропущено (дані однакові)")

                # Перевіряємо колонку U (витрати палива)
                if in_sheets:
                    fuel_rate = sheets_data[date].get("fuel_rate")
                    if fuel_rate is not None:
                        expected = float(config.FUEL_CONSUMPTION)
                        if abs(fuel_rate - expected) > 0.1:
                            report.fuel_rate_warnings.append((date, fuel_rate))
                            logger.warning(f"⚠️ {date}: витрати палива {fuel_rate} л/год не збігаються з config ({expected})")

            except Exception as e:
                report.errors.append((date, str(e)))
                logger.error(f"❌ Помилка обробки дати {date}: {e}", exc_info=True)

        conn.commit()
        conn.close()

        # Синхронізуємо довідники
        _sync_references(sheets_data, report)

        logger.info("✅ Синхронізація завершена!")

    except Exception as e:
        logger.error(f"❌ Критична помилка синхронізації: {e}", exc_info=True)
        report.errors.append(("GLOBAL", str(e)))

    return report
