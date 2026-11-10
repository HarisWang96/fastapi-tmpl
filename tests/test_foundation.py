"""Request context, errors, metrics, authz and config foundation behavior."""

import asyncio

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from app.clients.authz import AuthzClient, DataScope, Decision
from app.config import Settings, settings
from app.core.metrics import observe_http


def test_request_id_is_validated_and_returned(client):
    response = client.get("/livez", headers={"X-Request-Id": "test:request-1"})
    assert response.headers["x-request-id"] == "test:request-1"
    generated = client.get("/livez", headers={"X-Request-Id": "bad id"})
    assert generated.headers["x-request-id"] != "bad id"


def test_error_envelope_and_validation_details_are_hidden(client):
    response = client.get("/api/v1/demo/hello/" + "x" * 60)
    assert response.status_code == 422
    assert set(response.json()) == {"code", "message", "detail", "timestamp"}
    assert response.json()["detail"] is None


def test_metrics_endpoint_and_token_gate(client, monkeypatch):
    monkeypatch.setattr(settings, "METRICS_TOKEN", SecretStr("secret"))
    assert client.get("/metrics").status_code == 403
    assert (
        client.get("/metrics", headers={"X-Metrics-Token": "secret"}).status_code == 200
    )


def test_metrics_route_labels_use_route_template():
    observe_http("GET", "/users/{user_id}", 200, 0.001)


def test_production_configuration_requires_secrets():
    with pytest.raises(ValidationError, match="METRICS_TOKEN"):
        Settings(
            APP_ENV="prod",
            DATABASE_URL="postgresql+asyncpg://u:p@localhost/db",
            REDIS_URL="redis://localhost",
        )


def test_invalid_timezone_is_rejected():
    with pytest.raises(ValidationError, match="TIMEZONE"):
        Settings(
            APP_ENV="test",
            DATABASE_URL="postgresql+asyncpg://u:p@localhost/db",
            REDIS_URL="redis://localhost",
            TIMEZONE="Not/A-Timezone",
        )


def test_authz_client_parses_decision_and_scope():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/check"):
            return httpx.Response(
                200,
                json={
                    "code": 200,
                    "data": {"allow": True, "reason": "GRANTED", "version": 2},
                },
            )
        return httpx.Response(
            200,
            json={
                "code": 200,
                "data": {"mode": "IN", "dimension": "store", "values": [1, 2]},
            },
        )

    async def run():
        client = AuthzClient("http://authz", "token")
        await client._client.aclose()
        client._client = httpx.AsyncClient(
            base_url="http://authz", transport=httpx.MockTransport(handler)
        )
        decision = await client.check(user_id=7, app_id="admin", perm_code="store:read")
        scope = await client.scope(
            user_id=7, app_id="admin", resource_key="store", dimension="store"
        )
        await client.aclose()
        return decision, scope

    decision, scope = asyncio.run(run())
    assert decision == Decision(allow=True, reason="GRANTED", version=2)
    assert scope.filter_values() == [1, 2]


def test_authz_client_fails_closed_on_invalid_response():
    async def run():
        client = AuthzClient("http://authz", "token")
        await client._client.aclose()
        client._client = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(503))
        )
        with pytest.raises(Exception, match="Authorization service unavailable"):
            await client.check(user_id=1, app_id="app", perm_code="x")
        await client.aclose()

    asyncio.run(run())


def test_data_scope_all_none_semantics():
    assert DataScope(mode="ALL", dimension="dept").filter_values() is None
    assert DataScope(mode="NONE", dimension="dept").filter_values() == []
