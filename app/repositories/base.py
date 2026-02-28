"""Abstract base repository."""

from abc import ABC


class BaseRepository(ABC):
    """Base class for all repositories.

    Repositories encapsulate all database access and expose
    a clean, domain-oriented interface to service classes.
    """
