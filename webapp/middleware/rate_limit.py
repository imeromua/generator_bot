"""Rate limiting middleware for webapp."""

import logging
import time as _time
from collections import defaultdict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

_rate_limit_counts: dict = defaultdict(list)
_RATE_LIMIT_MAX = 100
_RATE_LIMIT_WINDOW = 60  # seconds
_RATE_LIMIT_CLEANUP_INTERVAL = 300  # clean stale IPs every 5 minutes
_rate_limit_last_cleanup = 0.0


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple in-memory rate limiter: 100 requests per minute per IP."""

    async def dispatch(self, request: Request, call_next):
        global _rate_limit_last_cleanup

        if request.method == "OPTIONS":
            return await call_next(request)

        ip = request.client.host if request.client else "unknown"
        now = _time.monotonic()
        window_start = now - _RATE_LIMIT_WINDOW

        # Periodically clean up IPs with no recent requests to prevent memory growth
        if now - _rate_limit_last_cleanup > _RATE_LIMIT_CLEANUP_INTERVAL:
            stale = [k for k, v in _rate_limit_counts.items() if not v or v[-1] < window_start]
            for k in stale:
                del _rate_limit_counts[k]
            _rate_limit_last_cleanup = now

        _rate_limit_counts[ip] = [t for t in _rate_limit_counts[ip] if t > window_start]

        if len(_rate_limit_counts[ip]) >= _RATE_LIMIT_MAX:
            logger.warning(f"⚠️ Rate limit exceeded for IP {ip}")
            return JSONResponse(
                content={"error": "Забагато запитів. Спробуйте пізніше."},
                status_code=429,
            )

        _rate_limit_counts[ip].append(now)
        return await call_next(request)
