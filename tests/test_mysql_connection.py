"""Connection-layer tests for PyMySQL format parameter handling; no database required."""

import pytest

import app.core.db.orm as orm_module
from app.core.config import MysqlConfig
from app.core.db.mysql import MysqlConnection, _ensure_percent_escaped


class _ExplodingEngine:
    """Raise on connection to prove validation happens before connecting."""

    def connect(self):
        raise RuntimeError("不应该建连")


def _connection() -> MysqlConnection:
    return MysqlConnection(lambda: _ExplodingEngine())


def test_escaped_percent_and_placeholder_are_accepted():
    _ensure_percent_escaped("SELECT DATE_FORMAT(NOW(), '%%Y') AS y WHERE %s = %s")


def test_doubled_percent_with_params_passes_guard_then_tries_to_connect():
    with pytest.raises(RuntimeError, match="不应该建连"):
        _connection().get_all("SELECT DATE_FORMAT(NOW(), '%%Y') AS y WHERE %s = 1", (1,))


def test_bare_percent_is_rejected_with_actionable_message():
    with pytest.raises(ValueError, match=r"%%") as excinfo:
        _ensure_percent_escaped("SELECT DATE_FORMAT(NOW(), '%Y') AS y WHERE %s = %s")
    assert "DATE_FORMAT" in str(excinfo.value)


def test_get_all_rejects_bare_percent_before_connecting():
    with pytest.raises(ValueError, match=r"%%"):
        _connection().get_all("SELECT DATE_FORMAT(NOW(), '%Y') AS y WHERE %s = 1", (1,))


def test_get_all_allows_bare_percent_without_params():
    # PyMySQL interpolates percent sequences only when parameters are supplied.
    with pytest.raises(RuntimeError, match="不应该建连"):
        _connection().get_all("SELECT DATE_FORMAT(NOW(), '%Y') AS y")


def test_execute_many_rejects_bare_percent_before_connecting():
    with pytest.raises(ValueError, match=r"%%"):
        _connection().execute_many("INSERT INTO t VALUES ('100%', %s)", [(1,)])


def test_execute_many_with_empty_sequence_returns_zero_without_connecting():
    assert _connection().execute_many("INSERT INTO t VALUES (%s)", []) == 0


def test_engine_passes_driver_connect_and_socket_timeouts(monkeypatch):
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        orm_module.settings,
        "MYSQL_DATABASES",
        {"default": MysqlConfig(host="localhost", user="user", password="secret", database="app")},
    )
    monkeypatch.setattr(orm_module.settings, "MYSQL_CONNECT_TIMEOUT", 4)
    monkeypatch.setattr(orm_module.settings, "MYSQL_READ_TIMEOUT", 12)
    monkeypatch.setattr(orm_module.settings, "MYSQL_WRITE_TIMEOUT", 13)
    monkeypatch.setattr(
        orm_module,
        "create_engine",
        lambda url, **kwargs: captured.update(kwargs) or object(),
    )

    orm_module._build_engine("default")

    assert captured["connect_args"] == {
        "connect_timeout": 4,
        "read_timeout": 12,
        "write_timeout": 13,
    }
