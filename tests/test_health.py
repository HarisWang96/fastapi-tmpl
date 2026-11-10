"""Liveness checks the process; readiness and health check configured dependencies."""


def test_livez_ok(client):
    response = client.get("/livez")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_degrades_when_dependencies_missing(client):
    # MySQL and Redis are not configured in tests; probes should return 503, not raise.
    response = client.get("/readyz")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["dependencies"]["mysql"]["status"] == "down"
    assert body["dependencies"]["redis"]["status"] == "down"


def test_healthz_includes_service_identity(client):
    response = client.get("/healthz")
    assert response.status_code == 503
    body = response.json()
    assert body["service"]
    assert body["version"]


def test_readyz_only_checks_configured_dependencies(client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "READINESS_DEPENDENCIES", ["redis"])
    response = client.get("/readyz")

    assert response.status_code == 503
    assert set(response.json()["dependencies"]) == {"redis"}


def test_readyz_is_healthy_without_hard_dependencies(client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "READINESS_DEPENDENCIES", [])
    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "dependencies": {}}


def test_readyz_checks_rabbitmq_when_events_are_enabled(client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "READINESS_DEPENDENCIES", [])
    monkeypatch.setattr(settings, "EVENT_ENABLED", True)
    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["dependencies"]["rabbitmq"]["status"] == "down"
