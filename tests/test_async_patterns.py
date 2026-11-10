"""Database-independent checks for async idempotency/outbox conventions."""

from datetime import UTC, datetime

from fastapi import Response

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
