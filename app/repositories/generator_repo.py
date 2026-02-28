"""Generator repository — wraps database.db_api generator functions."""

import logging
from typing import Literal

import database.db_api as db
from app.repositories.base import BaseRepository

logger = logging.getLogger(__name__)

GeneratorType = Literal["main", "emergency"]


class GeneratorRepository(BaseRepository):
    """Repository for generator-related database operations."""

    def get_active(self) -> str:
        """Return the currently active generator id."""
        return db.get_active_generator()

    def get_stats(self, generator_id: GeneratorType) -> dict:
        """Return runtime statistics for the given generator."""
        return db.get_generator_stats(generator_id)

    def get_name(self, generator_id: GeneratorType) -> str:
        """Return the human-readable name of a generator."""
        return db.get_generator_name(generator_id)

    def switch(self, generator_id: GeneratorType, admin_name: str = "admin") -> tuple:
        """Switch the active generator.

        Returns:
            Tuple of (success: bool, message: str).
        """
        return db.switch_generator(generator_id, admin_name)

    def is_emergency_active(self) -> bool:
        """Return True when the emergency generator is currently active."""
        return db.is_emergency_active()
