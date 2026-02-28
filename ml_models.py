"""ML-моделі для аналітики та прогнозування генератора.

Модулі:
  • FuelForecast  — прогноз витрати палива на 7 днів (лінійна регресія)
  • AnomalyDetector — виявлення аномалій у витраті (Isolation Forest)
"""

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

# Поріг витрати палива для ідентифікації аномалій (л/год)
_HIGH_FUEL_RATE_THRESHOLD = 8.0

# ---------------------------------------------------------------------------
# Спроба імпорту sklearn/numpy — graceful fallback якщо недоступні
# ---------------------------------------------------------------------------
try:
    import numpy as np
    from sklearn.linear_model import LinearRegression
    from sklearn.ensemble import IsolationForest
    from sklearn.preprocessing import StandardScaler
    ML_AVAILABLE = True
except ImportError:  # pragma: no cover
    ML_AVAILABLE = False
    np = None  # type: ignore
    LinearRegression = None  # type: ignore
    IsolationForest = None  # type: ignore
    StandardScaler = None  # type: ignore


# ---------------------------------------------------------------------------
# Допоміжні функції
# ---------------------------------------------------------------------------

def _day_features(dt: datetime) -> list:
    """Повертає ознаки для дня: [день_тижня, місяць, день_місяця]."""
    return [dt.weekday(), dt.month, dt.day]


# ---------------------------------------------------------------------------
# Модель 1: Прогноз витрати палива
# ---------------------------------------------------------------------------

class FuelForecast:
    """Прогноз витрати палива на 7 днів.

    Алгоритм: лінійна регресія з ознаками
      - день тижня (0-6)
      - місяць (1-12)
      - день місяця (1-31)
      - кількість відключень у день
    """

    def __init__(self):
        self._model: "LinearRegression | None" = None
        self._fitted = False

    def train(self, daily_stats: List[Dict[str, Any]]) -> bool:
        """Тренує модель на основі щоденної статистики.

        Args:
            daily_stats: список dict з ключами:
                - date: str "YYYY-MM-DD"
                - fuel_consumed: float (літрів за день)
                - outage_hours: int (кількість годин без світла)

        Returns:
            True якщо тренування успішне, False інакше
        """
        if not ML_AVAILABLE:
            logger.warning("scikit-learn недоступний — прогноз відключено")
            return False

        if len(daily_stats) < 7:
            logger.info("Недостатньо даних для тренування (потрібно ≥7 днів)")
            return False

        try:
            X, y = [], []
            for row in daily_stats:
                dt = datetime.strptime(row["date"], "%Y-%m-%d")
                outage = float(row.get("outage_hours", 0))
                features = _day_features(dt) + [outage]
                X.append(features)
                y.append(float(row["fuel_consumed"]))

            self._model = LinearRegression()
            self._model.fit(np.array(X), np.array(y))
            self._fitted = True
            logger.info(f"FuelForecast: модель навчена на {len(X)} днях")
            return True
        except Exception as e:
            logger.error(f"FuelForecast.train error: {e}", exc_info=True)
            return False

    def predict(self, days: int = 7, base_outage_hours: float = 4.0) -> List[Dict[str, Any]]:
        """Прогноз витрати палива на наступні N днів.

        Args:
            days: кількість днів прогнозу
            base_outage_hours: середній очікуваний час відключень

        Returns:
            список dict: {date, predicted_fuel, confidence}
        """
        if not ML_AVAILABLE or not self._fitted or self._model is None:
            return self._fallback_predict(days, base_outage_hours)

        try:
            results = []
            today = datetime.now().date()
            for i in range(1, days + 1):
                future_dt = datetime.combine(today + timedelta(days=i), datetime.min.time())
                features = _day_features(future_dt) + [base_outage_hours]
                pred = float(self._model.predict(np.array([features]))[0])
                pred = max(0.0, pred)  # не може бути від'ємним

                results.append({
                    "date": (today + timedelta(days=i)).strftime("%Y-%m-%d"),
                    "predicted_fuel": round(pred, 1),
                    "confidence": 0.75,  # фіксований confidence для linear regression
                })
            return results
        except Exception as e:
            logger.error(f"FuelForecast.predict error: {e}", exc_info=True)
            return self._fallback_predict(days, base_outage_hours)

    def _fallback_predict(self, days: int, avg_daily: float = 40.0) -> List[Dict[str, Any]]:
        """Простий fallback без ML — повертає середнє значення."""
        today = datetime.now().date()
        return [
            {
                "date": (today + timedelta(days=i)).strftime("%Y-%m-%d"),
                "predicted_fuel": round(avg_daily, 1),
                "confidence": 0.5,
            }
            for i in range(1, days + 1)
        ]


