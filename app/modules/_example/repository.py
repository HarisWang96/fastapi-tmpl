"""Data access for the t_demo_user table.

Keep SQL in the repository layer, bind user input with %s placeholders, and
never interpolate user input into SQL strings.
"""

from app.core.db.mysql import MysqlConnection

_COLUMNS = "id, user_name, user_mobile, create_time, update_time"
_LIKE_ESCAPE = str.maketrans({"\\": "\\\\", "%": "\\%", "_": "\\_"})


def list_users(
    conn: MysqlConnection,
    *,
    keyword: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict]:
    where, params = _user_filter(keyword)
    sql = f"SELECT {_COLUMNS} FROM t_demo_user WHERE {where} ORDER BY id DESC LIMIT %s OFFSET %s"
    return conn.get_all(sql, (*params, limit, offset))


def count_users(conn: MysqlConnection, *, keyword: str | None = None) -> int:
    where, params = _user_filter(keyword)
    row = conn.get_one(f"SELECT COUNT(*) AS total FROM t_demo_user WHERE {where}", params or None)
    return int(row["total"]) if row else 0


def create_user(conn: MysqlConnection, *, name: str, mobile: str | None = None) -> int:
    conn.execute(
        "INSERT INTO t_demo_user (user_name, user_mobile) VALUES (%s, %s)",
        (name, mobile or ""),
    )
    return conn.lastrowid or 0


def _user_filter(keyword: str | None) -> tuple[str, tuple[str, ...]]:
    if not keyword:
        return "is_delete = 0", ()
    like = f"%{keyword.translate(_LIKE_ESCAPE)}%"
    return (
        "is_delete = 0 AND (user_name LIKE %s OR user_mobile LIKE %s)",
        (like, like),
    )
