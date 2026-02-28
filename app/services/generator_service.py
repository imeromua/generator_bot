"""GeneratorService — business logic for generator management."""

import logging
from typing import Literal

from app.repositories.generator_repo import GeneratorRepository

logger = logging.getLogger(__name__)

GeneratorType = Literal["main", "emergency"]


class GeneratorService:
    """Encapsulates all business logic related to generators."""

    def __init__(self, repo: GeneratorRepository) -> None:
        self.repo = repo

    def get_active_generator(self) -> str:
        """Return the id of the currently active generator."""
        return self.repo.get_active()

    def get_stats(self, generator_id: GeneratorType | None = None) -> dict:
        """Return runtime statistics for a generator.

        If *generator_id* is omitted the currently active generator is used.
        """
        resolved: GeneratorType = generator_id if generator_id is not None else self.repo.get_active()  # type: ignore[assignment]
        return self.repo.get_stats(resolved)

    def get_name(self, generator_id: GeneratorType | None = None) -> str:
        """Return the human-readable name of a generator."""
        resolved: GeneratorType = generator_id if generator_id is not None else self.repo.get_active()  # type: ignore[assignment]
        return self.repo.get_name(resolved)

    def switch_generator(self, generator_id: GeneratorType, admin_name: str = "admin") -> tuple:
        """Switch the active generator.

        Returns:
            Tuple of (success: bool, message: str).
        """
        logger.info("Switching generator to '%s' (admin=%s)", generator_id, admin_name)
        return self.repo.switch(generator_id, admin_name)

    def is_emergency_active(self) -> bool:
        """Return True when the emergency generator is currently active."""
        return self.repo.is_emergency_active()
