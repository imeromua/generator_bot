import threading
import time

import database.db_api as db

# --- Offline probe (avoid hammering Sheets when offline) ---
_OFFLINE_PROBE_LOCK = threading.Lock()
_LAST_OFFLINE_PROBE_TS = 0.0
_OFFLINE_PROBE_INTERVAL_SECONDS = 5 * 60


def should_skip_offline_probe() -> bool:
    """True якщо зараз треба пропустити спробу звернення до Sheets через частий OFFLINE."""
    global _LAST_OFFLINE_PROBE_TS

    try:
        if db.sheet_is_offline():
            now_probe = time.monotonic()
            with _OFFLINE_PROBE_LOCK:
                if (now_probe - _LAST_OFFLINE_PROBE_TS) < _OFFLINE_PROBE_INTERVAL_SECONDS:
                    return True
                _LAST_OFFLINE_PROBE_TS = now_probe
    except Exception:
        pass

    return False
