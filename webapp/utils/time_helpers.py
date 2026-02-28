"""Time-related helper utilities."""


def _within_work_window(now_t, start_t, end_t) -> bool:
    """True if now_t is within [start_t, end_t)."""
    if start_t <= end_t:
        return start_t <= now_t < end_t
    return now_t >= start_t or now_t < end_t
