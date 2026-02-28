"""Analytics API endpoints."""
import logging
import math
from datetime import datetime, timedelta
from fastapi import Request
from fastapi.responses import JSONResponse
import config
import database.db_api as db
from webapp.utils import validation as _validation_mod
from webapp.services.analytics_service import _safe_round, _build_daily_stats

logger = logging.getLogger(__name__)

_DEFAULT_AVG_DAILY_HOURS = 2.0
_MIN_REALISTIC_AVG_DAILY_HOURS = 0.5


async def api_analytics_kpi(request: Request):
    """GET /api/analytics/kpi — KPI картки для дашборду аналітики."""
    user = _validation_mod.extract_user(request)
    if not user:
        return JSONResponse(content={"error": "Не авторизовано"}, status_code=401)
    try:
        days = int(request.query_params.get("days", "30"))
        days = max(1, min(days, 365))
        gen_id = request.query_params.get("generator") or None

        from utils.time import now_kiev

        now = now_kiev()
        start_dt = now - timedelta(days=days - 1)

        daily = _build_daily_stats(start_dt, now, gen_id)

        total_hours = sum(d["work_hours"] for d in daily)
        total_fuel = sum(d["fuel_consumed"] for d in daily)
        avg_per_day = total_hours / len(daily) if daily else 0
        avg_rate = total_fuel / total_hours if total_hours > 0 else 0
        fuel_price = db.get_fuel_price_db()
        fuel_cost = total_fuel * fuel_price
        total_outage = sum(d["outage_hours"] for d in daily)
        total_avail = days * 24
        efficiency = round((total_outage / total_avail) * 100, 1) if total_avail > 0 else 0

        # Порівняння з попереднім таким же періодом
        prev_start = start_dt - timedelta(days=days)
        prev_end = start_dt - timedelta(days=1)
        prev_daily = _build_daily_stats(prev_start, prev_end, gen_id)
        prev_hours = sum(d["work_hours"] for d in prev_daily)
        prev_fuel = sum(d["fuel_consumed"] for d in prev_daily)

        def _percent_change(curr, prev):
            if prev == 0:
                return None
            return round((curr - prev) / prev * 100, 1)

        return {
            "period_days": days,
            "total_hours": round(total_hours, 1),
            "avg_hours_per_day": round(avg_per_day, 2),
            "avg_fuel_rate": round(avg_rate, 3),
            "total_fuel": round(total_fuel, 1),
            "fuel_cost": round(fuel_cost, 0),
            "efficiency_pct": efficiency,
            "total_outage_hours": total_outage,
            "prev_total_hours": round(prev_hours, 1),
            "prev_total_fuel": round(prev_fuel, 1),
            "hours_change_pct": _percent_change(total_hours, prev_hours),
            "fuel_change_pct": _percent_change(total_fuel, prev_fuel),
        }
    except Exception as e:
        logger.exception("api_analytics_kpi error")
        return JSONResponse(content={"error": str(e)}, status_code=500)


async def api_analytics_fuel_timeline(request: Request):
    """GET /api/analytics/fuel-timeline — дані для графіка витрати палива."""
    user = _validation_mod.extract_user(request)
    if not user:
        return JSONResponse(content={"error": "Не авторизовано"}, status_code=401)
    try:
        days = int(request.query_params.get("days", "30"))
        days = max(1, min(days, 365))
        gen_id = request.query_params.get("generator") or None

        from utils.time import now_kiev

        now = now_kiev()
        start_dt = now - timedelta(days=days - 1)

        daily = _build_daily_stats(start_dt, now, gen_id)

        # Прогноз (наступні 7 днів)
        from ml_models import get_fuel_forecast

        forecast_obj = get_fuel_forecast()
        forecast_obj.train(daily)
        avg_outage = sum(d["outage_hours"] for d in daily) / len(daily) if daily else 4.0
        forecast = forecast_obj.predict(7, avg_outage)

        return {
            "actual": [
                {
                    "date": d["date"],
                    "fuel_consumed": d["fuel_consumed"],
                    "work_hours": d["work_hours"],
                    "refill_liters": d["refill_liters"],
                    "outage_hours": d["outage_hours"],
                    "morning_balance": d.get("morning_balance"),
                    "evening_balance": d.get("evening_balance"),
                }
                for d in daily
            ],
            "forecast": forecast,
        }
    except Exception as e:
        logger.exception("api_analytics_fuel_timeline error")
        return JSONResponse(content={"error": str(e)}, status_code=500)


