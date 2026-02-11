"""Compatibility layer for legacy Sheets sync helpers.

Runtime synchronization has been removed. This package is kept only so that
old imports like `from services.sheets_sync import ...` do not crash.

All functions below are no-ops and should not be used in new code.
"""

import logging

logger = logging.getLogger(__name__)

__all__ = [
    "push_logs_to_sheet",
    "pull_refill_from_sheet",
]


def _log_disabled(name: str) -> None:
    logger.info(
        "Sheets runtime sync helper '%s' is disabled. "
        "Use DB + manual import/export instead.",
        name,
    )


def push_logs_to_sheet(*args, **kwargs) -> None:  # type: ignore[override]
    _log_disabled("push_logs_to_sheet")


def pull_refill_from_sheet(*args, **kwargs) -> None:  # type: ignore[override]
    _log_disabled("pull_refill_from_sheet")
