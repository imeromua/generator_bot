"""Analytics business logic services."""
import math
import logging
from datetime import datetime, timedelta
import database.db_api as db
from database.api.logs import get_logs_for_period
from database.api.schedule import get_schedule

logger = logging.getLogger(__name__)


def _safe_round(v: float, ndigits: int = 1) -> float:
    """Round a float, replacing non-finite values with 0.0."""
    try:
        f = float(v)
        return round(f, ndigits) if math.isfinite(f) else 0.0
    except (TypeError, ValueError):
        return 0.0


def _build_daily_stats(start_dt: datetime, end_dt: datetime, generator_id: str | None = None) -> list:
    """Збирає денну статистику з логів за вказаний діапазон дат.

    Повертає список dict:
      {date, work_hours, fuel_consumed, fuel_rate, outage_hours, refill_liters,
       morning_balance, evening_balance}
    """
    start_str = start_dt.strftime("%Y-%m-%d")
    end_str = end_dt.strftime("%Y-%m-%d")

    logs = get_logs_for_period(start_str, end_str, generator_id)

    # Групуємо start/stop пари по датах
    daily: dict = {}
    current_day = start_dt.date()
    while current_day <= end_dt.date():
        daily[current_day.strftime("%Y-%m-%d")] = {
            "date": current_day.strftime("%Y-%m-%d"),
            "work_hours": 0.0,
            "fuel_consumed": 0.0,
            "fuel_rate": 0.0,
            "outage_hours": 0,
            "refill_liters": 0.0,
            "morning_balance": None,
            "evening_balance": None,
        }
        current_day += timedelta(days=1)

    # Відстежуємо старт/стоп по генератору
    pending_start: dict = {}  # gen_id -> datetime

    for row in logs:
        event_type, ts_str, user_name, value, driver_name, receipt_number, gen_id = row
        try:
            ts = datetime.strptime(ts_str[:19], "%Y-%m-%d %H:%M:%S")
        except Exception:
            continue
        day_key = ts.strftime("%Y-%m-%d")
        if day_key not in daily:
            continue

        if event_type in ("m_start", "d_start", "e_start", "x_start"):
            pending_start[gen_id or "main"] = ts

        elif event_type in ("m_end", "d_end", "e_end", "x_end"):
            gen_key = gen_id or "main"
            start_ts = pending_start.pop(gen_key, None)
            if start_ts:
                hours = (ts - start_ts).total_seconds() / 3600.0
                if 0 < hours < 24:
                    fuel_rate = float(db.get_fuel_consumption_rate() or 5.0)
                    daily[day_key]["work_hours"] += hours
                    daily[day_key]["fuel_consumed"] += hours * fuel_rate
                    daily[day_key]["fuel_rate"] = fuel_rate

        elif event_type == "refill":
            try:
                liters = float(value or 0)
                daily[day_key]["refill_liters"] += liters
            except Exception:
                pass

    # Відключення — з таблиці schedule
    for day_key in daily:
        try:
            sched = get_schedule(day_key)
            daily[day_key]["outage_hours"] = sum(1 for v in sched.values() if v == 1)
        except Exception:
            pass

    # Округлення
    for d in daily.values():
        d["fuel_consumed"] = round(d["fuel_consumed"], 2)
        d["work_hours"] = round(d["work_hours"], 2)
        if d["work_hours"] > 0:
            d["fuel_rate"] = round(d["fuel_consumed"] / d["work_hours"], 3)

    # Розрахунок залишків палива (ранок/вечір)
    sorted_days = sorted(daily.values(), key=lambda x: x["date"])
    try:
        current_fuel = float(db.get_state().get("current_fuel", 0) or 0)
    except Exception:
        current_fuel = 0.0
    total_period_refills = sum(d["refill_liters"] for d in sorted_days)
    total_period_consumption = sum(d["fuel_consumed"] for d in sorted_days)
    starting_fuel = current_fuel - total_period_refills + total_period_consumption
    prev_balance = starting_fuel if starting_fuel > 0 else None
    for d in sorted_days:
        morning_balance = prev_balance
        if morning_balance is not None:
            evening_balance = round(
                float(morning_balance) + d["refill_liters"] - d["fuel_consumed"], 1
            )
        else:
            evening_balance = None
        d["morning_balance"] = morning_balance
        d["evening_balance"] = evening_balance
        prev_balance = evening_balance if isinstance(evening_balance, float) else None

    return sorted_days
