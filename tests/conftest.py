"""Global pytest configuration.

Environment variables must be set before importing app.* because settings is
a module-level singleton. setdefault preserves values explicitly set by CI or developers.
"""

import os

os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("LOG_TO_FILE", "false")
os.environ.setdefault("LOG_LEVEL", "WARNING")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client() -> TestClient:
    # Entering TestClient runs lifespan, covering startup and shutdown paths.
    with TestClient(app) as test_client:
        yield test_client
