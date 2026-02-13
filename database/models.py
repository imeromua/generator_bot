import logging
import sqlite3
from urllib.parse import urlparse, urlunparse
import re

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


_QMARK_PATTERN = re.compile(r"\?(?=(?:[^'\"]|'[^']*'|\"[^\"]*\")*$)")


def _translate_qmarks(query: str) -> str:
    """Translate sqlite-style placeholders ('?') to psycopg placeholders ('%s').

    Uses a regex that replaces only placeholders outside of quoted string
    literals to avoid corrupting SQL that legitimately contains '?' inside
    string values or comments.
    """
    if not _is_postgres():
        return query
    return _QMARK_PATTERN.sub("%s", str(query))


def _safe_postgres_target(dsn: str) -> str:
    """Return safe (password-free) string like user@host:port/db."""
    try:
        u = urlparse(dsn)
        user = u.username or "?"
        host = u.hostname or "localhost"
        port = u.port or 5432
        db = (u.path or "").lstrip("/") or "?"
        return f"{user}@{host}:{port}/{db}"
    except Exception:
        return "(invalid POSTGRES_DSN)"


def db_target_info() -> str:
    if not _is_postgres():
        db_path = (getattr(config, "SQLITE_PATH", "generator.db") or "generator.db").strip()
        return f"sqlite:{db_path}"
    return f"postgres:{_safe_postgres_target(getattr(config, 'POSTGRES_DSN', '') or '')}"


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
    """Small adapter around psycopg connection to support sqlite-style SQL.

    IMPORTANT (Postgres): psycopg connections are transactional by default.
    Many project modules use `with get_connection() as conn:` and do not call `commit()`.

    To keep sqlite-like semantics and avoid silent rollbacks on context exit,
    we enable autocommit for Postgres connections in `get_connection()`.
    """

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


def ensure_postgres_database_exists():
    """Ensure target Postgres database exists; create it if missing."""
    if not _is_postgres():
        return

    if psycopg is None:
        raise RuntimeError("psycopg is not installed but DB_BACKEND=postgres")

    dsn = (getattr(config, "POSTGRES_DSN", "") or "").strip()
    if not dsn:
        raise RuntimeError("POSTGRES_DSN is not set")

    # FIX #4: Add connection timeout
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


def get_connection():
    """Returns a DB connection.

    - sqlite: sqlite3.Connection (with isolation_level=None for autocommit)
    - postgres: ConnectionProxy (psycopg connection wrapper, autocommit enabled)
    """
    if not _is_postgres():
        db_path = (getattr(config, "SQLITE_PATH", "generator.db") or "generator.db").strip()
        # FIX #1: Use isolation_level=None (autocommit) for SQLite to avoid locking issues
        # This provides similar semantics to Postgres autocommit mode
        conn = sqlite3.connect(db_path, check_same_thread=False, timeout=10, isolation_level=None)
        try:
            conn.execute("PRAGMA foreign_keys=ON")
        except Exception:
            pass
        return conn

    ensure_postgres_database_exists()
    # FIX #4: Add connection timeout
    conn = psycopg.connect(getattr(config, "POSTGRES_DSN"), connect_timeout=10)
    try:
        conn.autocommit = True
    except Exception:
        pass
    return ConnectionProxy(conn)


def begin_transaction(conn):
    """Start a transaction in a backend-appropriate way.

    FIX #2: Use SERIALIZABLE isolation level for Postgres to prevent phantom reads
    and ensure proper CAS (Compare-And-Set) operations in concurrent scenarios.
    """
    if _is_postgres():
        try:
            # Use SERIALIZABLE for strongest isolation guarantees
            conn.execute("BEGIN ISOLATION LEVEL SERIALIZABLE")
        except Exception as e:
            # FIX #3: Log errors instead of silent failures
            logging.warning(f"Failed to begin transaction: {e}")
            pass
    else:
        # SQLite: BEGIN IMMEDIATE prevents deadlocks in concurrent writes
        try:
            conn.execute("BEGIN IMMEDIATE")
        except Exception as e:
            # FIX #3: Log errors instead of silent failures
            logging.warning(f"Failed to begin transaction: {e}")
            pass


def init_db():
    """Створення схеми (ідемпотентно) + seed generator_state defaults.

    Підтримка двох генераторів: основного та аварійного.
    Додано generator_id в logs та maintenance для розділення записів.
    """
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

    # Міграція: додавання receipt_number (старий код)
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

    # Міграція: додавання generator_id в logs (нове для підтримки аварійного генератора)
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
                logging.warning(f"⚠️ Не вдалося додати generator_id: {e}")

    # Міграція: додавання generator_id в maintenance (нове для ТО по генераторах)
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

    # Індекси для оптимізації пошуку (створюються ПІСЛЯ міграцій!)
    index_statements = [
        "CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON logs(timestamp)",
        "CREATE INDEX IF NOT EXISTS idx_logs_event_type ON logs(event_type)",
        "CREATE INDEX IF NOT EXISTS idx_logs_is_synced ON logs(is_synced)",
        "CREATE INDEX IF NOT EXISTS idx_logs_generator_id ON logs(generator_id)",  # NEW: index for emergency generator
        "CREATE INDEX IF NOT EXISTS idx_maintenance_generator_id ON maintenance(generator_id)",  # NEW: index for maintenance per generator
        "CREATE INDEX IF NOT EXISTS idx_user_messages_user_ts ON user_messages(user_id, timestamp DESC)",
    ]
    for stmt in index_statements:
        try:
            c.execute(stmt)
        except Exception as e:
            logging.warning(f"⚠️ Не вдалося створити індекс ({stmt}): {e}")

    # Дефолтні значення generator_state
    defaults = [
        # Основні параметри
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
        ('sync_in_progress', '0'),

        # ПІДТРИМКА ДВОХ ГЕНЕРАТОРІВ: основний та аварійний
        ('active_generator', 'main'),  # 'main' або 'emergency'
        ('emergency_total_hours', '0.0'),  # мотогодини аварійного
        ('emergency_last_oil_change', '0.0'),  # остання заміна мастила (аварійний)
        ('emergency_last_spark_change', '0.0'),  # остання заміна свічок (аварійний)
    ]

    for k, v in defaults:
        try:
            c.execute(
                """
                INSERT INTO generator_state (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO NOTHING
                """,
                (k, v),
            )
        except Exception as e:
            try:
                if _is_postgres():
                    conn.rollback()
                c.execute("INSERT OR IGNORE INTO generator_state (key, value) VALUES (?, ?)", (k, v))
            except Exception as e2:
                logging.warning(f"⚠️ Не вдалося додати дефолт {k}={v}: {e2}")

    try:
        conn.commit()
    except Exception as e:
        logging.warning(f"⚠️ Помилка final commit в init_db: {e}")
    try:
        conn.close()
    except Exception as e:
        logging.warning(f"⚠️ Помилка закриття з'єднання: {e}")

    logging.info("✅ База даних ініціалізована (підтримка 2 генераторів + ТО).")
