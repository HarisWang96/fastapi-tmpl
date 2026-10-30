"""Repository and service tests without a database, covering SQL, binding, and LIKE escaping.

Real driver behavior (PyMySQL format style and literal percent rules) is tested
in test_mysql_connection.py and test_mysql_integration.py.
"""

from app.core.db.mysql import _ensure_percent_escaped
from app.modules._example import repository, service


class RecordingConnection:
    """Record calls and return prepared results as a MysqlConnection substitute."""

    def __init__(
        self,
        *,
        rows: list[dict] | None = None,
        one: dict | None = None,
        lastrowid: int = 7,
    ) -> None:
        self.calls: list[tuple[str, str, object]] = []
        self._rows = rows or []
        self._one = one
        self.lastrowid = lastrowid

    def get_all(self, sql: str, params=None) -> list[dict]:
        self.calls.append(("get_all", sql, params))
        return self._rows

    def get_one(self, sql: str, params=None) -> dict | None:
        self.calls.append(("get_one", sql, params))
        return self._one

    def execute(self, sql: str, params=None) -> int:
        self.calls.append(("execute", sql, params))
        return 1


def test_list_users_without_keyword_binds_pagination():
    conn = RecordingConnection()
    repository.list_users(conn, keyword=None, limit=20, offset=0)

    _, sql, params = conn.calls[0]
    assert "WHERE is_delete = 0" in sql
    assert sql.endswith("ORDER BY id DESC LIMIT %s OFFSET %s")
    assert params == (20, 0)


def test_list_users_escapes_like_metacharacters():
    conn = RecordingConnection()
    repository.list_users(conn, keyword="50%_a\\b")

    _, sql, params = conn.calls[0]
    assert "user_name LIKE %s OR user_mobile LIKE %s" in sql
    expected = "%50\\%\\_a\\\\b%"
    assert params == (expected, expected, 20, 0)


def test_count_users_without_keyword_passes_none():
    conn = RecordingConnection(one={"total": 0})
    repository.count_users(conn, keyword=None)

    _, sql, params = conn.calls[0]
    assert sql == "SELECT COUNT(*) AS total FROM t_demo_user WHERE is_delete = 0"
    assert params is None


def test_count_users_with_keyword_passes_like_params():
    conn = RecordingConnection(one={"total": 3})
    repository.count_users(conn, keyword="张")

    _, sql, params = conn.calls[0]
    assert "AND (user_name LIKE %s OR user_mobile LIKE %s)" in sql
    assert params == ("%张%", "%张%")


def test_create_user_returns_lastrowid():
    conn = RecordingConnection(lastrowid=42)
    new_id = repository.create_user(conn, name="张三", mobile=None)

    _, sql, params = conn.calls[0]
    assert sql == "INSERT INTO t_demo_user (user_name, user_mobile) VALUES (%s, %s)"
    assert params == ("张三", "")
    assert new_id == 42


def test_generated_sql_has_no_single_percent_and_placeholder_count_matches():
    conn = RecordingConnection(one={"total": 1})
    repository.list_users(conn, keyword="李", limit=10, offset=20)
    repository.count_users(conn, keyword="李")
    repository.create_user(conn, name="李四")

    for _, sql, params in conn.calls:
        _ensure_percent_escaped(sql)
        if params:
            assert sql.count("%s") == len(params), f"占位符与参数数量不一致: {sql}"


def test_service_counts_first_then_pages_and_maps_rows():
    conn = RecordingConnection(
        rows=[
            {
                "id": 1,
                "user_name": "张三",
                "user_mobile": "13800000000",
                "create_time": None,
                "update_time": None,
            }
        ],
        one={"total": 21},
    )
    result = service.list_users(conn, keyword=None, page=3, page_size=10)

    assert [call[0] for call in conn.calls] == ["get_one", "get_all"]
    assert conn.calls[1][2] == (10, 20)
    assert result.total == 21
    assert result.page == 3
    assert result.page_size == 10
    assert result.list[0].user_name == "张三"


def test_service_create_user_returns_new_id():
    conn = RecordingConnection(lastrowid=99)
    assert service.create_user(conn, name="王五", mobile="139") == 99