async def api_analytics_motor_hours(request: Request):
    """GET /api/analytics/motor-hours — мотогодини генераторів."""
    user = _validation_mod.extract_user(request)
    if not user:
        return JSONResponse(content={"error": "Не авторизовано"}, status_code=401)
    try:
        days = int(request.query_params.get("days", "30"))
        days = max(1, min(days, 365))

        from utils.time import now_kiev

        now = now_kiev()
        start_dt = now - timedelta(days=days - 1)

        main_daily = _build_daily_stats(start_dt, now, "main")
        emergency_daily = _build_daily_stats(start_dt, now, "emergency")

        # Об'єднуємо по датах
        date_map: dict = {}
        for d in main_daily:
            date_map[d["date"]] = {"date": d["date"], "main": d["work_hours"], "emergency": 0.0}
        for d in emergency_daily:
            if d["date"] in date_map:
                date_map[d["date"]]["emergency"] = d["work_hours"]
            else:
                date_map[d["date"]] = {"date": d["date"], "main": 0.0, "emergency": d["work_hours"]}

        combined = sorted(date_map.values(), key=lambda x: x["date"])

        from database.api.generator import get_generator_stats

        main_stats = get_generator_stats("main")
        emergency_stats = get_generator_stats("emergency")

        return {
            "daily": combined,
            "totals": {
                "main": {
                    "total_hours": main_stats.get("total_hours", 0),
                    "period_hours": round(sum(d["main"] for d in combined), 1),
                },
                "emergency": {
                    "total_hours": emergency_stats.get("total_hours", 0),
                    "period_hours": round(sum(d["emergency"] for d in combined), 1),
                },
            },
        }
    except Exception as e:
        logger.exception("api_analytics_motor_hours error")
        return JSONResponse(content={"error": str(e)}, status_code=500)


async def api_analytics_efficiency(request: Request):
    """GET /api/analytics/efficiency — ефективність роботи."""
    user = _validation_mod.extract_user(request)
    if not user:
        return JSONResponse(content={"error": "Не авторизовано"}, status_code=401)
    try:
        days = int(request.query_params.get("days", "30"))
        days = max(1, min(days, 365))

        from utils.time import now_kiev
        from database.api.maintenance import get_maintenance_stats

        now = now_kiev()
        start_dt = now - timedelta(days=days - 1)

        daily = _build_daily_stats(start_dt, now, None)

        total_hours_avail = days * 24
        work_hours = sum(d["work_hours"] for d in daily)
        outage_hours = float(sum(d["outage_hours"] for d in daily))
        maintenance_hours = 0.0
        # Guard against NaN/Inf from summing DB values
        if not math.isfinite(work_hours):
            work_hours = 0.0
        if not math.isfinite(outage_hours):
            outage_hours = 0.0
        idle_hours = max(0.0, total_hours_avail - outage_hours - maintenance_hours)

        # Розбивка по змінах
        shift_fuel: dict = {"m": 0.0, "d": 0.0, "e": 0.0, "x": 0.0}
        shift_hours: dict = {"m": 0.0, "d": 0.0, "e": 0.0, "x": 0.0}

        from database.api.logs import get_logs_for_period

        start_str = start_dt.strftime("%Y-%m-%d")
        end_str = now.strftime("%Y-%m-%d")
        logs = get_logs_for_period(start_str, end_str)

        pending: dict = {}
        for row in logs:
            event_type, ts_str, *_ = row
            try:
                ts = datetime.strptime(ts_str[:19], "%Y-%m-%d %H:%M:%S")
            except Exception:
                continue
            if event_type in ("m_start", "d_start", "e_start", "x_start"):
                shift_key = event_type[0]
                pending[shift_key] = ts
            elif event_type in ("m_end", "d_end", "e_end", "x_end"):
                shift_key = event_type[0]
                start_ts = pending.pop(shift_key, None)
                if start_ts:
                    h = (ts - start_ts).total_seconds() / 3600.0
                    if 0 < h < 24:
                        fuel_rate = float(db.get_fuel_consumption_rate() or 5.0)
                        shift_hours[shift_key] = shift_hours.get(shift_key, 0.0) + h
                        shift_fuel[shift_key] = shift_fuel.get(shift_key, 0.0) + h * fuel_rate

        return {
            "pie": {
                "work_hours": _safe_round(work_hours),
                "idle_hours": _safe_round(idle_hours),
                "outage_hours": _safe_round(outage_hours),
                "maintenance_hours": _safe_round(maintenance_hours),
            },
            "shifts": {
                shift: {
                    "hours": _safe_round(shift_hours.get(shift, 0.0)),
                    "fuel_consumed": _safe_round(shift_fuel.get(shift, 0.0)),
                }
                for shift in ("m", "d", "e", "x")
            },
        }
    except Exception as e:
        logger.exception("api_analytics_efficiency error")
        return JSONResponse(content={"error": str(e)}, status_code=500)


