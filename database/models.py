"""Database models and connection management with type hints.

Supports both SQLite and PostgreSQL backends with connection pooling.
"""

import logging
import re
import sqlite3
from typing import Any, Optional, Protocol, TypeVar, Union
from urllib.parse import ParseResult, urlparse, urlunparse

import config

try:
    import psycopg
    from psycopg import errors as pg_errors
    from psycopg import sql
    from psycopg_pool import ConnectionPool
except Exception:  # pragma: no cover
    psycopg = None  # type: ignore
    sql = None  # type: ignore
    pg_errors = None  # type: ignore
    ConnectionPool = None  # type: ignore


# Type definitions
CursorType = Union[sqlite3.Cursor, "psycopg.Cursor[Any]"]  # type: ignore
ConnectionType = Union[sqlite3.Connection, "psycopg.Connection[Any]"]  # type: ignore


def _is_postgres() -> bool:
    """Check if PostgreSQL backend is configured."""
    return (getattr(config, "DB_BACKEND", "sqlite") or "sqlite").strip().lower() == "postgres"


_QMARK_PATTERN = re.compile(r"\?")


def _translate_qmarks(query: str) -> str:
    """Translate sqlite-style placeholders ('?') to psycopg placeholders ('%s').

    For PostgreSQL backend replaces all '?' with '%s'. For SQLite returns
    query unchanged.

    Args:
        query: SQL query string with placeholders

    Returns:
        Translated query string
    """
    if not _is_postgres():
        return query
    return _QMARK_PATTERN.sub("%s", str(query))


def _safe_postgres_target(dsn: str) -> str:
    """Return safe (password-free) string like user@host:port/db.

    Args:
        dsn: PostgreSQL connection string

    Returns:
        Safe connection string without password
    """
    try:
        u: ParseResult = urlparse(dsn)
        user = u.username or "?"
        host = u.hostname or "localhost"
        port = u.port or 5432
        db = (u.path or "").lstrip("/") or "?"
        return f"{user}@{host}:{port}/{db}"
    except Exception:
        return "(invalid POSTGRES_DSN)"


def db_target_info() -> str:
    """Get human-readable database target info.

    Returns:
        String like 'sqlite:path' or 'postgres:user@host:port/db'
    """
    if not _is_postgres():
        db_path = (getattr(config, "SQLITE_PATH", "generator.db") or "generator.db").strip()
        return f"sqlite:{db_path}"
    return f"postgres:{_safe_postgres_target(getattr(config, 'POSTGRES_DSN', '') or '')}"


class CursorProxy:
    """Proxy for database cursors with query translation.

    Translates SQLite-style '?' placeholders to PostgreSQL '%s' style.
    """

    def __init__(self, cur: CursorType) -> None:
        self._cur = cur

    def execute(self, query: str, params: Optional[tuple[Any, ...] | list[Any]] = None) -> CursorType:
        q = _translate_qmarks(str(query))
        if params is None:
            return self._cur.execute(q)
        return self._cur.execute(q, params)

    def executemany(self, query: str, params_seq: list[tuple[Any, ...]] | list[list[Any]]) -> CursorType:
        q = _translate_qmarks(str(query))
        return self._cur.executemany(q, params_seq)

    def __getattr__(self, item: str) -> Any:
        return getattr(self._cur, item)


class ConnectionProxy:
    """Adapter around psycopg connection to support sqlite-style SQL.

    psycopg connections are transactional by default; to match sqlite-like
    behaviour, we enable autocommit when creating the pool.
    """

    def __init__(self, conn: ConnectionType) -> None:
        self._conn = conn

    def execute(self, query: str, params: Optional[tuple[Any, ...] | list[Any]] = None) -> CursorType:
        q = _translate_qmarks(str(query))
        if params is None:
            return self._conn.execute(q)
        return self._conn.execute(q, params)

    def cursor(self, *args: Any, **kwargs: Any) -> CursorProxy:
        return CursorProxy(self._conn.cursor(*args, **kwargs))

    def commit(self) -> None:
        return self._conn.commit()

    def rollback(self) -> None:
        return self._conn.rollback()

    def close(self) -> None:
        return self._conn.close()

    def __enter__(self) -> "ConnectionProxy":
        self._conn.__enter__()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return self._conn.__exit__(exc_type, exc, tb)

    def __getattr__(self, item: str) -> Any:
        return getattr(self._conn, item)


