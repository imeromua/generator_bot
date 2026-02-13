"""Compatibility layer for legacy Sheets sync helpers.

Runtime synchronization has been removed. This package is kept only so that
old imports like `from services.sheets_sync import ...` do not crash.

All functions below are no-ops and should not be used in new code.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "push_logs_to_sheet",
    "pull_refill_from_sheet",
]


def _log_disabled(name: str) -> None:
    """Log warning about disabled sync helper.

    Args:
        name: Function name being called
    """
    logger.info(
        "Sheets runtime sync helper '%s' is disabled. "
        "Use DB + manual import/export instead.",
        name,
    )


def push_logs_to_sheet(*args: Any, **kwargs: Any) -> None:
    """No-op stub for legacy compatibility."""
    _log_disabled("push_logs_to_sheet")


def pull_refill_from_sheet(*args: Any, **kwargs: Any) -> None:
    """No-op stub for legacy compatibility."""
    _log_disabled("pull_refill_from_sheet")
