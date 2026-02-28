"""User home router.

The "home" callback handler is now in handlers.common_parts.help (cb_home)
to avoid duplicate registration. This router is kept for backward compatibility
but is intentionally empty.
"""

from aiogram import Router

router = Router()
