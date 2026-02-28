"""Dynamic configuration management for generator parameters.

Provides CRUD operations for:
- generator_config: per-generator parameters (e.g. fuel_consumption_rate)
- global_config: system-wide parameters (e.g. fuel_price)
- config_history: audit trail of all config changes

Values fall back to .env / config module defaults when not present in DB.
"""

import logging
from datetime import datetime

import config as _config
import database.models as db_models

logger = logging.getLogger(__name__)

# --- Validation ranges ---
FUEL_CONSUMPTION_MIN = 3.0
FUEL_CONSUMPTION_MAX = 15.0
FUEL_PRICE_MIN = 10.0
FUEL_PRICE_MAX = 200.0

VALID_GENERATOR_IDS = ("main", "emergency")
VALID_GENERATOR_PARAMS = ("fuel_consumption_rate",)
VALID_GLOBAL_PARAMS = ("fuel_price",)


# ---------------------------------------------------------------------------
# Initialisation helpers (called by init_db)
# ---------------------------------------------------------------------------

def _ensure_tables(conn) -> None:
    """Create config tables if they don't exist (called from init_db)."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS generator_config (
            id SERIAL PRIMARY KEY,
            generator_id TEXT NOT NULL,
            param_name TEXT NOT NULL,
            param_value REAL NOT NULL,
            updated_at TEXT NOT NULL,
            updated_by INTEGER,
            updated_by_name TEXT,
            UNIQUE(generator_id, param_name)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS global_config (
            id SERIAL PRIMARY KEY,
            param_name TEXT NOT NULL UNIQUE,
            param_value REAL NOT NULL,
            updated_at TEXT NOT NULL,
            updated_by INTEGER,
            updated_by_name TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS config_history (
            id SERIAL PRIMARY KEY,
            config_type TEXT NOT NULL,
            entity_id TEXT,
            param_name TEXT NOT NULL,
            old_value REAL,
            new_value REAL NOT NULL,
            changed_at TEXT NOT NULL,
            changed_by INTEGER,
            changed_by_name TEXT,
            comment TEXT
        )
    """)


def _seed_defaults(conn) -> None:
    """Populate config tables with .env defaults on first run (INSERT OR IGNORE)."""
    now = datetime.now(_config.KYIV).strftime("%Y-%m-%d %H:%M:%S")
    main_rate = float(getattr(_config, "FUEL_CONSUMPTION", 5.3))
    emerg_rate = float(getattr(_config, "EMERGENCY_FUEL_CONSUMPTION", main_rate))
    fuel_price = float(getattr(_config, "FUEL_PRICE", 50.0))

    # PostgreSQL: ON CONFLICT DO NOTHING instead of INSERT OR IGNORE
    conn.execute(
        """INSERT INTO generator_config
           (generator_id, param_name, param_value, updated_at)
           VALUES ('main', 'fuel_consumption_rate', %s, %s)
           ON CONFLICT (generator_id, param_name) DO NOTHING""",
        (main_rate, now),
    )
    conn.execute(
        """INSERT INTO generator_config
           (generator_id, param_name, param_value, updated_at)
           VALUES ('emergency', 'fuel_consumption_rate', %s, %s)
           ON CONFLICT (generator_id, param_name) DO NOTHING""",
        (emerg_rate, now),
    )
    conn.execute(
        """INSERT INTO global_config
           (param_name, param_value, updated_at)
           VALUES ('fuel_price', %s, %s)
           ON CONFLICT (param_name) DO NOTHING""",
        (fuel_price, now),
    )


# ---------------------------------------------------------------------------
# generator_config
# ---------------------------------------------------------------------------

def get_generator_param(generator_id: str, param_name: str) -> float | None:
    """Return the stored value for a generator parameter, or None if not found."""
    try:
        conn = db_models.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT param_value FROM generator_config "
                "WHERE generator_id = %s AND param_name = %s",
                (generator_id, param_name),
            )
            row = cursor.fetchone()
            return float(row[0]) if row else None
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"get_generator_param error: {e}")
        return None


