import logging
import sqlite3
from urllib.parse import urlparse, urlunparse
import re

import config

try:
    import psycopg
    from psycopg import sql
    from psycopg import errors as pg_errors
    from psycopg_pool import ConnectionPool
except Exception:  # pragma: no cover
    psycopg = None
    sql = None
    pg_errors = None
    ConnectionPool = None


def _is_postgres() -> bool:
    return (getattr(config, "DB_BACKEND", "sqlite") or "sqlite").strip().lower() == "postgres"


_QMARK_PATTERN = re.compile(r"\?")


def _translate_qmarks(query: str) -> str:
    """Translate sqlite-style placeholders ('?') to psycopg placeholders ('%s').

    For PostgreSQL backend replaces all '?' with '%s'. For SQLite returns
    query unchanged.
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

    For pooled connections we MUST NOT close them on context exit, only return
    them to the pool. Closing pooled connections leads to "the connection is
    closed" errors when the pool reuses them.
    """

    def __init__(self, conn, from_pool=False):
        self._conn = conn
        self._from_pool = from_pool

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
        """Close connection or return to pool."""
        if self._from_pool:
            # Return connection to pool instead of closing
            try:
                pool = get_postgres_pool()
                pool.putconn(self._conn)
                logging.debug("✅ Connection returned to pool")
            except Exception as e:
                logging.warning(f"⚠️ Failed to return connection to pool: {e}")
                try:
                    self._conn.close()
                except Exception:
                    pass
        else:
            return self._conn.close()

    def __enter__(self):
        """Support `with get_connection() as conn:` pattern.

        For pooled connections we do NOT delegate to the underlying
        connection's context manager (it would close the connection).
        We simply return self and let __exit__ handle pool return.
        """
        if not self._from_pool:
            # For non-pooled connections (SQLite or direct psycopg) preserve
            # default context manager behaviour.
            self._conn.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        """On context exit, either close connection or return to pool.

        For pooled connections: return to pool and DO NOT close.
        For non-pooled connections: delegate to underlying __exit__.
        """
        if self._from_pool:
            try:
                pool = get_postgres_pool()
                pool.putconn(self._conn)
                logging.debug("✅ Connection returned to pool from context manager")
            except Exception as e:
                logging.warning(f"⚠️ Failed to return connection to pool: {e}")
                try:
                    self._conn.close()
                except Exception:
                    pass
            # Do not suppress exceptions
            return False
        # Non-pooled connection: preserve original behaviour
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

    # Check if DB exists using temporary connection
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
            f"Failed to create Postgres database '{dbname}'. " f"Check POSTGRES_ADMIN_DSN / permissions. Error: {e}"
        )


# Global connection pool
_pg_pool = None


def get_postgres_pool():
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

        # Ensure database exists before creating pool
        ensure_postgres_database_exists()

        # Create connection pool with reasonable defaults
        min_size = getattr(config, "PG_POOL_MIN_SIZE", 2)
        max_size = getattr(config, "PG_POOL_MAX_SIZE", 10)
        timeout = getattr(config, "PG_POOL_TIMEOUT", 30)
        max_idle = getattr(config, "PG_POOL_MAX_IDLE", 300)  # 5 minutes

        try:
            _pg_pool = ConnectionPool(
                conninfo=dsn,
                min_size=min_size,
                max_size=max_size,
                timeout=timeout,
                max_idle=max_idle,
                # Configure connection properties
                kwargs={
                    "autocommit": True,  # Match SQLite semantics
                    "connect_timeout": 10,
                },
            )
            logging.info(f"✅ PostgreSQL connection pool initialized (min={min_size}, max={max_size})")
        except Exception as e:
            logging.error(f"❌ Failed to create connection pool: {e}")
            raise

    return _pg_pool


def close_postgres_pool():
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


