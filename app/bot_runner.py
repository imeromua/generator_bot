"""aiogram bot entry point.

Run as a standalone process::

    python -m app.bot_runner

Or via the existing main.py (unchanged) for backward compatibility::

    python main.py
"""

import asyncio
import logging
import os
import sys

# Ensure the project root is on sys.path when executed directly
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

logger = logging.getLogger(__name__)


def main() -> None:
    """Entry point — delegates to the existing main.main coroutine."""
    # main.py already provides a complete, production-ready polling loop
    # with auto-restart, logging setup and graceful shutdown.  We re-use
    # it here so there is no duplication of logic.
    from main import main as _bot_main, setup_logging

    setup_logging()
    logger.info("🤖 Starting bot via app.bot_runner …")
    try:
        asyncio.run(_bot_main())
    except KeyboardInterrupt:
        logger.info("🛑 Bot stopped by user.")
    except Exception as exc:
        logger.error("💥 Fatal error in bot_runner: %s", exc, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
