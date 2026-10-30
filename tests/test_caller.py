"""Gateway identity headers are read downstream without parsing JWTs."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_production_requires_proxy_token():
    with pytest.raises(ValidationError, match="TRUSTED_PROXY_TOKEN"):
        Settings(APP_ENV="prod")


def test_non_production_allows_missing_proxy_token():
    config = Settings(APP_ENV="test")
    assert config.TRUSTED_PROXY_TOKEN is None


def test_me_without_header_is_401(client):
    response = client.get("/api/v1/demo/me")
    assert response.status_code == 401
    body = response.json()
    assert body["code"] == 1401
    assert body["message"] == "缺少网关身份头 X-User-Id"


def test_me_with_header_returns_caller(client):
    response = client.get(
        "/api/v1/demo/me",
        headers={"X-User-Id": "42", "X-App-Id": "bi"},
    )
    assert response.status_code == 200
    assert response.json()["data"] == {"user_id": 42, "app_id": "bi"}


def test_me_with_invalid_user_id_is_401(client):
    response = client.get("/api/v1/demo/me", headers={"X-User-Id": "not-a-number"})
    assert response.status_code == 401
    assert response.json()["message"] == "X-User-Id 非法"


def test_whoami_is_public(client):
    response = client.get("/api/v1/demo/whoami")
    assert response.status_code == 200
    assert response.json()["data"] == {"user_id": None, "app_id": None}
