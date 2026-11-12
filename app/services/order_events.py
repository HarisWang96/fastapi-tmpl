"""Example subscriber registered when the optional event bus is enabled."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import subscribe
from app.logger import logger


@subscribe("order.created")
async def on_order_created(
    session: AsyncSession, payload: dict[str, Any], headers: dict[str, Any]
) -> None:
    """Demonstrate a transactional event handler without owning its transaction."""
    logger.info("received order.created order_id={}", payload.get("order_id"))