class PooledConnectionProxy(ConnectionProxy):
    """Connection proxy backed by psycopg_pool.ConnectionPool.

    Uses pool.connection() context manager under the hood and returns
    connections to the pool on close()/__exit__.
    """

    def __init__(self, pool: "ConnectionPool") -> None:  # type: ignore[name-defined]
        self._pool = pool
        self._ctx = pool.connection()
        self._closed = False

        conn = self._ctx.__enter__()
        # Best-effort: ensure autocommit (pool kwargs should already set it).
        try:
            conn.autocommit = True
        except Exception:
            pass

        super().__init__(conn)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._ctx.__exit__(None, None, None)
        except Exception:
            try:
                self._conn.close()
            except Exception:
                pass

    def __enter__(self) -> "PooledConnectionProxy":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        try:
            if self._closed:
                return False
            self._closed = True
            return bool(self._ctx.__exit__(exc_type, exc, tb))
        except Exception:
            try:
                self._conn.close()
            except Exception:
                pass
            return False


def _parse_dbname_from_dsn(dsn: str) -> str:
    u: ParseResult = urlparse(dsn)
    path = (u.path or "").lstrip("/")
    return (path or "").strip()


def _build_admin_dsn_from_app_dsn(app_dsn: str) -> str:
    u: ParseResult = urlparse(app_dsn)
    new_u = u._replace(path="/postgres")
    return urlunparse(new_u)


def _postgres_db_missing(exc: Exception) -> bool:
    try:
        if pg_errors and isinstance(exc, pg_errors.InvalidCatalogName):
            return True
    except Exception:
        pass

    msg = str(exc).lower()
    return ("does not exist" in msg) and ("database" in msg)


def ensure_postgres_database_exists() -> None:
    if not _is_postgres():
        return

    if psycopg is None:
        raise RuntimeError("psycopg is not installed but DB_BACKEND=postgres")

    dsn = (getattr(config, "POSTGRES_DSN", "") or "").strip()
    if not dsn:
        raise RuntimeError("POSTGRES_DSN is not set")

    try:
        with psycopg.connect(dsn, connect_timeout=10):
            return
    except Exception as e:
        if not _postgres_db_missing(e):
            raise

    dbname = _parse_dbname_from_dsn(dsn)
    if not dbname:
        raise RuntimeError("Cannot parse dbname from POSTGRES_DSN")

    admin_dsn = (getattr(config, "POSTGRES_ADMIN_DSN", "") or "").strip() or _build_admin_dsn_from_app_dsn(dsn)

    try:
        conn = psycopg.connect(admin_dsn, connect_timeout=10)
        conn.autocommit = True
        try:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname)))
            logging.info(f"✅ Postgres DB created: {dbname}")
        except Exception as ce:
            try:
                if pg_errors and isinstance(ce, pg_errors.DuplicateDatabase):
                    pass
                else:
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


# Global connection pool
_pg_pool: Optional["ConnectionPool"] = None  # type: ignore


