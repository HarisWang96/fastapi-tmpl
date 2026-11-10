"""Service-side permission and data-scope enforcement."""

import asyncio

import httpx2
import pytest

from app.api.authz_deps import get_authz_client, reset_authz_cache
from app.clients.authz import AuthzClient, DataScope, Decision
from app.core.config import settings
from app.core.exceptions import ServiceUnavailableError
from app.main import app

HEADERS = {"X-User-Id": "42", "X-App-Id": "sys"}


class FakeAuthzClient:
    def __init__(self) -> None:
        self.check_calls = 0
        self.scope_calls = 0
        self.decision = Decision(allow=True, reason="OK", version=1)
        self.scope_value = DataScope(mode="ALL", dimension="dept", version=1)
        self.error: Exception | None = None

    async def check(self, **_kwargs) -> Decision:
        self.check_calls += 1
        if self.error is not None:
            raise self.error
        return self.decision

    async def scope(self, **_kwargs) -> DataScope:
        self.scope_calls += 1
        if self.error is not None:
            raise self.error
        return self.scope_value

    async def aclose(self) -> None:
        pass


@pytest.fixture
def fake_authz():
    fake = FakeAuthzClient()
    app.dependency_overrides[get_authz_client] = lambda: fake
    reset_authz_cache()
    yield fake
    app.dependency_overrides.pop(get_authz_client, None)
    reset_authz_cache()


def test_permission_allowed(client, fake_authz):
    response = client.get("/api/v1/demo/perm", headers=HEADERS)

    assert response.status_code == 200
    assert response.json()["data"] == {"user_id": 42, "perm": "demo:read"}
    assert fake_authz.check_calls == 1


def test_permission_denied_is_403(client, fake_authz):
    fake_authz.decision = Decision(allow=False, reason="NO_PERM", version=1)

    response = client.get("/api/v1/demo/perm", headers=HEADERS)

    assert response.status_code == 403
    assert response.json()["code"] == 1403


def test_permission_requires_app_id(client, fake_authz):
    response = client.get("/api/v1/demo/perm", headers={"X-User-Id": "42"})

    assert response.status_code == 401
    assert response.json()["message"] == "缺少网关身份头 X-App-Id"
    assert fake_authz.check_calls == 0


def test_permission_decisions_are_cached(client, fake_authz):
    client.get("/api/v1/demo/perm", headers=HEADERS)
    client.get("/api/v1/demo/perm", headers=HEADERS)

    assert fake_authz.check_calls == 1


def test_cache_can_be_disabled(client, fake_authz, monkeypatch):
    monkeypatch.setattr(settings, "AUTHZ_CACHE_TTL_SECONDS", 0)

    client.get("/api/v1/demo/perm", headers=HEADERS)
    client.get("/api/v1/demo/perm", headers=HEADERS)

    assert fake_authz.check_calls == 2


def test_permission_dependency_unavailable_is_503(client, fake_authz):
    fake_authz.error = ServiceUnavailableError("权限服务不可用")

    response = client.get("/api/v1/demo/perm", headers=HEADERS)

    assert response.status_code == 503
    assert response.json()["code"] == 1503


@pytest.mark.parametrize(
    ("scope", "expected_filter"),
    [
        (DataScope(mode="ALL", dimension="dept"), None),
        (DataScope(mode="IN", dimension="dept", values=[1, 2]), [1, 2]),
        (DataScope(mode="NONE", dimension="dept"), []),
    ],
)
def test_scope_filter_values(client, fake_authz, scope, expected_filter):
    fake_authz.scope_value = scope

    response = client.get("/api/v1/demo/scope", headers=HEADERS)

    assert response.status_code == 200
    assert response.json()["data"]["filter_values"] == expected_filter


def test_scope_requires_app_id(client, fake_authz):
    response = client.get("/api/v1/demo/scope", headers={"X-User-Id": "42"})

    assert response.status_code == 401
    assert fake_authz.scope_calls == 0


def test_client_parses_envelope():
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/authz/check"
        return httpx2.Response(
            200,
            json={
                "code": 200,
                "message": "success",
                "data": {"allow": True, "reason": "OK", "version": 3},
            },
        )

    authz = AuthzClient(
        base_url="http://authz-svc",
        internal_token="test-token",
        timeout=1,
        transport=httpx2.MockTransport(handler),
    )
    decision = asyncio.run(authz.check(user_id=1, app_id="sys", perm_code="demo:read"))
    asyncio.run(authz.aclose())

    assert decision == Decision(allow=True, reason="OK", version=3)


def test_client_maps_http_error_to_503():
    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(500, json={"code": 500, "message": "boom"})

    authz = AuthzClient(
        base_url="http://authz-svc",
        internal_token="test-token",
        timeout=1,
        transport=httpx2.MockTransport(handler),
    )
    with pytest.raises(ServiceUnavailableError):
        asyncio.run(authz.check(user_id=1, app_id="sys", perm_code="demo:read"))
    asyncio.run(authz.aclose())