def get_generator_config(generator_id: str) -> dict:
    """Return all params for a generator as {param_name: {value, updated_at, updated_by_name}}."""
    try:
        conn = db_models.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT param_name, param_value, updated_at, updated_by_name "
                "FROM generator_config WHERE generator_id = %s",
                (generator_id,),
            )
            rows = cursor.fetchall()
            return {
                r[0]: {
                    "value": float(r[1]),
                    "last_updated": r[2] or "",
                    "updated_by": r[3] or "",
                }
                for r in rows
            }
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"get_generator_config error: {e}")
        return {}


def set_generator_param(
    generator_id: str,
    param_name: str,
    value: float,
    updated_by: int = 0,
    updated_by_name: str = "",
) -> bool:
    """Upsert a generator parameter and record it in config_history.

    Returns True on success, False on failure.
    """
    if generator_id not in VALID_GENERATOR_IDS:
        raise ValueError(f"Invalid generator_id: {generator_id!r}")
    if param_name not in VALID_GENERATOR_PARAMS:
        raise ValueError(f"Invalid param_name: {param_name!r}")

    _validate_generator_param(param_name, value)

    now = datetime.now(_config.KYIV).strftime("%Y-%m-%d %H:%M:%S")
    try:
        conn = db_models.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT param_value FROM generator_config "
                "WHERE generator_id = %s AND param_name = %s",
                (generator_id, param_name),
            )
            row = cursor.fetchone()
            old_value = float(row[0]) if row else None

            cursor.execute(
                """INSERT INTO generator_config
                   (generator_id, param_name, param_value, updated_at, updated_by, updated_by_name)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON CONFLICT(generator_id, param_name)
                   DO UPDATE SET
                       param_value = EXCLUDED.param_value,
                       updated_at = EXCLUDED.updated_at,
                       updated_by = EXCLUDED.updated_by,
                       updated_by_name = EXCLUDED.updated_by_name""",
                (generator_id, param_name, value, now, updated_by or None, updated_by_name or None),
            )
            cursor.execute(
                """INSERT INTO config_history
                   (config_type, entity_id, param_name, old_value, new_value,
                    changed_at, changed_by, changed_by_name)
                   VALUES ('generator', %s, %s, %s, %s, %s, %s, %s)""",
                (generator_id, param_name, old_value, value, now,
                 updated_by or None, updated_by_name or None),
            )
            conn.commit()
            return True
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"set_generator_param error: {e}")
        return False


# ---------------------------------------------------------------------------
# global_config
# ---------------------------------------------------------------------------

def get_global_param(param_name: str) -> float | None:
    """Return the stored value for a global parameter, or None if not found."""
    try:
        conn = db_models.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT param_value FROM global_config WHERE param_name = %s",
                (param_name,),
            )
            row = cursor.fetchone()
            return float(row[0]) if row else None
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"get_global_param error: {e}")
        return None


def get_global_config() -> dict:
    """Return all global params as {param_name: {value, updated_at, updated_by_name}}."""
    try:
        conn = db_models.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT param_name, param_value, updated_at, updated_by_name FROM global_config"
            )
            rows = cursor.fetchall()
            return {
                r[0]: {
                    "value": float(r[1]),
                    "last_updated": r[2] or "",
                    "updated_by": r[3] or "",
                }
                for r in rows
            }
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"get_global_config error: {e}")
        return {}


