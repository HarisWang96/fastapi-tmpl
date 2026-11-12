"""Example business endpoints with validation, persistence and idempotency."""

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.core.idempotency import idempotent
from app.dependencies import AsyncSessionDep
from app.errors import AppError
from app.models.order import Order
from app.schemas.orders import OrderCreate, OrderView
from app.services.orders import create_order

router = APIRouter(prefix="/api/v1/orders", tags=["orders"])


@router.post("", response_model=OrderView, status_code=status.HTTP_201_CREATED)
@idempotent(required=True, status_code=status.HTTP_201_CREATED)
async def post_order(
    request: Request,
    payload: OrderCreate,
    db: AsyncSessionDep,
) -> Order:
    order = await create_order(db, payload)
    # Serialize once before the idempotency decorator stores the response.
    view = OrderView.model_validate(order)
    return JSONResponse(
        content=view.model_dump(mode="json"),
        status_code=status.HTTP_201_CREATED,
    )


@router.get("/{order_id}", response_model=OrderView)
async def get_order(order_id: int, db: AsyncSessionDep) -> Order:
    order = await db.get(Order, order_id)
    if order is None:
        raise AppError("Order not found", code=1404, status_code=404)
    return order


@router.get("", response_model=list[OrderView])
async def list_orders(db: AsyncSessionDep, customer_id: str | None = None):
    query = select(Order).order_by(Order.id.desc()).limit(100)
    if customer_id:
        query = query.where(Order.customer_id == customer_id)
    return list((await db.scalars(query)).all())
