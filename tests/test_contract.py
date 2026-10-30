"""Success and error responses use one envelope; the framework does not contain JWT code."""


def test_success_envelope_keys(client):
    body = client.get("/api/v1/demo/ping").json()
    assert set(body) == {"code", "message", "data", "timestamp"}
    assert body["code"] == 200
    assert body["data"] == {"pong": True}


def test_validation_error_envelope(client):
    response = client.get("/api/v1/demo/echo")
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == 422
    assert set(body) == {"code", "message", "detail", "timestamp"}


def test_not_found_envelope(client):
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    assert response.json()["code"] == 404


def test_openapi_has_business_paths_and_no_auth_scheme(client):
    schema = client.get("/openapi.json").json()
    assert "/api/v1/example/users" in schema["paths"]
    # The framework does not parse JWTs, so OpenAPI should not declare security schemes.
    assert "securitySchemes" not in schema.get("components", {})
    assert not any(
        "security" in operation for path in schema["paths"].values() for operation in path.values()
    )
