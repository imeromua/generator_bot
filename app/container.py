"""Dependency-injection container.

Instantiates and wires together repositories and services.
Use ``Container()`` as a single source of truth for all shared objects.

Example usage with FastAPI Depends::

    from app.container import Container

    _container: Container | None = None

    def get_container() -> Container:
        if _container is None:
            raise RuntimeError("Container not initialised")
        return _container

    @app.get("/status")
    def status(container: Container = Depends(get_container)):
        return container.generator_service.get_stats()
"""

import logging

from app.repositories.fuel_repo import FuelRepository
from app.repositories.generator_repo import GeneratorRepository
from app.repositories.shift_repo import ShiftRepository
from app.services.fuel_service import FuelService
from app.services.generator_service import GeneratorService
from app.services.shift_service import ShiftService

logger = logging.getLogger(__name__)


class Container:
    """Wires repositories into services and exposes them as attributes."""

    def __init__(self) -> None:
        # Repositories
        self.generator_repo: GeneratorRepository = GeneratorRepository()
        self.shift_repo: ShiftRepository = ShiftRepository()
        self.fuel_repo: FuelRepository = FuelRepository()

        # Services
        self.generator_service: GeneratorService = GeneratorService(self.generator_repo)
        self.fuel_service: FuelService = FuelService(self.fuel_repo)
        self.shift_service: ShiftService = ShiftService(self.shift_repo)

        logger.debug("Container initialised")
