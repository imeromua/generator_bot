import logging
import sqlite3
from urllib.parse import urlparse, urlunparse

import config

try:
    import psycopg
    from psycopg import sql
    from psycopg import errors as pg_errors
except Exception:  # pragma: no cover
    psycopg = None
    sql = None
    pg_errors = None


def _is_postgres() -> bool:
    return (getattr(config, "DB_BACKEND", "sqlite") or "sqlite").strip().lower() == "postgres"


def _translate_qmarks(query: str) -> str:
    """Translate sqlite-style placeholders ('?') to psycopg placeholders ('%s')."""
    if not _is_postgres():
        return query
    # Simple translation is enough for our codebase (we don't embed '?' in SQL literals)
    return query.replace("?", "%s")


class CursorProxy:
    def __init__(self, cur):
        self._cur = cur

    def execute(self, query, params=None):
        q = _translate_qmarks(str(query))
        if params is None:
            return self._cur.execute(q)
        return self._cur.execute(q, params)

    def executemany(self, query, params_seq):
        q = _translate_qmarks(str(query))
        return self._cur.executemany(q, params_seq)

    def __getattr__(self, item):
        return getattr(self._cur, item)


class ConnectionProxy:
    """Small adapter around psycopg connection to support sqlite-style SQL."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, query, params=None):
        q = _translate_qmarks(str(query))
        if params is None:
            return self._conn.execute(q)
        return self._conn.execute(q, params)

    def cursor(self, *args, **kwargs):
        return CursorProxy(self._conn.cursor(*args, **kwargs))

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def close(self):
        return self._conn.close()

    def __enter__(self):
        self._conn.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        return self._conn.__exit__(exc_type, exc, tb)

    def __getattr__(self, item):
        return getattr(self._conn, item)


def _parse_dbname_from_dsn(dsn: str) -> str:
    u = urlparse(dsn)
    path = (u.path or "").lstrip("/")
    return (path or "").strip()


def _build_admin_dsn_from_app_dsn(app_dsn: str) -> str:
    u = urlparse(app_dsn)
    # switch database to 'postgres'
    new_u = u._replace(path="/postgres")
    return urlunparse(new_u)


def _postgres_db_missing(exc: Exception) -> bool:
    # Prefer structured errors if available
    try:
        if pg_errors and isinstance(exc, pg_errors.InvalidCatalogName):
            return True
    except Exception:
        pass

    msg = str(exc).lower()
    return ("does not exist" in msg) and ("database" in msg)


def ensure_postgres_database_exists():
    """Ensure target Postgres database exists; create it if missing."""
    if not _is_postgres():
        return

    if psycopg is None:
        raise RuntimeError("psycopg is not installed but DB_BACKEND=postgres")

    dsn = (getattr(config, "POSTGRES_DSN", "") or "").strip()
    if not dsn:
        raise RuntimeError("POSTGRES_DSN is not set")

    # Fast path: DB exists
    try:
        with psycopg.connect(dsn):
            return
    except Exception as e:
        if not _postgres_db_missing(e):
            raise

    dbname = _parse_dbname_from_dsn(dsn)
    if not dbname:
        raise RuntimeError("Cannot parse dbname from POSTGRES_DSN")

    admin_dsn = (getattr(config, "POSTGRES_ADMIN_DSN", "") or "").strip() or _build_admin_dsn_from_app_dsn(dsn)

    try:
        conn = psycopg.connect(admin_dsn)
        conn.autocommit = True
        try:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname)))
            logging.info(f"✅ Postgres DB created: {dbname}")
        except Exception as ce:
            try:
                if pg_errors and isinstance(ce, pg_errors.DuplicateDatabase):
                    pass
                else:
                    # race condition or different server message, ignore if DB already exists
                    if "already exists" not in str(ce).lower():
                        raise
            except Exception:
                raise
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception as e:
        raise RuntimeError(
            f"Failed to create Postgres database '{dbname}'. "
            f"Check POSTGRES_ADMIN_DSN / permissions. Error: {e}"
        )


def get_connection():
    """Returns a DB connection.

    - sqlite: sqlite3.Connection
    - postgres: ConnectionProxy (psycopg connection wrapper)
    """
    if not _is_postgres():
        db_path = (getattr(config, "SQLITE_PATH", "generator.db") or "generator.db").strip()
        return sqlite3.connect(db_path, check_same_thread=False, timeout=10)

    ensure_postgres_database_exists()
    conn = psycopg.connect(getattr(config, "POSTGRES_DSN"))
    return ConnectionProxy(conn)


def begin_transaction(conn):
    """Start a transaction in a backend-appropriate way."""
    if _is_postgres():
        # psycopg starts a transaction implicitly, but explicit BEGIN is OK.
        try:
            conn.execute("BEGIN")
        except Exception:
            pass
    else:
        conn.execute("BEGIN IMMEDIATE")


def init_db():
    """Create schema (idempotent) + seed generator_state defaults."""
    conn = get_connection()
    c = conn.cursor()

    if not _is_postgres():
        c.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, full_name TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS drivers (id INTEGER PRIMARY KEY, name TEXT UNIQUE)''')
        c.execute('''CREATE TABLE IF NOT EXISTS logs (id INTEGER PRIMARY KEY, event_type TEXT, timestamp TEXT, user_name TEXT, value TEXT, driver_name TEXT, is_synced INTEGER DEFAULT 0)''')
        c.execute('''CREATE TABLE IF NOT EXISTS generator_state (key TEXT PRIMARY KEY, value TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS schedule (date TEXT, hour INTEGER, is_off INTEGER, PRIMARY KEY(date, hour))''')
        c.execute('''CREATE TABLE IF NOT EXISTS maintenance (id INTEGER PRIMARY KEY, date TEXT, type TEXT, hours REAL, admin TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS user_personnel (user_id INTEGER PRIMARY KEY, personnel_name TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS personnel_names (name TEXT PRIMARY KEY)''')
        c.execute('''CREATE TABLE IF NOT EXISTS user_ui (user_id INTEGER PRIMARY KEY, chat_id INTEGER, message_id INTEGER)''')

    else:
        c.execute('''CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY, full_name TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS drivers (id BIGSERIAL PRIMARY KEY, name TEXT UNIQUE)''')
        c.execute('''CREATE TABLE IF NOT EXISTS logs (id BIGSERIAL PRIMARY KEY, event_type TEXT, timestamp TEXT, user_name TEXT, value TEXT, driver_name TEXT, is_synced INTEGER DEFAULT 0)''')
        c.execute('''CREATE TABLE IF NOT EXISTS generator_state (key TEXT PRIMARY KEY, value TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS schedule (date TEXT, hour INTEGER, is_off INTEGER, PRIMARY KEY(date, hour))''')
        c.execute('''CREATE TABLE IF NOT EXISTS maintenance (id BIGSERIAL PRIMARY KEY, date TEXT, type TEXT, hours DOUBLE PRECISION, admin TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS user_personnel (user_id BIGINT PRIMARY KEY, personnel_name TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS personnel_names (name TEXT PRIMARY KEY)''')
        c.execute('''CREATE TABLE IF NOT EXISTS user_ui (user_id BIGINT PRIMARY KEY, chat_id BIGINT, message_id BIGINT)''')

    defaults = [
        ('total_hours', '0.0'),
        ('last_oil_change', '0.0'),
        ('last_spark_change', '0.0'),
        ('status', 'OFF'),
        ('active_shift', 'none'),
        ('last_start_time', ''),
        ('last_start_date', ''),
        ('current_fuel', '0.0'),
        ('fuel_ordered_date', ''),
        ('fuel_alert_last_sent_ts', ''),
        ('stop_reminder_sent_date', ''),
        ('sheet_last_ok_ts', ''),
        ('sheet_first_fail_ts', ''),
        ('sheet_offline', '0'),
        ('sheet_offline_since_ts', ''),
    ]

    # Seed defaults: keep existing values if already present
    for k, v in defaults:
        try:
            c.execute(
                """
                INSERT INTO generator_state (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO NOTHING
                """,
                (k, v),
            )
        except Exception:
            # fallback for older sqlite
            try:
                c.execute("INSERT OR IGNORE INTO generator_state (key, value) VALUES (?, ?)", (k, v))
            except Exception:
                pass

    try:
        conn.commit()
    except Exception:
        pass
    try:
        conn.close()
    except Exception:
        pass

    logging.info("✅ База даних ініціалізована.")
