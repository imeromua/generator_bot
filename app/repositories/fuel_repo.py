"""Fuel repository — wraps database.db_api fuel functions."""

import logging

import database.db_api as db
from app.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class FuelRepository(BaseRepository):
    """Repository for fuel-related database operations."""

    def get_consumption_rate(self, generator_id: str = "main") -> float:
        """Return the configured fuel consumption rate (litres/hour)."""
        return db.get_fuel_consumption_rate(generator_id)

    def update(self, liters_delta: float) -> None:
        """Update the current fuel level by the given delta (can be negative)."""
        db.update_fuel(liters_delta)

    def get_state(self) -> dict:
        """Return the current generator state dict (includes current_fuel)."""
        return db.get_state()
