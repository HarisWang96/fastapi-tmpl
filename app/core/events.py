"""Transactional outbox and RabbitMQ event bus.

`emit_event(session, ...)` writes an outbox row inside the caller's business
transaction, so the state change and the event are committed atomically.
A background relay publishes pending rows to a topic exchange; consumers declare
one durable queue per service, bind the topics they subscribe to, and dedupe by
event_id after the handler succeeds (at-least-once delivery).

Usage:
    emit_event(session, "order.created", {"order_id": 1})

    @subscribe("order.created")
    def on_order_created(payload, headers): ...

Handlers may be sync or async. A handler that fails after partial side effects
must be idempotent, because delivery is at-least-once.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import aio_pika
import aio_pika.abc
from prometheus_client import Counter
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.clock import now
from app.core.config import settings
from app.core.db.orm import get_session_factory
from app.core.logger import logger
from app.models.platform import EventConsumed, OutboxEvent

PENDING = 0
PUBLISHING = 1
PUBLISHED = 2
FAILED = 3

Handler = Callable[[dict[str, Any], dict[str, Any]], Any]

_subscriptions: dict[str, list[Handler]] = {}


def subscribe(topic: str) -> Callable[[Handler], Handler]:
    """Register a handler for a routing key. Bind happens when the consumer starts."""

    def decorator(func: Handler) -> Handler:
        _subscriptions.setdefault(topic, []).append(func)
        return func

    return decorator


def emit_event(
    session: Session,
    topic: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, Any] | None = None,
    event_id: str | None = None,
) -> str:
    """Add an outbox row to the caller's transaction; the caller must commit."""
    eid = event_id or str(uuid.uuid4())
    session.add(
        OutboxEvent(
            event_id=eid,
            topic=topic,
            payload=payload,
            headers=headers or {},
            status=PENDING,
            next_attempt_at=now(),
        )
    )
    return eid