# ---------------------------------------------------------------------------
# Модель 2: Виявлення аномалій
# ---------------------------------------------------------------------------

class AnomalyDetector:
    """Виявлення аномалій у витраті палива.

    Алгоритм: Isolation Forest
    Що аналізуємо:
      - Різке збільшення витрати
      - Нетипові години роботи
    """

    def __init__(self, contamination: float = 0.1):
        self._model: "IsolationForest | None" = None
        self._scaler: "StandardScaler | None" = None
        self._fitted = False
        self._contamination = contamination

    def train(self, daily_stats: List[Dict[str, Any]]) -> bool:
        """Тренує детектор аномалій.

        Args:
            daily_stats: список dict з ключами:
                - fuel_consumed: float
                - work_hours: float
                - fuel_rate: float (л/год)
        """
        if not ML_AVAILABLE:
            return False

        if len(daily_stats) < 10:
            logger.info("AnomalyDetector: недостатньо даних (потрібно ≥10 днів)")
            return False

        try:
            X = []
            for row in daily_stats:
                X.append([
                    float(row.get("fuel_consumed", 0)),
                    float(row.get("work_hours", 0)),
                    float(row.get("fuel_rate", 0)),
                ])

            self._scaler = StandardScaler()
            X_scaled = self._scaler.fit_transform(np.array(X))

            self._model = IsolationForest(
                contamination=self._contamination,
                random_state=42,
                n_estimators=100,
            )
            self._model.fit(X_scaled)
            self._fitted = True
            logger.info(f"AnomalyDetector: модель навчена на {len(X)} днях")
            return True
        except Exception as e:
            logger.error(f"AnomalyDetector.train error: {e}", exc_info=True)
            return False

    def detect(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """Перевіряє запис на аномальність.

        Args:
            record: dict з ключами fuel_consumed, work_hours, fuel_rate

        Returns:
            dict: {is_anomaly: bool, score: float, reason: str}
        """
        if not ML_AVAILABLE or not self._fitted or self._model is None or self._scaler is None:
            return {"is_anomaly": False, "score": 0.0, "reason": ""}

        try:
            X = np.array([[
                float(record.get("fuel_consumed", 0)),
                float(record.get("work_hours", 0)),
                float(record.get("fuel_rate", 0)),
            ]])
            X_scaled = self._scaler.transform(X)
            prediction = self._model.predict(X_scaled)[0]
            score = float(self._model.score_samples(X_scaled)[0])

            is_anomaly = prediction == -1
            reason = ""
            if is_anomaly:
                fuel_rate = record.get("fuel_rate", 0)
                if fuel_rate and float(fuel_rate) > _HIGH_FUEL_RATE_THRESHOLD:
                    reason = "Підвищена витрата палива"
                elif record.get("work_hours", 0) and float(record.get("work_hours", 0)) > 18:
                    reason = "Нетипово довга робота"
                else:
                    reason = "Відхилення від норми"

            return {"is_anomaly": is_anomaly, "score": round(score, 3), "reason": reason}
        except Exception as e:
            logger.error(f"AnomalyDetector.detect error: {e}", exc_info=True)
            return {"is_anomaly": False, "score": 0.0, "reason": ""}


# ---------------------------------------------------------------------------
# Глобальні екземпляри (singleton)
# ---------------------------------------------------------------------------

_fuel_forecast = FuelForecast()
_anomaly_detector = AnomalyDetector()


def get_fuel_forecast() -> FuelForecast:
    """Повертає глобальний екземпляр FuelForecast."""
    return _fuel_forecast


def get_anomaly_detector() -> AnomalyDetector:
    """Повертає глобальний екземпляр AnomalyDetector."""
    return _anomaly_detector


def train_models_from_logs(daily_stats: List[Dict[str, Any]]) -> Dict[str, bool]:
    """Тренує всі моделі з підготовлених денних даних.

    Args:
        daily_stats: список dict з ключами:
            - date, fuel_consumed, work_hours, fuel_rate, outage_hours

    Returns:
        dict: {forecast: bool, anomaly: bool}
    """
    ok_forecast = _fuel_forecast.train(daily_stats)
    ok_anomaly = _anomaly_detector.train(daily_stats)
    return {"forecast": ok_forecast, "anomaly": ok_anomaly}
