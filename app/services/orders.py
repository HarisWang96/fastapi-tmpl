"""Order application operations."""

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import emit_event
from app.models.order import Order
from app.schemas.orders import OrderCreate


async def create_order(session: AsyncSession, payload: OrderCreate) -> Order:
    order = Order(
        customer_id=payload.customer_id,
        sku=payload.sku,
        quantity=payload.quantity,
        status="created",
        created_at=datetime.now(UTC),
    )
    session.add(order)
    await session.flush()
    await emit_event(
        session,
        "order.created",
        {
            "order_id": order.id,
            "customer_id": order.customer_id,
            "sku": order.sku,
            "quantity": order.quantity,
        },
    )
    return order
