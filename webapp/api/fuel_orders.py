"""Fuel orders API endpoints."""

import logging
from fastapi import Request
from fastapi.responses import JSONResponse
import config
import database.db_api as db
from webapp.utils import validation as _validation_mod
from webapp.utils import permissions as _permissions_mod
from webapp.utils.db_helpers import atomic_transaction, get_admin_info as _get_admin_info

logger = logging.getLogger(__name__)


async def api_fuel_orders_list(request: Request):
    """GET /api/fuel/orders — list fuel orders."""
    user = _validation_mod.extract_user(request)
    if user is None:
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
    user = _validation_mod.extract_user(request)
    if not user:
        return JSONResponse(content={"error": "Не авторизовано"}, status_code=401)
    if not _permissions_mod.is_admin(user):
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

    if amount <= 0 or amount > config.FUEL_ORDER_MAX_LITERS:
        return JSONResponse(
            content={"error": f"Кількість літрів має бути від 1 до {config.FUEL_ORDER_MAX_LITERS}"},
            status_code=400,
        )

    try:
        from database.api.fuel_orders import create_order
        from utils.time import now_kiev

        now = now_kiev()
        user_id, admin_name = _get_admin_info(user)
        order_id = create_order(
            created_at=now.strftime("%Y-%m-%d %H:%M:%S"),
            amount_liters=amount,
            requested_by=user_id or None,
            supplier=str(body.get("supplier", "")).strip() or None,
            price=float(body["price"]) if body.get("price") else None,
            delivery_date=str(body.get("delivery_date", "")).strip() or None,
            notes=str(body.get("notes", "")).strip() or None,
        )
        db.log_admin_action(
            user_id,
            admin_name,
            "fuel_order_create",
            f"Створено замовлення палива #{order_id}: {amount} л",
            target_entity=f"fuel_order:{order_id}",
            new_value={"order_id": order_id, "amount_liters": amount},
        )
        return {"ok": True, "order_id": order_id, "message": "Замовлення створено"}
    except Exception as e:
        logger.exception("api_fuel_orders_create error")
        return JSONResponse(content={"error": str(e)}, status_code=500)


async def api_fuel_orders_update(request: Request):
    """POST /api/fuel/orders/update — update a fuel order status."""
    user = _validation_mod.extract_user(request)
    if not user:
        return JSONResponse(content={"error": "Не авторизовано"}, status_code=401)
    if not _permissions_mod.is_admin(user):
        return JSONResponse(content={"error": "Тільки для адміністраторів"}, status_code=403)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(content={"error": "Невірний JSON"}, status_code=400)

    order_id = body.get("order_id")
    if not order_id:
        return JSONResponse(content={"error": "order_id обов'язковий"}, status_code=400)

    try:
        from database.api.fuel_orders import update_order, update_order_status, VALID_STATUSES, get_order

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

        user_id, admin_name = _get_admin_info(user)
        db.log_admin_action(
            user_id,
            admin_name,
            "fuel_order_update",
            f"Оновлено замовлення палива #{order_id}" + (f": статус → {new_status}" if new_status else ""),
            target_entity=f"fuel_order:{order_id}",
            new_value={"order_id": order_id, "status": new_status or None},
        )

        # If delivered, add fuel to current level atomically
        if new_status == "delivered":
            order = get_order(int(order_id))
            if order:
                with atomic_transaction() as conn:
                    db.update_fuel(order["amount_liters"], conn=conn)
                    db.add_log("refill", admin_name, str(order["amount_liters"]), conn=conn)

        return {"ok": True, "message": "Замовлення оновлено"}
    except Exception as e:
        logger.exception("api_fuel_orders_update error")
        return JSONResponse(content={"error": str(e)}, status_code=500)
