"""Legacy Google Sheets runtime sync module.

Runtime synchronization with Google Sheets is fully disabled in this project.
This module is kept only to preserve imports from older code paths.

All functions here are now no-ops and only log that sync is disabled.
Use services.sheets_import / services.sheets_export for manual operations.
"""

import logging

logger = logging.getLogger(__name__)

__all__ = ["sync_loop", "sync_canonical_state_once"]


async def sync_loop() -> None:
    """Disabled background sync loop (no-op)."""
    logger.info("Google Sheets runtime sync is disabled. " "Manual import/export should be used instead.")


async def sync_canonical_state_once() -> None:
    """Disabled one-shot sync (no-op)."""
    logger.info("Google Sheets canonical state sync is disabled. " "Manual import/export should be used instead.")
