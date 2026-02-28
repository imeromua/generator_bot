"""ShiftService — business logic for shift management."""

import logging
from datetime import datetime

from app.repositories.shift_repo import ShiftRepository

logger = logging.getLogger(__name__)


class ShiftService:
    """Encapsulates all business logic related to generator shifts."""

    def __init__(self, repo: ShiftRepository) -> None:
        self.repo = repo

    def start_shift(self, event_type: str, user_name: str, dt: datetime) -> dict:
        """Start a new generator shift.

        Returns:
            Dict with ``ok`` (bool) and ``msg`` (str).
        """
        logger.info("Starting shift: type=%s user=%s dt=%s", event_type, user_name, dt)
        return self.repo.start(event_type, user_name, dt)

    def stop_shift(self, end_event_type: str, user_name: str, dt: datetime) -> dict:
        """Stop the active generator shift.

        Returns:
            Dict with ``ok`` (bool) and ``msg`` (str).
        """
        logger.info("Stopping shift: type=%s user=%s dt=%s", end_event_type, user_name, dt)
        return self.repo.stop(end_event_type, user_name, dt)

    def get_today_completed(self) -> list:
        """Return shifts completed today."""
        return self.repo.get_today_completed()

    def get_recent_events(self, limit: int = 20) -> list:
        """Return the most recent event log rows."""
        return self.repo.get_last_logs(limit)
