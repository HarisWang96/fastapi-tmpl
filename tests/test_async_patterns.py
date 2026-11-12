"""Database-independent checks for async idempotency/outbox conventions."""

import asyncio
from datetime import UTC, datetime

from fastapi import Response

from app.config import settings
from app.core.events import _retry_or_dead_letter
from app.core.idempotency import _pack, _replay
from app.models.platform import IdempotencyRecord


def test_idempotency_pack_and_replay_preserves_explicit_response():
    original = Response(
        content=b'{"created":true}',
        status_code=201,
        media_type="application/json",
        headers={"Location": "/orders/42", "X-Request-Id": "first"},
    )
    status, body, headers = _pack(original)
    record = IdempotencyRecord(
        scope="scope",
        idem_key="key",
        request_hash="hash",
        status=2,
        response_status=status,
        response_body=body,
        response_headers=headers,
        created_at=datetime.now(UTC),
        expires_at=datetime.now(UTC),
    )

    replay = _replay(record)

    assert replay.status_code == 201
    assert replay.body == b'{"created":true}'
    assert replay.headers["location"] == "/orders/42"
    assert "x-request-id" not in replay.headers


def test_idempotency_pack_plain_json_body():
    status, body, headers = _pack({"created": True})
    assert status == 200
    assert body["__idempotency_response_v1__"] == "json"
    assert body["body"] == {"created": True}
    assert headers == {}


def test_platform_metadata_uses_configured_postgres_schema():
    from app.config import settings
    from app.models.platform import Base

    assert Base.metadata.schema == settings.DATABASE_SCHEMA
    assert {table.name for table in Base.metadata.tables.values()} >= {
        "sys_idempotency",
        "sys_outbox",
        "sys_event_consumed",
    }


def test_event_failures_are_retried_then_sent_to_dead_letter(monkeypatch):
    class Exchange:
        def __init__(self):
            self.published = []

        async def publish(self, message, routing_key):
            self.published.append((message, routing_key))

    class Original:
        body = b'{"id": 1}'
        content_type = "application/json"
        content_encoding = None
        delivery_mode = None
        priority = None
        correlation_id = None
        reply_to = None
        expiration = None
        message_id = "event-1"
        timestamp = None
        type = None
        app_id = None
        routing_key = "order.created"

        def __init__(self):
            self.headers = {}
            self.acked = False
            self.nacked = False

        async def ack(self):
            self.acked = True

        async def nack(self, *, requeue):
            self.nacked = requeue

    async def run():
        monkeypatch.setattr(settings, "CONSUMER_MAX_RETRIES", 1)
        monkeypatch.setattr(settings, "CONSUMER_RETRY_BACKOFF_SECONDS", 0)
        normal, dead = Exchange(), Exchange()
        runtime = type(
            "Runtime", (), {"exchange": normal, "dead_letter_exchange": dead}
        )()
        original = Original()

        await _retry_or_dead_letter(runtime, None, original)
        assert original.acked
        retry, topic = normal.published[0]
        assert topic == "order.created"
        assert retry.headers["x-consumer-retries"] == 1

        second = Original()
        second.headers = retry.headers
        await _retry_or_dead_letter(runtime, None, second)
        assert second.acked
        assert dead.published[0][1] == "order.created"

    asyncio.run(run())
