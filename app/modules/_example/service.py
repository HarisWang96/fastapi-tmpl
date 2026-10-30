"""Example-domain business logic: accept dependencies and avoid HTTP concerns."""

from app.core.db.mysql import MysqlConnection
from app.modules._example import repository
from app.modules._example.schemas import UserItem, UserPage


def list_users(
    conn: MysqlConnection,
    *,
    keyword: str | None,
    page: int,
    page_size: int,
) -> UserPage:
    total = repository.count_users(conn, keyword=keyword)
    rows = repository.list_users(
        conn,
        keyword=keyword,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    return UserPage(
        list=[UserItem.model_validate(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


def create_user(conn: MysqlConnection, *, name: str, mobile: str | None) -> int:
    return repository.create_user(conn, name=name, mobile=mobile)
