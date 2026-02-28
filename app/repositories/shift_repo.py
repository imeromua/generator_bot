"""Shift repository — wraps database.db_api shift / log functions."""

import logging
from datetime import datetime

import database.db_api as db
from app.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class ShiftRepository(BaseRepository):
    """Repository for shift-related database operations."""

    def start(self, event_type: str, user_name: str, dt: datetime) -> dict:
        """Attempt to start a new shift.

        Returns:
            Dict with keys ``ok`` (bool) and ``msg`` (str).
        """
        return db.try_start_shift(event_type, user_name, dt)

    def stop(self, end_event_type: str, user_name: str, dt: datetime) -> dict:
        """Attempt to stop the active shift.

        Returns:
            Dict with keys ``ok`` (bool) and ``msg`` (str).
        """
        return db.try_stop_shift(end_event_type, user_name, dt)

    def get_today_completed(self) -> list:
        """Return list of completed shifts for today."""
        return list(db.get_today_completed_shifts())

    def get_last_logs(self, limit: int = 20) -> list:
        """Return the most recent log rows."""
        return list(db.get_last_logs(limit))
