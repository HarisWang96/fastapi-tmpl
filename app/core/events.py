"""Optional async RabbitMQ transactional outbox for PostgreSQL services."""

import asyncio
import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import aio_pika
from sqlalchemy import select, update

from app.config import settings
from app.database import AsyncSessionLocal
from app.logger import logger
from app.models.platform import EventConsumed, OutboxEvent

_PENDING, _PUBLISHING, _PUBLISHED, _FAILED = range(4)
_handlers: dict[str, list[Callable[..., Any]]] = {}


def subscribe(topic: str):
    def decorate(handler: Callable[..., Any]):
        _handlers.setdefault(topic, []).append(handler)
        return handler

    return decorate


async def emit_event(
    session,
    topic: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, Any] | None = None,
) -> str:
    """Stage an event in the caller's AsyncSession transaction."""
    event_id = str(uuid.uuid4())
    session.add(
        OutboxEvent(
            event_id=event_id,
            topic=topic,
            payload=payload,
            headers=headers or {},
            status=_PENDING,
            attempts=0,
            next_attempt_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
        )
    )
    return event_id


class EventRuntime:
    def __init__(
        self, connection, exchange, stop: asyncio.Event, tasks: list[asyncio.Task]
    ):
        self.connection, self.exchange, self.stop, self.tasks = (
            connection,
            exchange,
            stop,
            tasks,
        )
        self.connected = True


async def _relay(runtime: EventRuntime) -> None:
    while not runtime.stop.is_set():
        async with AsyncSessionLocal() as session, session.begin():
            rows = (
                await session.scalars(
                    select(OutboxEvent)
                    .where(
                        OutboxEvent.status.in_((_PENDING, _FAILED, _PUBLISHING)),
                        OutboxEvent.attempts < settings.OUTBOX_MAX_ATTEMPTS,
                        OutboxEvent.next_attempt_at <= datetime.now(UTC),
                        (OutboxEvent.locked_until.is_(None))
                        | (OutboxEvent.locked_until <= datetime.now(UTC)),
                    )
                    .order_by(OutboxEvent.id)
                    .limit(100)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            for row in rows:
                row.status = _PUBLISHING
                row.locked_until = datetime.now(UTC) + timedelta(
                    seconds=settings.OUTBOX_LEASE_SECONDS
                )
        if not rows:
            try:
                await asyncio.wait_for(
                    runtime.stop.wait(), settings.OUTBOX_POLL_INTERVAL_SECONDS
                )
            except TimeoutError:
                pass
            continue
        for row in rows:
            try:
                message = aio_pika.Message(
                    body=json.dumps(
                        row.payload, ensure_ascii=False, default=str
                    ).encode(),
                    content_type="application/json",
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                    message_id=row.event_id,
                    headers=row.headers or {},
                )
                await runtime.exchange.publish(message, routing_key=row.topic)
            except Exception as exc:  # noqa: BLE001 - broker failures must be persisted for retry
                status, attempts, error = _FAILED, row.attempts + 1, str(exc)[:1000]
            else:
                status, attempts, error = _PUBLISHED, row.attempts, None
            async with AsyncSessionLocal() as session:
                await session.execute(
                    update(OutboxEvent)
                    .where(OutboxEvent.id == row.id)
                    .values(
                        status=status,
                        attempts=attempts,
                        last_error=error,
                        locked_until=None,
                        published_at=datetime.now(UTC)
                        if status == _PUBLISHED
                        else None,
                        next_attempt_at=datetime.now(UTC)
                        + timedelta(seconds=min(300, 2 ** min(attempts, 8))),
                    )
                )
                await session.commit()


async def _consume(runtime: EventRuntime, queue_name: str) -> None:
    channel = await runtime.connection.channel()
    await channel.set_qos(prefetch_count=10)
    queue = await channel.declare_queue(queue_name, durable=True)
    for topic in _handlers:
        await queue.bind(runtime.exchange, routing_key=topic)
    async with queue.iterator() as iterator:
        async for message in iterator:
            if runtime.stop.is_set():
                return
            event_id = message.message_id or ""
            try:
                payload = json.loads(message.body)
                if not event_id or not isinstance(payload, dict):
                    raise ValueError("invalid event")
                async with AsyncSessionLocal() as session:
                    duplicate = await session.scalar(
                        select(EventConsumed.id).where(
                            EventConsumed.event_id == event_id
                        )
                    )
                if duplicate:
                    await message.ack()
                    continue
                for handler in _handlers.get(message.routing_key or "", []):
                    result = handler(payload, dict(message.headers or {}))
                    if asyncio.iscoroutine(result):
                        await result
                async with AsyncSessionLocal() as session:
                    session.add(
                        EventConsumed(
                            event_id=event_id,
                            topic=message.routing_key or "",
                            consumed_at=datetime.now(UTC),
                        )
                    )
                    await session.commit()
                await message.ack()
            except Exception:  # noqa: BLE001 - handler failures nack the message for retry
                logger.exception("event handler failed; message will be retried")
                await message.nack(requeue=True)


async def start_event_bus() -> EventRuntime | None:
    if not settings.EVENT_ENABLED:
        return None
    assert settings.EVENT_BROKER_URL is not None
    connection = await aio_pika.connect_robust(
        settings.EVENT_BROKER_URL.get_secret_value()
    )
    channel = await connection.channel(publisher_confirms=True)
    exchange = await channel.declare_exchange(
        settings.EVENT_EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True
    )
    stop = asyncio.Event()
    runtime = EventRuntime(connection, exchange, stop, [])
    runtime.tasks.append(asyncio.create_task(_relay(runtime)))
    if _handlers:
        queue = settings.EVENT_QUEUE or f"{settings.APP_NAME}.events"
        runtime.tasks.append(asyncio.create_task(_consume(runtime, queue)))
    return runtime


async def close_event_bus(runtime: EventRuntime | None) -> None:
    if runtime is None:
        return
    runtime.stop.set()
    for task in runtime.tasks:
        task.cancel()
    await asyncio.gather(*runtime.tasks, return_exceptions=True)
    await runtime.connection.close()
