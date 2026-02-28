"""FuelService — business logic for fuel management."""

import logging

from app.repositories.fuel_repo import FuelRepository

logger = logging.getLogger(__name__)


class FuelService:
    """Encapsulates all business logic related to fuel."""

    def __init__(self, repo: FuelRepository) -> None:
        self.repo = repo

    def get_consumption_rate(self, generator_id: str = "main") -> float:
        """Return fuel consumption rate in litres per hour."""
        return self.repo.get_consumption_rate(generator_id)

    def get_current_level(self) -> float:
        """Return the current fuel level in litres."""
        state = self.repo.get_state()
        return float(state.get("current_fuel", 0))

    def refuel(self, liters: float) -> None:
        """Record a refuel event (positive delta)."""
        if liters <= 0:
            raise ValueError(f"Refuel amount must be positive, got {liters}")
        logger.info("Refuelling: +%.1f L", liters)
        self.repo.update(liters)

    def consume(self, liters: float) -> None:
        """Record fuel consumption (negative delta)."""
        if liters <= 0:
            raise ValueError(f"Consumption amount must be positive, got {liters}")
        logger.info("Consuming fuel: -%.1f L", liters)
        self.repo.update(-liters)
