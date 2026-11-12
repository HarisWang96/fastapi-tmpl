"""Database-backed business-flow tests (run with ``pytest -m integration``)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.core import idempotency
from app.core.events import _PENDING
from app.database import AsyncSessionLocal, engine
from app.main import app
from app.models.order import Order
from app.models.platform import IdempotencyRecord, OutboxEvent

pytestmark = pytest.mark.integration


def test_create_order_persists_order_outbox_and_replays_idempotently():
    key = "integration-order-create"
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/orders",
            headers={"Idempotency-Key": key},
            json={"customer_id": "customer-1", "sku": "sku-1", "quantity": 2},
        )
        assert response.status_code == 201
        order_id = response.json()["id"]
        replay = client.post(
            "/api/v1/orders",
            headers={"Idempotency-Key": key},
            json={"customer_id": "customer-1", "sku": "sku-1", "quantity": 2},
        )
        assert replay.status_code == 201
        assert replay.json() == response.json()

    import asyncio

    async def verify_and_cleanup():
        try:
            async with AsyncSessionLocal() as session, session.begin():
                order = await session.get(Order, order_id)
                event = await session.scalar(
                    select(OutboxEvent).where(
                        OutboxEvent.payload["order_id"].as_integer() == order_id
                    )
                )
                assert order is not None
                assert event is not None and event.status == _PENDING
                assert event.payload["order_id"] == order_id
                await session.execute(delete(Order).where(Order.id == order_id))
                await session.execute(
                    delete(OutboxEvent).where(OutboxEvent.id == event.id)
                )
                await session.execute(
                    delete(IdempotencyRecord).where(IdempotencyRecord.idem_key == key)
                )
        finally:
            await engine.dispose()

    asyncio.run(verify_and_cleanup())


def test_business_write_and_idempotency_record_roll_back_together(monkeypatch):
    key = "integration-order-atomic-rollback"

    def fail_after_business_handler(_result):
        raise RuntimeError("simulated failure before idempotency completion")

    monkeypatch.setattr(idempotency, "_pack", fail_after_business_handler)
    with TestClient(app, raise_server_exceptions=False) as client:
        failed = client.post(
            "/api/v1/orders",
            headers={"Idempotency-Key": key},
            json={"customer_id": "customer-atomic", "sku": "sku-atomic", "quantity": 1},
        )
        assert failed.status_code == 500

    monkeypatch.undo()

    import asyncio

    async def assert_failure_left_no_rows():
        try:
            async with AsyncSessionLocal() as session:
                assert (
                    await session.scalar(
                        select(Order.id).where(Order.customer_id == "customer-atomic")
                    )
                    is None
                )
                assert (
                    await session.scalar(
                        select(IdempotencyRecord.id).where(
                            IdempotencyRecord.idem_key == key
                        )
                    )
                    is None
                )
                assert (
                    await session.scalar(
                        select(OutboxEvent.id).where(
                            OutboxEvent.payload["customer_id"].as_string()
                            == "customer-atomic"
                        )
                    )
                    is None
                )
        finally:
            await engine.dispose()

    asyncio.run(assert_failure_left_no_rows())

    with TestClient(app) as client:
        succeeded = client.post(
            "/api/v1/orders",
            headers={"Idempotency-Key": key},
            json={"customer_id": "customer-atomic", "sku": "sku-atomic", "quantity": 1},
        )
        assert succeeded.status_code == 201

    async def cleanup():
        try:
            async with AsyncSessionLocal() as session, session.begin():
                await session.execute(
                    delete(Order).where(Order.customer_id == "customer-atomic")
                )
                await session.execute(
                    delete(OutboxEvent).where(
                        OutboxEvent.payload["customer_id"].as_string()
                        == "customer-atomic"
                    )
                )
                await session.execute(
                    delete(IdempotencyRecord).where(IdempotencyRecord.idem_key == key)
                )
        finally:
            await engine.dispose()

    asyncio.run(cleanup())
