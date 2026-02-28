"""Repository layer — abstracts all database access."""

from app.repositories.base import BaseRepository
from app.repositories.generator_repo import GeneratorRepository
from app.repositories.shift_repo import ShiftRepository
from app.repositories.fuel_repo import FuelRepository

__all__ = [
    "BaseRepository",
    "GeneratorRepository",
    "ShiftRepository",
    "FuelRepository",
]
