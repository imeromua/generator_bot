"""Events API endpoint."""
import logging
from fastapi import Request
from fastapi.responses import JSONResponse
import database.db_api as db

logger = logging.getLogger(__name__)
MAX_EVENTS_LIMIT = 100


async def api_events(request: Request):
    """GET /api/events?limit=20 — останні події."""
    try:
        limit = min(int(request.query_params.get("limit", "20")), MAX_EVENTS_LIMIT)
    except (ValueError, TypeError):
        limit = 20

    try:
        rows = db.get_last_logs(limit)
        events = []
        for row in rows:
            events.append(
                {
                    "event_type": row[0] if len(row) > 0 else "",
                    "timestamp": row[1] if len(row) > 1 else "",
                    "actor": row[2] if len(row) > 2 else "",
                    "value": row[3] if len(row) > 3 else "",
                    "driver": row[4] if len(row) > 4 else "",
                    "receipt": row[5] if len(row) > 5 else "",
                }
            )
        return {"events": events, "count": len(events)}
    except Exception as e:
        logger.exception("api_events error")
        return JSONResponse(content={"error": str(e)}, status_code=500)