async def api_analytics_calendar(request: Request):
    """GET /api/analytics/calendar — календар відключень (місяць)."""
    user = _validation_mod.extract_user(request)
    if not user:
        return JSONResponse(content={"error": "Не авторизовано"}, status_code=401)
    try:
        from utils.time import now_kiev
        from database.api.schedule import get_schedule
        import calendar

        now = now_kiev()
        month_str = request.query_params.get("month") or now.strftime("%Y-%m")
        year, month = int(month_str[:4]), int(month_str[5:7])
        _, num_days = calendar.monthrange(year, month)

        result = []
        for day in range(1, num_days + 1):
            date_str = f"{year:04d}-{month:02d}-{day:02d}"
            sched = get_schedule(date_str)
            outage_h = sum(1 for v in sched.values() if v == 1)
            result.append({"date": date_str, "outage_hours": outage_h, "schedule": sched})

        return {"month": month_str, "days": result}
    except Exception as e:
        logger.exception("api_analytics_calendar error")
        return JSONResponse(content={"error": str(e)}, status_code=500)


async def api_analytics_trends(request: Request):
    """GET /api/analytics/trends — тренди та автоматичні інсайти."""
    user = _validation_mod.extract_user(request)
    if not user:
        return JSONResponse(content={"error": "Не авторизовано"}, status_code=401)
    try:
        days = int(request.query_params.get("days", "30"))
        days = max(7, min(days, 365))

        from utils.time import now_kiev

        now = now_kiev()
        start_dt = now - timedelta(days=days - 1)

        daily = _build_daily_stats(start_dt, now, None)

        insights = []

        # Тренд витрати палива
        if len(daily) >= 14:
            first_half = daily[: len(daily) // 2]
            second_half = daily[len(daily) // 2 :]
            avg1 = sum(d["fuel_consumed"] for d in first_half) / len(first_half)
            avg2 = sum(d["fuel_consumed"] for d in second_half) / len(second_half)
            if avg1 > 0:
                change = (avg2 - avg1) / avg1 * 100
                if abs(change) >= 5:
                    direction = "зросла" if change > 0 else "знизилась"
                    insights.append(
                        {
                            "type": "fuel_trend",
                            "icon": "📈" if change > 0 else "📉",
                            "text": f"Витрата {direction} на {abs(change):.0f}% за {days} днів",
                            "severity": "warning" if change > 15 else "info",
                        }
                    )

        # День тижня з найбільшою кількістю відключень
        weekday_outage: dict = {}
        weekday_names = ["Понеділок", "Вівторок", "Середа", "Четвер", "П'ятниця", "Субота", "Неділя"]
        for d in daily:
            dt = datetime.strptime(d["date"], "%Y-%m-%d")
            wd = dt.weekday()
            weekday_outage[wd] = weekday_outage.get(wd, [])
            weekday_outage[wd].append(d["outage_hours"])
        if weekday_outage:
            avg_by_day = {wd: sum(v) / len(v) for wd, v in weekday_outage.items()}
            worst_day = max(avg_by_day, key=avg_by_day.get)  # type: ignore[arg-type]
            if avg_by_day[worst_day] > 2:
                insights.append(
                    {
                        "type": "outage_weekday",
                        "icon": "📅",
                        "text": f"Найбільше відключень у {weekday_names[worst_day]} (сер. {avg_by_day[worst_day]:.1f} год)",
                        "severity": "info",
                    }
                )

        # Порівняння генераторів
        main_daily = _build_daily_stats(start_dt, now, "main")
        emergency_daily = _build_daily_stats(start_dt, now, "emergency")
        main_hours = sum(d["work_hours"] for d in main_daily)
        emerg_hours = sum(d["work_hours"] for d in emergency_daily)
        total_gen = main_hours + emerg_hours
        if total_gen > 0 and emerg_hours > 0:
            emerg_pct = emerg_hours / total_gen * 100
            if emerg_pct > 10:
                insights.append(
                    {
                        "type": "emergency_usage",
                        "icon": "⚠️",
                        "text": f"Аварійний генератор використовується {emerg_pct:.0f}% часу",
                        "severity": "warning" if emerg_pct > 30 else "info",
                    }
                )

        # Аномалії
        from ml_models import get_anomaly_detector

        anomaly_det = get_anomaly_detector()
        anomaly_det.train(daily)
        anomalies_found = []
        for d in daily[-7:]:  # перевіряємо останній тиждень
            res = anomaly_det.detect(d)
            if res["is_anomaly"]:
                anomalies_found.append(f"{d['date']}: {res['reason']}")
        if anomalies_found:
            insights.append(
                {
                    "type": "anomaly",
                    "icon": "🔴",
                    "text": f"Виявлено аномалії: {', '.join(anomalies_found[:3])}",
                    "severity": "critical",
                }
            )

        return {
            "period_days": days,
            "insights": insights,
        }
    except Exception as e:
        logger.exception("api_analytics_trends error")
        return JSONResponse(content={"error": str(e)}, status_code=500)


async def api_analytics_forecast(request: Request):
    """GET /api/analytics/forecast — ML-прогноз витрати палива."""
    user = _validation_mod.extract_user(request)
    if not user:
        return JSONResponse(content={"error": "Не авторизовано"}, status_code=401)
    try:
        from utils.time import now_kiev
        from database.api.generator import get_generator_stats

        now = now_kiev()
        # Тренуємо на останніх 60 днях
        start_dt = now - timedelta(days=60)
        daily = _build_daily_stats(start_dt, now, None)

        from ml_models import get_fuel_forecast

        forecast_obj = get_fuel_forecast()
        ok = forecast_obj.train(daily)

        avg_outage = sum(d["outage_hours"] for d in daily) / len(daily) if daily else 4.0
        forecast = forecast_obj.predict(7, avg_outage)

        total_forecast_fuel = sum(f["predicted_fuel"] for f in forecast)

        # ТО
        main_stats = get_generator_stats("main")
        oil_hours = main_stats.get("last_oil_change", 0)
        oil_interval = getattr(config, "OIL_CHANGE_INTERVAL", 250)
        spark_interval = getattr(config, "SPARK_CHANGE_INTERVAL", 500)
        oil_remaining = max(0, oil_interval - oil_hours)
        spark_remaining = max(0, spark_interval - main_stats.get("last_spark_change", 0))

        avg_daily_hours = sum(d["work_hours"] for d in daily[-7:]) / 7 if len(daily) >= 7 else _DEFAULT_AVG_DAILY_HOURS
        if avg_daily_hours < _MIN_REALISTIC_AVG_DAILY_HOURS:
            avg_daily_hours = _DEFAULT_AVG_DAILY_HOURS
        days_to_oil = round(oil_remaining / avg_daily_hours, 0) if avg_daily_hours > 0 else 0
        days_to_spark = round(spark_remaining / avg_daily_hours, 0) if avg_daily_hours > 0 else 0

        return {
            "model_trained": ok,
            "forecast_days": 7,
            "daily_forecast": forecast,
            "total_forecast_fuel": round(total_forecast_fuel, 1),
            "maintenance": {
                "oil_remaining_hours": round(oil_remaining, 1),
                "spark_remaining_hours": round(spark_remaining, 1),
                "days_to_oil_change": int(days_to_oil),
                "days_to_spark_change": int(days_to_spark),
            },
        }
    except Exception as e:
        logger.exception("api_analytics_forecast error")
        return JSONResponse(content={"error": str(e)}, status_code=500)
