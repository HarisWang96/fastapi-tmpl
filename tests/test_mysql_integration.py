"""Real MySQL integration tests, skipped by default.

Run with RUN_MYSQL_TESTS=1 and MYSQL_DATABASES.default configured. Unit tests
cover SQL shape (tests/test_repository.py); this verifies actual driver execution.
PyMySQL format parameters require literal percent signs to be doubled.
"""

import os

import pytest

from app.core.config import settings

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_MYSQL_TESTS") != "1" or "default" not in settings.MYSQL_DATABASES,
    reason="需要 RUN_MYSQL_TESTS=1 且 MYSQL_DATABASES 配置 default",
)


def test_driver_accepts_doubled_percent_and_binds_params():
    from app.core.db.mysql import mysql_pool

    conn = mysql_pool.connection("default")
    try:
        rows = conn.get_all(
            "SELECT DATE_FORMAT(NOW(), '%%Y') AS y, %s AS v WHERE %s = %s",
            ("ok", 1, 1),
        )
    finally:
        conn.close()

    assert rows[0]["v"] == "ok"
    assert len(rows[0]["y"]) == 4
    assert rows[0]["y"].isdigit()