def set_global_param(
    param_name: str,
    value: float,
    updated_by: int = 0,
    updated_by_name: str = "",
) -> bool:
    """Upsert a global parameter and record it in config_history.

    Returns True on success, False on failure.
    """
    if param_name not in VALID_GLOBAL_PARAMS:
        raise ValueError(f"Invalid param_name: {param_name!r}")

    _validate_global_param(param_name, value)

    now = datetime.now(_config.KYIV).strftime("%Y-%m-%d %H:%M:%S")
    try:
        conn = db_models.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT param_value FROM global_config WHERE param_name = %s",
                (param_name,),
            )
            row = cursor.fetchone()
            old_value = float(row[0]) if row else None

            cursor.execute(
                """INSERT INTO global_config
                   (param_name, param_value, updated_at, updated_by, updated_by_name)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT(param_name)
                   DO UPDATE SET
                       param_value = EXCLUDED.param_value,
                       updated_at = EXCLUDED.updated_at,
                       updated_by = EXCLUDED.updated_by,
                       updated_by_name = EXCLUDED.updated_by_name""",
                (param_name, value, now, updated_by or None, updated_by_name or None),
            )
            cursor.execute(
                """INSERT INTO config_history
                   (config_type, entity_id, param_name, old_value, new_value,
                    changed_at, changed_by, changed_by_name)
                   VALUES ('global', NULL, %s, %s, %s, %s, %s, %s)""",
                (param_name, old_value, value, now,
                 updated_by or None, updated_by_name or None),
            )
            conn.commit()
            return True
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"set_global_param error: {e}")
        return False


# ---------------------------------------------------------------------------
# config_history
# ---------------------------------------------------------------------------

def get_config_history(limit: int = 20, offset: int = 0) -> list[dict]:
    """Return recent config changes as a list of dicts."""
    try:
        conn = db_models.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT config_type, entity_id, param_name,
                          old_value, new_value, changed_at,
                          changed_by, changed_by_name, comment
                   FROM config_history
                   ORDER BY changed_at DESC
                   LIMIT %s OFFSET %s""",
                (limit, offset),
            )
            rows = cursor.fetchall()
            return [
                {
                    "config_type": r[0],
                    "entity_id": r[1],
                    "param_name": r[2],
                    "old_value": float(r[3]) if r[3] is not None else None,
                    "new_value": float(r[4]),
                    "changed_at": r[5] or "",
                    "changed_by": r[6],
                    "changed_by_name": r[7] or "",
                    "comment": r[8] or "",
                }
                for r in rows
            ]
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"get_config_history error: {e}")
        return []


# ---------------------------------------------------------------------------
# Dynamic getters (with .env fallback)
# ---------------------------------------------------------------------------

def get_fuel_consumption_rate_db(generator_id: str = "main") -> float:
    """Get fuel consumption rate from DB, fallback to .env value."""
    value = get_generator_param(generator_id, "fuel_consumption_rate")
    if value is not None:
        return value
    if generator_id == "emergency":
        return float(getattr(_config, "EMERGENCY_FUEL_CONSUMPTION",
                             getattr(_config, "FUEL_CONSUMPTION", 5.3)))
    return float(getattr(_config, "FUEL_CONSUMPTION", 5.3))


def get_fuel_price_db() -> float:
    """Get fuel price from DB, fallback to config.FUEL_PRICE or 50.0."""
    value = get_global_param("fuel_price")
    if value is not None:
        return value
    return float(getattr(_config, "FUEL_PRICE", 50.0))


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _validate_generator_param(param_name: str, value: float) -> None:
    if param_name == "fuel_consumption_rate":
        if not (FUEL_CONSUMPTION_MIN <= value <= FUEL_CONSUMPTION_MAX):
            raise ValueError(
                f"fuel_consumption_rate must be between {FUEL_CONSUMPTION_MIN} "
                f"and {FUEL_CONSUMPTION_MAX}, got {value}"
            )


def _validate_global_param(param_name: str, value: float) -> None:
    if param_name == "fuel_price":
        if not (FUEL_PRICE_MIN <= value <= FUEL_PRICE_MAX):
            raise ValueError(
                f"fuel_price must be between {FUEL_PRICE_MIN} "
                f"and {FUEL_PRICE_MAX}, got {value}"
            )
