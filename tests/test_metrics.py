"""/metrics 暴露、令牌门禁与指标标签。"""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from prometheus_client import generate_latest
from pydantic import SecretStr, ValidationError

from app.core import metrics
from app.core.config import Settings, settings
from app.core.context import request_id_ctx
from app.core.logger import _patch_record
from app.main import create_app


def test_metrics_endpoint_serves_prometheus_text(monkeypatch):
    monkeypatch.setattr(settings, "METRICS_TOKEN", None)
    with TestClient(create_app()) as client:
        response = client.get("/metrics")
    assert response.status_code == 200
    assert "http_requests_total" in response.text


def test_metrics_endpoint_requires_token_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "METRICS_TOKEN", SecretStr("metrics-secret"))
    with TestClient(create_app()) as client:
        assert client.get("/metrics").status_code == 403
        assert client.get("/metrics", headers={"X-Metrics-Token": "wrong"}).status_code == 403
        response = client.get("/metrics", headers={"X-Metrics-Token": "metrics-secret"})
    assert response.status_code == 200


def test_production_requires_metrics_token():
    with pytest.raises(ValidationError, match="METRICS_TOKEN"):
        Settings(
            APP_ENV="prod",
            TRUSTED_PROXY_TOKEN="proxy-secret",
            INTERNAL_API_TOKEN="internal-secret",
        )

    configured = Settings(
        APP_ENV="prod",
        TRUSTED_PROXY_TOKEN="proxy-secret",
        INTERNAL_API_TOKEN="internal-secret",
        METRICS_TOKEN="metrics-secret",
    )
    assert configured.METRICS_TOKEN.get_secret_value() == "metrics-secret"


def test_observe_http_skips_the_metrics_endpoint_itself():
    metrics.observe_http(method="GET", path="/metrics", status=200, seconds=0.001)
    text = generate_latest().decode()

    assert 'path="/metrics"' not in text


def test_observe_http_labels_the_route_template():
    metrics.observe_http(method="GET", path="/users/{user_id}", status=200, seconds=0.002)
    text = generate_latest().decode()

    assert 'path="/users/{user_id}"' in text
    assert f'service="{settings.APP_NAME}"' in text


def test_patch_record_adds_service_and_request_id():
    record = {"time": datetime.now(UTC), "extra": {}}
    token = request_id_ctx.set("rid-test")
    try:
        _patch_record(record)
    finally:
        request_id_ctx.reset(token)

    assert record["extra"]["service"] == settings.APP_NAME
    assert record["extra"]["request_id"] == "rid-test"