def get_postgres_pool() -> Optional["ConnectionPool"]:  # type: ignore
    """Get or create global PostgreSQL connection pool."""
    global _pg_pool

    if _pg_pool is None:
        if not _is_postgres():
            return None

        if ConnectionPool is None:
            raise RuntimeError("psycopg_pool is not installed but DB_BACKEND=postgres")

        dsn = (getattr(config, "POSTGRES_DSN", "") or "").strip()
        if not dsn:
            raise RuntimeError("POSTGRES_DSN is not set")

        ensure_postgres_database_exists()

        min_size = getattr(config, "PG_POOL_MIN_SIZE", 2)
        max_size = getattr(config, "PG_POOL_MAX_SIZE", 10)
        timeout = getattr(config, "PG_POOL_TIMEOUT", 30)
        max_idle = getattr(config, "PG_POOL_MAX_IDLE", 300)

        try:
            _pg_pool = ConnectionPool(
                conninfo=dsn,
                min_size=min_size,
                max_size=max_size,
                timeout=timeout,
                max_idle=max_idle,
                kwargs={
                    "autocommit": True,
                    "connect_timeout": 10,
                },
            )
            logging.info(f"✅ PostgreSQL connection pool initialized (min={min_size}, max={max_size})")
        except Exception as e:
            logging.error(f"❌ Failed to create connection pool: {e}")
            raise

    return _pg_pool


def close_postgres_pool() -> None:
    """Close PostgreSQL connection pool gracefully."""
    global _pg_pool

    if _pg_pool is not None:
        try:
            _pg_pool.close()
            logging.info("✅ PostgreSQL connection pool closed")
        except Exception as e:
            logging.warning(f"⚠️ Error closing connection pool: {e}")
        finally:
            _pg_pool = None


def get_connection() -> Union[sqlite3.Connection, ConnectionProxy, PooledConnectionProxy]:
    """Returns a DB connection.

    Returns:
        - sqlite: sqlite3.Connection (with isolation_level=None for autocommit)
        - postgres: PooledConnectionProxy (psycopg connection from pool)
    """
    if not _is_postgres():
        db_path = (getattr(config, "SQLITE_PATH", "generator.db") or "generator.db").strip()
        conn = sqlite3.connect(db_path, check_same_thread=False, timeout=10, isolation_level=None)
        try:
            conn.execute("PRAGMA foreign_keys=ON")
        except Exception:
            pass
        return conn

    pool = get_postgres_pool()
    if pool is None:
        raise RuntimeError("Failed to get connection pool")
    return PooledConnectionProxy(pool)


def begin_transaction(conn: Union[sqlite3.Connection, ConnectionProxy]) -> None:
    """Start a transaction in a backend-appropriate way."""
    if _is_postgres():
        try:
            conn.execute("BEGIN ISOLATION LEVEL SERIALIZABLE")
        except Exception as e:
            logging.warning(f"Failed to begin transaction: {e}")
            pass
    else:
        try:
            conn.execute("BEGIN IMMEDIATE")
        except Exception as e:
            logging.warning(f"Failed to begin transaction: {e}")
            pass