def get_connection():
    """Returns a DB connection.

    - sqlite: sqlite3.Connection (with isolation_level=None for autocommit)
    - postgres: ConnectionProxy (psycopg connection from pool, autocommit enabled)
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

    # PostgreSQL: get connection from pool
    try:
        pool = get_postgres_pool()
        conn = pool.getconn()
        return ConnectionProxy(conn, from_pool=True)
    except Exception as e:
        logging.error(f"❌ Failed to get connection from pool: {e}")
        raise


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
        c.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            full_name TEXT,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            role TEXT NOT NULL DEFAULT 'user',
            is_active INTEGER NOT NULL DEFAULT 1,
            registered_at TEXT,
            last_activity TEXT,
            blocked_at TEXT,
            blocked_by INTEGER,
            block_reason TEXT,
            deleted_at TEXT
        )''')
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
        c.execute(
            '''CREATE TABLE IF NOT EXISTS schedule (date TEXT, hour INTEGER, is_off INTEGER, PRIMARY KEY(date, hour))'''
        )
        c.execute('''CREATE TABLE IF NOT EXISTS maintenance (
            id INTEGER PRIMARY KEY,
            date TEXT,
            type TEXT,
            hours REAL,
            admin TEXT,
            generator_id TEXT DEFAULT 'main'
        )''')
        c.execute(
            '''CREATE TABLE IF NOT EXISTS user_personnel (user_id INTEGER PRIMARY KEY, personnel_name TEXT, FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE)'''
        )
        c.execute('''CREATE TABLE IF NOT EXISTS personnel_names (name TEXT PRIMARY KEY)''')
        c.execute(
            '''CREATE TABLE IF NOT EXISTS user_ui (user_id INTEGER PRIMARY KEY, chat_id INTEGER, message_id INTEGER, FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE)'''
        )
        c.execute('''CREATE TABLE IF NOT EXISTS user_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            message_text TEXT NOT NULL,
            message_type TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS admin_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            admin_user_id INTEGER NOT NULL,
            admin_name TEXT,
            action_type TEXT NOT NULL,
            action_description TEXT,
            target_entity TEXT,
            old_value TEXT,
            new_value TEXT,
            success INTEGER NOT NULL DEFAULT 1
        )''')
        # Task 5: Push notifications preferences
        c.execute('''CREATE TABLE IF NOT EXISTS notification_preferences (
            user_id INTEGER NOT NULL,
            notification_type TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            quiet_hours_start TEXT DEFAULT NULL,
            quiet_hours_end TEXT DEFAULT NULL,
            delivery_method TEXT NOT NULL DEFAULT 'telegram',
            PRIMARY KEY (user_id, notification_type)
        )''')
        # Task 6: Fuel orders
        c.execute('''CREATE TABLE IF NOT EXISTS fuel_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            requested_by INTEGER,
            amount_liters REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            supplier TEXT,
            price REAL,
            delivery_date TEXT,
            notes TEXT
        )''')
        # Task 8: Shift schedule
        c.execute('''CREATE TABLE IF NOT EXISTS shift_schedule (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            shift_type TEXT NOT NULL,
            assigned_personnel_id TEXT,
            status TEXT NOT NULL DEFAULT 'planned',
            notes TEXT,
            UNIQUE(date, shift_type)
        )''')

    else:
        c.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            full_name TEXT,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            role TEXT NOT NULL DEFAULT 'user',
            is_active INTEGER NOT NULL DEFAULT 1,
            registered_at TEXT,
            last_activity TEXT,
            blocked_at TEXT,
            blocked_by BIGINT,
            block_reason TEXT,
            deleted_at TEXT
        )''')
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
        c.execute(
            '''CREATE TABLE IF NOT EXISTS schedule (date TEXT, hour INTEGER, is_off INTEGER, PRIMARY KEY(date, hour))'''
        )
        c.execute('''CREATE TABLE IF NOT EXISTS maintenance (
            id BIGSERIAL PRIMARY KEY,
            date TEXT,
            type TEXT,
            hours DOUBLE PRECISION,
            admin TEXT,
            generator_id TEXT DEFAULT 'main'
        )''')
        c.execute(
            '''CREATE TABLE IF NOT EXISTS user_personnel (user_id BIGINT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE, personnel_name TEXT)'''
        )
        c.execute('''CREATE TABLE IF NOT EXISTS personnel_names (name TEXT PRIMARY KEY)''')
        c.execute(
            '''CREATE TABLE IF NOT EXISTS user_ui (user_id BIGINT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE, chat_id BIGINT, message_id BIGINT)'''
        )
        c.execute('''CREATE TABLE IF NOT EXISTS user_messages (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            message_text TEXT NOT NULL,
            message_type TEXT NOT NULL,
            timestamp TEXT NOT NULL
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS admin_audit_log (
            id BIGSERIAL PRIMARY KEY,
            timestamp TEXT NOT NULL,
            admin_user_id BIGINT NOT NULL,
            admin_name TEXT,
            action_type TEXT NOT NULL,
            action_description TEXT,
            target_entity TEXT,
            old_value TEXT,
            new_value TEXT,
            success INTEGER NOT NULL DEFAULT 1
        )''')
        # Task 5: Push notifications preferences
        c.execute('''CREATE TABLE IF NOT EXISTS notification_preferences (
            user_id BIGINT NOT NULL,
            notification_type TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            quiet_hours_start TEXT DEFAULT NULL,
            quiet_hours_end TEXT DEFAULT NULL,
            delivery_method TEXT NOT NULL DEFAULT 'telegram',
            PRIMARY KEY (user_id, notification_type)
        )''')
        # Task 6: Fuel orders
        c.execute('''CREATE TABLE IF NOT EXISTS fuel_orders (
            id BIGSERIAL PRIMARY KEY,
            created_at TEXT NOT NULL,
            requested_by BIGINT,
            amount_liters DOUBLE PRECISION NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            supplier TEXT,
            price DOUBLE PRECISION,
            delivery_date TEXT,
            notes TEXT
        )''')
        # Task 8: Shift schedule
        c.execute('''CREATE TABLE IF NOT EXISTS shift_schedule (
            id BIGSERIAL PRIMARY KEY,
            date TEXT NOT NULL,
            shift_type TEXT NOT NULL,
            assigned_personnel_id TEXT,
            status TEXT NOT NULL DEFAULT 'planned',
            notes TEXT,
            UNIQUE(date, shift_type)
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

    # Міграція: додавання нових колонок в users (для управління ролями)
    _blocked_by_type = "BIGINT" if _is_postgres() else "INTEGER"
    _users_new_columns = [
        ("username", "TEXT"),
        ("first_name", "TEXT"),
        ("last_name", "TEXT"),
        ("role", "TEXT NOT NULL DEFAULT 'user'"),
        ("is_active", "INTEGER NOT NULL DEFAULT 1"),
        ("registered_at", "TEXT"),
        ("last_activity", "TEXT"),
        ("blocked_at", "TEXT"),
        ("blocked_by", _blocked_by_type),
        ("block_reason", "TEXT"),
        ("deleted_at", "TEXT"),
    ]
    for col_name, col_def in _users_new_columns:
        try:
            c.execute(f"SELECT {col_name} FROM users LIMIT 1")
        except Exception:
            try:
                c.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_def}")
                logging.info(f"✅ Колонка users.{col_name} додана")
            except Exception as e:
                if "duplicate column" in str(e).lower() or "already exists" in str(e).lower():
                    logging.info(f"✅ Колонка users.{col_name} вже існує")
                else:
                    logging.warning(f"⚠️ Не вдалося додати users.{col_name}: {e}")

    # SD-1 Міграція: нові колонки в users для веб-авторизації
    # Note: SQLite does not support ADD COLUMN with UNIQUE constraint;
    # uniqueness is enforced via dedicated UNIQUE indexes added below.
    _web_auth_user_columns = [
        ("email", "TEXT"),
        ("password_hash", "TEXT"),
        ("web_login", "TEXT"),
        ("web_last_login", "TEXT"),
        ("telegram_linked", "INTEGER DEFAULT 1"),
    ]
    for col_name, col_def in _web_auth_user_columns:
        try:
            c.execute(f"SELECT {col_name} FROM users LIMIT 1")
        except Exception:
            try:
                c.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_def}")
                logging.info(f"✅ Колонка users.{col_name} додана")
            except Exception as e:
                if "duplicate column" in str(e).lower() or "already exists" in str(e).lower():
                    logging.info(f"✅ Колонка users.{col_name} вже існує")
                else:
                    logging.warning(f"⚠️ Не вдалося додати users.{col_name}: {e}")

    # SD-1 Нова таблиця web_sessions
    _id_col = "BIGSERIAL" if _is_postgres() else "INTEGER"
    _user_id_type = "BIGINT" if _is_postgres() else "INTEGER"
    try:
        c.execute(f"""CREATE TABLE IF NOT EXISTS web_sessions (
            id {_id_col} PRIMARY KEY,
            user_id {_user_id_type} NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            token TEXT NOT NULL UNIQUE,
            refresh_token TEXT UNIQUE,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            ip_address TEXT,
            user_agent TEXT,
            is_active INTEGER NOT NULL DEFAULT 1
        )""")
        logging.info("✅ Таблиця web_sessions готова")
    except Exception as e:
        logging.warning(f"⚠️ Не вдалося створити web_sessions: {e}")

    # SD-1 Нова таблиця web_password_reset
    try:
        c.execute(f"""CREATE TABLE IF NOT EXISTS web_password_reset (
            id {_id_col} PRIMARY KEY,
            user_id {_user_id_type} NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            reset_token TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            used INTEGER NOT NULL DEFAULT 0
        )""")
        logging.info("✅ Таблиця web_password_reset готова")
    except Exception as e:
        logging.warning(f"⚠️ Не вдалося створити web_password_reset: {e}")

    # Індекси для оптимізації пошуку (створюються ПІСЛЯ міграцій!)
    index_statements = [
        "CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON logs(timestamp)",
        "CREATE INDEX IF NOT EXISTS idx_logs_event_type ON logs(event_type)",
        "CREATE INDEX IF NOT EXISTS idx_logs_is_synced ON logs(is_synced)",
        "CREATE INDEX IF NOT EXISTS idx_logs_generator_id ON logs(generator_id)",
        "CREATE INDEX IF NOT EXISTS idx_maintenance_generator_id ON maintenance(generator_id)",
        "CREATE INDEX IF NOT EXISTS idx_user_messages_user_ts ON user_messages(user_id, timestamp DESC)",
        "CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp ON admin_audit_log(timestamp)",
        "CREATE INDEX IF NOT EXISTS idx_audit_log_admin ON admin_audit_log(admin_user_id)",
        "CREATE INDEX IF NOT EXISTS idx_audit_log_action_type ON admin_audit_log(action_type)",
        "CREATE INDEX IF NOT EXISTS idx_notif_prefs_user ON notification_preferences(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_fuel_orders_status ON fuel_orders(status)",
        "CREATE INDEX IF NOT EXISTS idx_fuel_orders_created ON fuel_orders(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_shift_schedule_date ON shift_schedule(date)",
        "CREATE INDEX IF NOT EXISTS idx_shift_schedule_personnel ON shift_schedule(assigned_personnel_id)",
        "CREATE INDEX IF NOT EXISTS idx_users_role ON users(role)",
        "CREATE INDEX IF NOT EXISTS idx_users_active ON users(is_active)",
        "CREATE INDEX IF NOT EXISTS idx_web_sessions_user ON web_sessions(user_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email) WHERE email IS NOT NULL",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_web_login ON users(web_login) WHERE web_login IS NOT NULL",
    ]

    # PostgreSQL-specific optimized indexes
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
        ('active_generator', 'main'),
        ('last_maintenance', '0.0'),
        ('emergency_total_hours', '0.0'),
        ('emergency_last_oil_change', '0.0'),
        ('emergency_last_spark_change', '0.0'),
        ('emergency_last_maintenance', '0.0'),
    ]

    # Backend-specific INSERT syntax (no fallback needed with direct syntax)
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
        # SQLite with autocommit: use INSERT OR IGNORE directly
        for k, v in defaults:
            try:
                c.execute("INSERT OR IGNORE INTO generator_state (key, value) VALUES (?, ?)", (k, v))
            except Exception as e:
                logging.warning(f"⚠️ Не вдалося додати дефолт {k}={v}: {e}")

    # Config tables (generator_config, global_config, config_history)
    try:
        from database.api.config import _ensure_tables, _seed_defaults

        _ensure_tables(conn)
        _seed_defaults(conn)
    except Exception as e:
        logging.warning(f"⚠️ Не вдалося ініціалізувати таблиці конфігурації: {e}")

    try:
        conn.commit()
    except Exception as e:
        logging.warning(f"⚠️ Помилка final commit в init_db: {e}")
    try:
        conn.close()
    except Exception as e:
        logging.warning(f"⚠️ Помилка закриття з'єднання: {e}")

    logging.info("✅ База даних ініціалізована (підтримка 2 генераторів + ТО + connection pool).")
