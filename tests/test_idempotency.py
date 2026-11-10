"""Idempotency store and decorator behavior (SQLite, no MySQL required)."""

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.exceptions import BadRequestError, ConflictError, register_exception_handlers
from app.core.idempotency import IdempotencyStore, idempotent
from app.core.schemas.common import ApiResponse, success
from app.models.base import Base


@pytest.fixture()
def store() -> IdempotencyStore:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return IdempotencyStore(factory, ttl_seconds=3600)


def test_first_begin_claims_and_complete_replays(store: IdempotencyStore):
    assert store.begin("sys:1:POST:/orders", "k1", "hash-a") is None
    store.complete("sys:1:POST:/orders", "k1", 200, {"code": 200, "data": {"id": 1}})

    replay = store.begin("sys:1:POST:/orders", "k1", "hash-a")

    assert replay is not None
    assert replay.status_code == 200
    assert replay.body == {"code": 200, "data": {"id": 1}}


def test_same_key_different_body_conflicts(store: IdempotencyStore):
    store.begin("sys:1:POST:/orders", "k1", "hash-a")

    with pytest.raises(ConflictError):
        store.begin("sys:1:POST:/orders", "k1", "hash-b")


def test_in_progress_duplicate_conflicts(store: IdempotencyStore):
    store.begin("sys:1:POST:/orders", "k1", "hash-a")

    with pytest.raises(ConflictError):
        store.begin("sys:1:POST:/orders", "k1", "hash-a")


def test_abort_removes_claim(store: IdempotencyStore):
    store.begin("sys:1:POST:/orders", "k1", "hash-a")
    store.abort("sys:1:POST:/orders", "k1")

    assert store.begin("sys:1:POST:/orders", "k1", "hash-a") is None


def test_scope_isolates_callers(store: IdempotencyStore):
    store.begin("sys:1:POST:/orders", "k1", "hash-a")
    store.complete("sys:1:POST:/orders", "k1", 200, {"ok": True})

    assert store.begin("sys:2:POST:/orders", "k1", "hash-a") is None


def test_decorator_replays_without_reexecuting(store: IdempotencyStore):
    calls = {"n": 0}

    app = FastAPI()
    register_exception_handlers(app)

    @app.post("/write", response_model=ApiResponse[dict[str, int]])
    @idempotent(required=True, store_factory=lambda: store)
    def write(request: Request) -> ApiResponse[dict[str, int]]:
        calls["n"] += 1
        return success({"n": calls["n"]})

    with TestClient(app) as client:
        headers = {"Idempotency-Key": "key-1"}
        first = client.post("/write", headers=headers)
        second = client.post("/write", headers=headers)
        other = client.post("/write", headers={"Idempotency-Key": "key-2"})
        missing = client.post("/write")
        different_body = client.post(
            "/write",
            headers={**headers, "Content-Type": "application/json"},
            content=b'{"x":1}',
        )

    assert first.status_code == 200
    assert second.json() == first.json()
    assert other.json()["data"]["n"] == 2
    assert calls["n"] == 2
    assert missing.status_code == 400
    assert different_body.status_code == 409


def test_decorator_allows_missing_key_when_optional(store: IdempotencyStore):
    app = FastAPI()
    register_exception_handlers(app)
    calls = {"n": 0}

    @app.post("/write", response_model=ApiResponse[dict[str, int]])
    @idempotent(store_factory=lambda: store)
    def write(request: Request) -> ApiResponse[dict[str, int]]:
        calls["n"] += 1
        return success({"n": calls["n"]})

    with TestClient(app) as client:
        client.post("/write")
        client.post("/write")

    assert calls["n"] == 2


def test_decorator_replays_response_body_status_and_headers(store: IdempotencyStore):
    calls = {"n": 0}
    app = FastAPI()

    @app.post("/response")
    @idempotent(required=True, store_factory=lambda: store)
    def write(request: Request):
        calls["n"] += 1
        return JSONResponse(
            status_code=201,
            content={"created": calls["n"]},
            headers={"Location": "/orders/1"},
        )

    with TestClient(app) as client:
        headers = {"Idempotency-Key": "response-key"}
        first = client.post("/response", headers=headers)
        replay = client.post("/response", headers=headers)

    assert first.status_code == replay.status_code == 201
    assert first.json() == replay.json() == {"created": 1}
    assert replay.headers["location"] == "/orders/1"
    assert calls["n"] == 1


def test_decorator_replays_declared_status_for_plain_result(store: IdempotencyStore):
    app = FastAPI()

    @app.post("/created", status_code=201)
    @idempotent(required=True, status_code=201, store_factory=lambda: store)
    def write(request: Request):
        return {"created": True}

    with TestClient(app) as client:
        headers = {"Idempotency-Key": "created-key"}
        first = client.post("/created", headers=headers)
        replay = client.post("/created", headers=headers)

    assert first.status_code == replay.status_code == 201
    assert first.json() == replay.json() == {"created": True}


def test_required_missing_key_raises_bad_request():
    with pytest.raises(BadRequestError):
        # Direct call bypasses FastAPI but exercises the same guard.
        @idempotent(required=True)
        def handler(request: Request):  # pragma: no cover - not called
            return None

        import asyncio

        from starlette.requests import Request as StarletteRequest

        scope = {"type": "http", "method": "POST", "path": "/x", "headers": []}
        asyncio.run(handler(StarletteRequest(scope)))
