"""Outbox store, relay and consumer dedupe/retry behavior (SQLite, no broker)."""

import asyncio
import json

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import events
from app.core.config import settings
from app.core.events import OutboxRelay, OutboxStore, RabbitConsumer, emit_event
from app.models.base import Base
from app.models.platform import OutboxEvent


@pytest.fixture()
def store() -> OutboxStore:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return OutboxStore(factory)


def _factory(store: OutboxStore) -> sessionmaker:
    return store.factory


class FakePublisher:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.published: list[dict] = []

    async def ensure_connected(self) -> None:
        return None

    async def publish(self, topic, payload, headers=None, *, message_id=None, dead_letter=False):
        if self.fail:
            raise RuntimeError("broker down")
        self.published.append(
            {
                "topic": topic,
                "payload": payload,
                "headers": headers,
                "message_id": message_id,
                "dead_letter": dead_letter,
            }
        )


def test_emit_event_joins_callers_transaction(store: OutboxStore):
    factory = _factory(store)
    with factory() as session:
        event_id = emit_event(session, "order.created", {"order_id": 7})
        session.commit()

    with factory() as session:
        row = session.scalar(select(OutboxEvent))
    assert row.event_id == event_id
    assert row.topic == "order.created"
    assert row.payload == {"order_id": 7}
    assert row.status == events.PENDING


def test_relay_publishes_and_marks_published(store: OutboxStore):
    factory = _factory(store)
    with factory() as session:
        emit_event(session, "order.created", {"order_id": 7})
        session.commit()

    publisher = FakePublisher()
    published = asyncio.run(OutboxRelay(store, publisher).run_once())

    assert published == 1
    assert publisher.published[0]["topic"] == "order.created"
    assert publisher.published[0]["message_id"]
    with factory() as session:
        row = session.scalar(select(OutboxEvent))
    assert row.status == events.PUBLISHED
    assert row.published_at is not None


def test_relay_marks_failed_for_retry(store: OutboxStore):
    factory = _factory(store)
    with factory() as session:
        emit_event(session, "order.created", {"order_id": 7})
        session.commit()

    publisher = FakePublisher(fail=True)
    assert asyncio.run(OutboxRelay(store, publisher).run_once()) == 1
    with factory() as session:
        row = session.scalar(select(OutboxEvent))
    assert row.status == events.FAILED
    assert row.attempts == 1
    assert "broker down" in row.last_error


def test_consumer_dedupes_after_success(store: OutboxStore, monkeypatch):
    calls: list[dict] = []

    @events.subscribe("test.topic")
    def handler(payload, headers):
        calls.append(payload)

    monkeypatch.setattr(settings, "CONSUMER_MAX_RETRIES", 0)
    consumer = RabbitConsumer("amqp://unused", "q", "ex", "dlx", store, FakePublisher())
    message = FakeMessage()

    try:
        asyncio.run(consumer._handle(message))
        assert message.acked is True
        assert calls == [{"a": 1}]

        duplicate = FakeMessage()
        asyncio.run(consumer._handle(duplicate))
        assert duplicate.acked is True
        assert calls == [{"a": 1}]
    finally:
        events._subscriptions.clear()


def test_consumer_moves_poison_message_to_dlq(store: OutboxStore, monkeypatch):
    @events.subscribe("test.topic")
    def handler(payload, headers):
        raise RuntimeError("boom")

    monkeypatch.setattr(settings, "CONSUMER_MAX_RETRIES", 0)
    publisher = FakePublisher()
    consumer = RabbitConsumer("amqp://unused", "q", "ex", "dlx", store, publisher)
    message = FakeMessage()

    try:
        asyncio.run(consumer._handle(message))
    finally:
        events._subscriptions.clear()

    assert message.acked is True
    assert publisher.published[0]["dead_letter"] is True
    assert publisher.published[0]["message_id"] == message.message_id


class FakeMessage:
    routing_key = "test.topic"
    message_id = "evt-1"
    headers: dict = {}
    body = json.dumps({"a": 1}).encode()

    def __init__(self) -> None:
        self.acked = False
        self.nacked = False

    async def ack(self) -> None:
        self.acked = True

    async def nack(self, requeue: bool = False) -> None:
        self.nacked = True