def init_db() -> None:
    """Створення схеми (ідемпотентно) + seed generator_state defaults."""
    conn = get_connection()
    c = conn.cursor()

    if not _is_postgres():
        c.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, full_name TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS drivers (id INTEGER PRIMARY KEY, name TEXT UNIQUE)''')
        c.execute('''CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY,
            event_type TEXT,
            timestamp TEXT,
            user_name TEXT,
            value TEXT,
            driver_name TEXT,
            receipt_number TEXT,
            is_synced INTEGER DEFAULT 0,
            generator_id TEXT DEFAULT 'main'
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS generator_state (key TEXT PRIMARY KEY, value TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS schedule (date TEXT, hour INTEGER, is_off INTEGER, PRIMARY KEY(date, hour))''')
        c.execute('''CREATE TABLE IF NOT EXISTS maintenance (
            id INTEGER PRIMARY KEY,
            date TEXT,
            type TEXT,
            hours REAL,
            admin TEXT,
            generator_id TEXT DEFAULT 'main'
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS user_personnel (user_id INTEGER PRIMARY KEY, personnel_name TEXT, FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE)''')
        c.execute('''CREATE TABLE IF NOT EXISTS personnel_names (name TEXT PRIMARY KEY)''')
        c.execute('''CREATE TABLE IF NOT EXISTS user_ui (user_id INTEGER PRIMARY KEY, chat_id INTEGER, message_id INTEGER, FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE)''')
        c.execute('''CREATE TABLE IF NOT EXISTS user_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            message_text TEXT NOT NULL,
            message_type TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
        )''')

    else:
        c.execute('''CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY, full_name TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS drivers (id BIGSERIAL PRIMARY KEY, name TEXT UNIQUE)''')
        c.execute('''CREATE TABLE IF NOT EXISTS logs (
            id BIGSERIAL PRIMARY KEY,
            event_type TEXT,
            timestamp TEXT,
            user_name TEXT,
            value TEXT,
            driver_name TEXT,
            receipt_number TEXT,
            is_synced INTEGER DEFAULT 0,
            generator_id TEXT DEFAULT 'main'
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS generator_state (key TEXT PRIMARY KEY, value TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS schedule (date TEXT, hour INTEGER, is_off INTEGER, PRIMARY KEY(date, hour))''')
        c.execute('''CREATE TABLE IF NOT EXISTS maintenance (
            id BIGSERIAL PRIMARY KEY,
            date TEXT,
            type TEXT,
            hours DOUBLE PRECISION,
            admin TEXT,
            generator_id TEXT DEFAULT 'main'
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS user_personnel (user_id BIGINT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE, personnel_name TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS personnel_names (name TEXT PRIMARY KEY)''')
        c.execute('''CREATE TABLE IF NOT EXISTS user_ui (user_id BIGINT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE, chat_id BIGINT, message_id BIGINT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS user_messages (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            message_text TEXT NOT NULL,
            message_type TEXT NOT NULL,
            timestamp TEXT NOT NULL
        )''')

    try:
        c.execute("SELECT receipt_number FROM logs LIMIT 1")
        logging.info("✅ Колонка receipt_number вже існує")
    except Exception:
        logging.info("🔧 Додаємо колонку receipt_number...")
        try:
            begin_transaction(conn)
            c.execute("ALTER TABLE logs ADD COLUMN receipt_number TEXT")
            try:
                conn.commit()
            except Exception as e:
                logging.warning(f"⚠️ Помилка commit після додавання receipt_number: {e}")
            logging.info("✅ Колонка receipt_number додана")
        except Exception as e:
            try:
                conn.rollback()
            except Exception as re:
                logging.warning(f"⚠️ Помилка rollback: {re}")
            if "duplicate column" in str(e).lower() or "already exists" in str(e).lower():
                logging.info("✅ Колонка receipt_number вже існує")
            else:
                logging.warning(f"⚠️ Не вдалося додати receipt_number: {e}")

    try:
        c.execute("SELECT generator_id FROM logs LIMIT 1")
        logging.info("✅ Колонка generator_id в logs вже існує")
    except Exception:
        logging.info("🔧 Додаємо колонку generator_id в logs...")
        try:
            begin_transaction(conn)
            c.execute("ALTER TABLE logs ADD COLUMN generator_id TEXT DEFAULT 'main'")
            try:
                conn.commit()
            except Exception as e:
                logging.warning(f"⚠️ Помилка commit після додавання generator_id: {e}")
            logging.info("✅ Колонка generator_id в logs додана")
        except Exception as e:
            try:
                conn.rollback()
            except Exception as re:
                logging.warning(f"⚠️ Помилка rollback: {re}")
            if "duplicate column" in str(e).lower() or "already exists" in str(e).lower():
                logging.info("✅ Колонка generator_id в logs вже існує")
            else:
                logging.warning(f"⚠️ Не вдалося додати generator_id в logs: {e}")

    try:
        c.execute("SELECT generator_id FROM maintenance LIMIT 1")
        logging.info("✅ Колонка generator_id в maintenance вже існує")
    except Exception:
        logging.info("🔧 Додаємо колонку generator_id в maintenance...")
        try:
            begin_transaction(conn)
            c.execute("ALTER TABLE maintenance ADD COLUMN generator_id TEXT DEFAULT 'main'")
            try:
                conn.commit()
            except Exception as e:
                logging.warning(f"⚠️ Помилка commit після додавання generator_id в maintenance: {e}")
            logging.info("✅ Колонка generator_id в maintenance додана")
        except Exception as e:
            try:
                conn.rollback()
            except Exception as re:
                logging.warning(f"⚠️ Помилка rollback: {re}")
            if "duplicate column" in str(e).lower() or "already exists" in str(e).lower():
                logging.info("✅ Колонка generator_id в maintenance вже існує")
            else:
                logging.warning(f"⚠️ Не вдалося додати generator_id в maintenance: {e}")

    index_statements = [
        "CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON logs(timestamp)",
        "CREATE INDEX IF NOT EXISTS idx_logs_event_type ON logs(event_type)",
        "CREATE INDEX IF NOT EXISTS idx_logs_is_synced ON logs(is_synced)",
        "CREATE INDEX IF NOT EXISTS idx_logs_generator_id ON logs(generator_id)",
        "CREATE INDEX IF NOT EXISTS idx_maintenance_generator_id ON maintenance(generator_id)",
        "CREATE INDEX IF NOT EXISTS idx_user_messages_user_ts ON user_messages(user_id, timestamp DESC)",
    ]

    if _is_postgres():
        index_statements.extend(
            [
                "CREATE INDEX IF NOT EXISTS idx_logs_date_generator ON logs(timestamp, generator_id)",
                "CREATE INDEX IF NOT EXISTS idx_logs_sync_generator ON logs(is_synced, generator_id) WHERE is_synced = 0",
            ]
        )

    for stmt in index_statements:
        try:
            c.execute(stmt)
        except Exception as e:
            logging.warning(f"⚠️ Не вдалося створити індекс ({stmt}): {e}")

    defaults: list[tuple[str, str]] = [
        ("total_hours", "0.0"),
        ("last_oil_change", "0.0"),
        ("last_spark_change", "0.0"),
        ("status", "OFF"),
        ("active_shift", "none"),
        ("last_start_time", ""),
        ("last_start_date", ""),
        ("current_fuel", "0.0"),
        ("fuel_ordered_date", ""),
        ("fuel_alert_last_sent_ts", ""),
        ("stop_reminder_sent_date", ""),
        ("sheet_last_ok_ts", ""),
        ("sheet_first_fail_ts", ""),
        ("sheet_offline", "0"),
        ("sheet_offline_since_ts", ""),
        ("sync_in_progress", "0"),
        ("active_generator", "main"),
        ("emergency_total_hours", "0.0"),
        ("emergency_last_oil_change", "0.0"),
        ("emergency_last_spark_change", "0.0"),
    ]

    if _is_postgres():
        for k, v in defaults:
            try:
                c.execute(
                    "INSERT INTO generator_state (key, value) VALUES (%s, %s) ON CONFLICT(key) DO NOTHING",
                    (k, v),
                )
            except Exception as e:
                logging.warning(f"⚠️ Не вдалося додати дефолт {k}={v}: {e}")
    else:
        for k, v in defaults:
            try:
                c.execute("INSERT OR IGNORE INTO generator_state (key, value) VALUES (?, ?)", (k, v))
            except Exception as e:
                logging.warning(f"⚠️ Не вдалося додати дефолт {k}={v}: {e}")

    try:
        conn.commit()
    except Exception as e:
        logging.warning(f"⚠️ Помилка final commit в init_db: {e}")
    try:
        conn.close()
    except Exception as e:
        logging.warning(f"⚠️ Помилка закриття з'єднання: {e}")

    logging.info("✅ База даних ініціалізована (підтримка 2 генераторів + ТО + connection pool).")
