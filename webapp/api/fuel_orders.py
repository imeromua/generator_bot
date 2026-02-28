"""Fuel orders API endpoints."""
import logging
from fastapi import Request
from fastapi.responses import JSONResponse
import database.db_api as db
from webapp.utils.validation import extract_user as _extract_user
from webapp.utils.permissions import is_admin as _is_admin

logger = logging.getLogger(__name__)


async def api_fuel_orders_list(request: Request):
    """GET /api/fuel/orders — list fuel orders."""
    user = _extract_user(request)
    if not user:
        return JSONResponse(content={"error": "Не авторизовано"}, status_code=401)
    try:
        from database.api.fuel_orders import get_orders, get_fuel_consumption_stats

        status_filter = request.query_params.get("status") or None
        orders = get_orders(status=status_filter, limit=50)
        stats = get_fuel_consumption_stats(days=30)
        return {"orders": orders, "consumption_stats": stats}
    except Exception as e:
        logger.exception("api_fuel_orders_list error")
        return JSONResponse(content={"error": str(e)}, status_code=500)


async def api_fuel_orders_create(request: Request):
    """POST /api/fuel/orders — create a new fuel order."""
    user = _extract_user(request)
    if not _is_admin(user):
        return JSONResponse(content={"error": "Тільки для адміністраторів"}, status_code=403)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(content={"error": "Невірний JSON"}, status_code=400)

    amount = body.get("amount_liters")
    if amount is None:
        return JSONResponse(content={"error": "amount_liters обов'язковий"}, status_code=400)
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return JSONResponse(content={"error": "Невірне значення кількості літрів"}, status_code=400)

    if amount <= 0 or amount > 100000:
        return JSONResponse(content={"error": "Кількість літрів поза допустимим діапазоном"}, status_code=400)

    try:
        from database.api.fuel_orders import create_order
        from utils.time import now_kiev

        now = now_kiev()
        user_id = int(user.get("id", 0))
        order_id = create_order(
            created_at=now.strftime("%Y-%m-%d %H:%M:%S"),
            amount_liters=amount,
            requested_by=user_id or None,
            supplier=str(body.get("supplier", "")).strip() or None,
            price=float(body["price"]) if body.get("price") else None,
            delivery_date=str(body.get("delivery_date", "")).strip() or None,
            notes=str(body.get("notes", "")).strip() or None,
        )
        return {"ok": True, "order_id": order_id, "message": "Замовлення створено"}
    except Exception as e:
        logger.exception("api_fuel_orders_create error")
        return JSONResponse(content={"error": str(e)}, status_code=500)


async def api_fuel_orders_update(request: Request):
    """POST /api/fuel/orders/update — update a fuel order status."""
    user = _extract_user(request)
    if not _is_admin(user):
        return JSONResponse(content={"error": "Тільки для адміністраторів"}, status_code=403)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(content={"error": "Невірний JSON"}, status_code=400)

    order_id = body.get("order_id")
    if not order_id:
        return JSONResponse(content={"error": "order_id обов'язковий"}, status_code=400)

    try:
        from database.api.fuel_orders import update_order, update_order_status, VALID_STATUSES

        new_status = str(body.get("status", "")).strip()
        if new_status and new_status not in VALID_STATUSES:
            return JSONResponse(
                content={"error": f"Статус має бути одним із: {', '.join(VALID_STATUSES)}"}, status_code=400
            )

        updated = update_order(
            int(order_id),
            supplier=str(body.get("supplier", "")).strip() or None,
            price=float(body["price"]) if body.get("price") else None,
            delivery_date=str(body.get("delivery_date", "")).strip() or None,
            status=new_status or None,
            notes=str(body.get("notes", "")).strip() or None,
        )
        if not updated:
            return JSONResponse(content={"error": "Нічого не оновлено"}, status_code=400)

        # If delivered, add fuel to current level atomically
        if new_status == "delivered":
            from database.api.fuel_orders import get_order

            order = get_order(int(order_id))
            if order:
                db.update_fuel(order["amount_liters"])
                user_id = int(user.get("id", 0))
                user_info = db.get_user(user_id)
                actor = user_info[1] if user_info else user.get("first_name", "Адмін")
                db.add_log("refill", actor, str(order["amount_liters"]))

        return {"ok": True, "message": "Замовлення оновлено"}
    except Exception as e:
        logger.exception("api_fuel_orders_update error")
        return JSONResponse(content={"error": str(e)}, status_code=500)