class OutboxStore:
    """Claim/mark operations for the relay; the row is the unit of work."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._factory = session_factory

    @property
    def factory(self) -> sessionmaker[Session]:
        return self._factory

    def claim(self, limit: int, lease_seconds: int, max_attempts: int) -> list[dict[str, Any]]:
        current = now()
        with self._factory() as session:
            ids = session.scalars(
                select(OutboxEvent.id)
                .where(
                    OutboxEvent.status.in_((PENDING, PUBLISHING, FAILED)),
                    OutboxEvent.attempts < max_attempts,
                    OutboxEvent.next_attempt_at <= current,
                    (OutboxEvent.locked_until.is_(None)) | (OutboxEvent.locked_until < current),
                )
                .order_by(OutboxEvent.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            ).all()
            if not ids:
                return []
            session.execute(
                update(OutboxEvent)
                .where(OutboxEvent.id.in_(ids))
                .values(status=PUBLISHING, locked_until=current + timedelta(seconds=lease_seconds))
            )
            session.commit()
            rows = session.scalars(select(OutboxEvent).where(OutboxEvent.id.in_(ids))).all()
            return [
                {
                    "id": row.id,
                    "event_id": row.event_id,
                    "topic": row.topic,
                    "payload": row.payload,
                    "headers": row.headers or {},
                    "attempts": row.attempts,
                }
                for row in rows
            ]

    def mark_published(self, row_id: int) -> None:
        with self._factory() as session:
            session.execute(
                update(OutboxEvent)
                .where(OutboxEvent.id == row_id)
                .values(status=PUBLISHED, published_at=now(), locked_until=None, last_error=None)
            )
            session.commit()

    def mark_failed(self, row_id: int, error: str) -> None:
        with self._factory() as session:
            row = session.get(OutboxEvent, row_id)
            if row is None:
                return
            row.attempts += 1
            row.status = FAILED
            row.locked_until = None
            row.last_error = error[:1000]
            backoff = min(60, 2 ** min(row.attempts, 6))
            row.next_attempt_at = now() + timedelta(seconds=backoff)
            session.commit()

    def mark_consumed(self, event_id: str, topic: str) -> bool:
        """Return True when this is the first successful consumption."""
        with self._factory() as session:
            session.add(EventConsumed(event_id=event_id, topic=topic))
            try:
                session.commit()
                return True
            except IntegrityError:
                session.rollback()
                return False

    def is_consumed(self, event_id: str) -> bool:
        with self._factory() as session:
            return (
                session.scalar(select(EventConsumed.id).where(EventConsumed.event_id == event_id))
                is not None
            )

    def purge_consumed(self, retention_days: int) -> int:
        cutoff = now() - timedelta(days=retention_days)
        with self._factory() as session:
            ids = session.scalars(
                select(EventConsumed.id).where(EventConsumed.consumed_at < cutoff).limit(5000)
            ).all()
            if not ids:
                return 0
            session.execute(delete(EventConsumed).where(EventConsumed.id.in_(ids)))
            session.commit()
            return len(ids)


class RabbitPublisher:
    """Durable topic exchange publisher with confirms enabled."""

    def __init__(self, url: str, exchange: str, dlx_exchange: str) -> None:
        self._url = url
        self._exchange_name = exchange
        self._dlx_name = dlx_exchange
        self._connection: aio_pika.abc.AbstractRobustConnection | None = None
        self._exchange: aio_pika.abc.AbstractExchange | None = None
        self._dlx: aio_pika.abc.AbstractExchange | None = None

    async def connect(self) -> None:
        if self._connection is not None:
            return
        self._connection = await aio_pika.connect_robust(self._url)
        channel = await self._connection.channel(publisher_confirms=True)
        self._exchange = await channel.declare_exchange(
            self._exchange_name, aio_pika.ExchangeType.TOPIC, durable=True
        )
        self._dlx = await channel.declare_exchange(
            self._dlx_name, aio_pika.ExchangeType.TOPIC, durable=True
        )

    @property
    def connected(self) -> bool:
        return (
            self._connection is not None
            and not self._connection.is_closed
            and self._connection.connected.is_set()
        )

    async def ensure_connected(self) -> None:
        if not self.connected:
            self._connection = None
            await self.connect()

    async def publish(
        self,
        topic: str,
        payload: dict[str, Any],
        headers: dict[str, Any] | None = None,
        *,
        message_id: str | None = None,
        dead_letter: bool = False,
    ) -> None:
        exchange = self._dlx if dead_letter else self._exchange
        if exchange is None:
            raise RuntimeError("事件发布器尚未连接")
        message = aio_pika.Message(
            body=json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"),
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            message_id=message_id,
            headers=headers or {},
        )
        await exchange.publish(message, routing_key=topic)

    async def close(self) -> None:
        if self._connection is not None:
            await self._connection.close()
            self._connection = None


class OutboxRelay:
    def __init__(self, store: OutboxStore, publisher: RabbitPublisher) -> None:
        self._store = store
        self._publisher = publisher

    async def run(self, stop: asyncio.Event) -> None:
        interval = settings.OUTBOX_POLL_INTERVAL_SECONDS
        while not stop.is_set():
            try:
                count = await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("outbox relay 执行失败")
                count = 0
            if count == 0:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=interval)
                except TimeoutError:
                    pass

    async def run_once(self) -> int:
        await self._publisher.ensure_connected()
        rows = await asyncio.to_thread(
            self._store.claim,
            settings.OUTBOX_BATCH_SIZE,
            settings.OUTBOX_LEASE_SECONDS,
            settings.OUTBOX_MAX_ATTEMPTS,
        )
        for row in rows:
            try:
                await self._publisher.publish(
                    row["topic"],
                    row["payload"],
                    row["headers"],
                    message_id=row["event_id"],
                )
            except Exception as exc:
                logger.warning(f"outbox 发布失败 id={row['id']} topic={row['topic']}: {exc}")
                await asyncio.to_thread(self._store.mark_failed, row["id"], str(exc))
                _OUTBOX_EVENTS.labels(settings.APP_NAME, "failed").inc()
            else:
                await asyncio.to_thread(self._store.mark_published, row["id"])
                _OUTBOX_EVENTS.labels(settings.APP_NAME, "published").inc()
        return len(rows)


class RabbitConsumer:
    def __init__(
        self,
        url: str,
        queue: str,
        exchange: str,
        dlx_exchange: str,
        store: OutboxStore,
        publisher: RabbitPublisher,
    ) -> None:
        self._url = url
        self._queue_name = queue
        self._exchange_name = exchange
        self._dlx_name = dlx_exchange
        self._store = store
        self._publisher = publisher

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await self._consume(stop)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("事件消费者断开，5 秒后重连")
                try:
                    await asyncio.wait_for(stop.wait(), timeout=5)
                except TimeoutError:
                    pass

    async def _consume(self, stop: asyncio.Event) -> None:
        connection = await aio_pika.connect_robust(self._url)
        try:
            channel = await connection.channel()
            await channel.set_qos(prefetch_count=settings.CONSUMER_PREFETCH)
            dlx = await channel.declare_exchange(
                self._dlx_name, aio_pika.ExchangeType.TOPIC, durable=True
            )
            dlq = await channel.declare_queue(f"{self._queue_name}.dlq", durable=True)
            await dlq.bind(dlx, routing_key="#")
            exchange = await channel.declare_exchange(
                self._exchange_name, aio_pika.ExchangeType.TOPIC, durable=True
            )
            queue = await channel.declare_queue(self._queue_name, durable=True)
            for topic in _subscriptions:
                await queue.bind(exchange, routing_key=topic)
            logger.info(f"事件消费者就绪 queue={self._queue_name} topics={sorted(_subscriptions)}")
            async with queue.iterator() as messages:
                async for message in messages:
                    if stop.is_set():
                        return
                    await self._handle(message)
        finally:
            await connection.close()

    async def _handle(self, message: aio_pika.abc.AbstractIncomingMessage) -> None:
        topic = message.routing_key or ""
        try:
            payload = json.loads(message.body)
            if not isinstance(payload, dict):
                raise ValueError("payload 必须是 JSON 对象")
        except Exception as exc:
            logger.warning(f"丢弃无法解析的事件 topic={topic}: {exc}")
            await message.ack()
            _EVENTS_CONSUMED.labels(settings.APP_NAME, topic, "bad_message").inc()
            return

        event_id = message.message_id or str(payload.get("event_id") or "")
        if not event_id:
            logger.warning(f"丢弃缺少 event_id 的事件 topic={topic}")
            await message.ack()
            _EVENTS_CONSUMED.labels(settings.APP_NAME, topic, "bad_message").inc()
            return
        if await asyncio.to_thread(self._store.is_consumed, event_id):
            await message.ack()
            _EVENTS_CONSUMED.labels(settings.APP_NAME, topic, "duplicate").inc()
            return

        handlers = _subscriptions.get(topic, [])
        if not handlers:
            await message.ack()
            return
        headers = dict(message.headers or {})
        for attempt in range(settings.CONSUMER_MAX_RETRIES + 1):
            try:
                for handler in handlers:
                    if asyncio.iscoroutinefunction(handler):
                        await handler(payload, headers)
                    else:
                        await asyncio.to_thread(handler, payload, headers)
            except Exception as exc:
                if attempt >= settings.CONSUMER_MAX_RETRIES:
                    logger.exception(f"事件处理失败，转入死信 topic={topic} event_id={event_id}")
                    try:
                        await self._publisher.publish(
                            topic,
                            payload,
                            headers,
                            message_id=event_id,
                            dead_letter=True,
                        )
                    except Exception:
                        logger.exception("死信发布失败，消息重新入队")
                        await message.nack(requeue=True)
                    else:
                        await message.ack()
                    _EVENTS_CONSUMED.labels(settings.APP_NAME, topic, "failed").inc()
                    return
                logger.warning(
                    f"事件处理失败，重试 {attempt + 1}/{settings.CONSUMER_MAX_RETRIES} "
                    f"topic={topic}: {exc}"
                )
                await asyncio.sleep(settings.CONSUMER_RETRY_BACKOFF_SECONDS * (2**attempt))
            else:
                await asyncio.to_thread(self._store.mark_consumed, event_id, topic)
                await message.ack()
                _EVENTS_CONSUMED.labels(settings.APP_NAME, topic, "ok").inc()
                return


@dataclass
class EventRuntime:
    publisher: RabbitPublisher
    relay_task: asyncio.Task[None] | None
    consumer_task: asyncio.Task[None] | None
    stop: asyncio.Event


async def start_event_bus() -> EventRuntime | None:
    """Start relay and (when handlers exist) consumer. Returns None when disabled."""
    if not settings.EVENT_ENABLED:
        return None
    assert settings.EVENT_BROKER_URL is not None
    url = settings.EVENT_BROKER_URL.get_secret_value()
    publisher = RabbitPublisher(url, settings.EVENT_EXCHANGE, settings.EVENT_DLX_EXCHANGE)
    store = OutboxStore(get_session_factory())
    stop = asyncio.Event()
    relay_task = asyncio.create_task(OutboxRelay(store, publisher).run(stop))
    consumer_task = None
    if _subscriptions:
        queue = settings.EVENT_QUEUE or f"{settings.APP_NAME}.events"
        consumer = RabbitConsumer(
            url,
            queue,
            settings.EVENT_EXCHANGE,
            settings.EVENT_DLX_EXCHANGE,
            store,
            publisher,
        )
        consumer_task = asyncio.create_task(consumer.run(stop))
    logger.info(f"事件总线已启动 exchange={settings.EVENT_EXCHANGE}")
    return EventRuntime(publisher, relay_task, consumer_task, stop)


async def close_event_bus(runtime: EventRuntime | None) -> None:
    if runtime is None:
        return
    runtime.stop.set()
    for task in (runtime.relay_task, runtime.consumer_task):
        if task is not None:
            task.cancel()
    for task in (runtime.relay_task, runtime.consumer_task):
        if task is not None:
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
    await runtime.publisher.close()


_OUTBOX_EVENTS = Counter(
    "outbox_events_total",
    "outbox 发布结果",
    ["service", "outcome"],
)
_EVENTS_CONSUMED = Counter(
    "events_consumed_total",
    "事件消费结果",
    ["service", "topic", "outcome"],
)
