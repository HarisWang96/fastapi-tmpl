"""Raw SQL access to MySQL through SQLAlchemy Core, sharing the ORM Engine.

Each database has one Engine and pool shared by ORM and raw SQL access.

Transaction boundaries are managed by app.api.deps.get_db; this layer does not commit implicitly.

exec_driver_sql uses PyMySQL's format parameter style. Literal percent signs in
parameterized SQL must be doubled (for example, DATE_FORMAT(x, '%%Y')). The
_ensure_percent_escaped guard catches invalid cases before execution.
"""

from collections.abc import Callable, Sequence
from typing import Any

from sqlalchemy.engine import Connection, Engine, Result

from app.core.db.orm import get_engine
from app.core.logger import logger


# PyMySQL accepts %s placeholders and %% escapes; other percent sequences fail during interpolation.
def _ensure_percent_escaped(sql: str) -> None:
    index = sql.find("%")
    while index != -1:
        token = sql[index : index + 2]
        if token in ("%s", "%%"):
            index = sql.find("%", index + 2)
            continue
        raise ValueError(f"SQL 只支持 %s 占位符，字面 % 需写成 %%：{sql}")


def _normalize(value: Any) -> Any:
    if value == b"\x00":
        return False
    if value == b"\x01":
        return True
    return value


class MysqlConnection:
    """Represent one connection for a request.

    Connect lazily on the first query so a connection is not created in a
    dependency thread and then used in a controller thread; SQLAlchemy Connection
    objects are not guaranteed to be thread-safe.
    """

    def __init__(self, engine_factory: Callable[[], Engine]) -> None:
        self._engine_factory = engine_factory
        self._conn: Connection | None = None
        self._lastrowid: int | None = None

    def get_all(self, sql: str, params: Sequence[Any] | None = None) -> list[dict[str, Any]]:
        rows = self._execute(sql, params).mappings().all()
        return [{key: _normalize(value) for key, value in row.items()} for row in rows]

    def get_one(self, sql: str, params: Sequence[Any] | None = None) -> dict[str, Any] | None:
        row = self._execute(sql, params).mappings().first()
        return {key: _normalize(value) for key, value in row.items()} if row else None

    def execute(self, sql: str, params: Sequence[Any] | None = None) -> int:
        result = self._execute(sql, params)
        self._lastrowid = result.lastrowid
        return result.rowcount

    def execute_many(self, sql: str, params_seq: Sequence[Sequence[Any]]) -> int:
        # An empty parameter sequence is treated as no parameters; return zero without executing SQL.
        if not params_seq:
            return 0
        _ensure_percent_escaped(sql)
        try:
            result = self._connection().exec_driver_sql(sql, list(params_seq))
        except Exception:
            logger.opt(exception=True).error(f"MySQL 批量执行失败: {sql}")
            raise
        return result.rowcount

    @property
    def lastrowid(self) -> int | None:
        return self._lastrowid

    def commit(self) -> None:
        if self._conn is not None:
            self._conn.commit()

    def rollback(self) -> None:
        if self._conn is not None:
            self._conn.rollback()

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None
                self._lastrowid = None

    def _connection(self) -> Connection:
        if self._conn is None:
            self._conn = self._engine_factory().connect()
        return self._conn

    def _execute(self, sql: str, params: Sequence[Any] | None) -> Result[Any]:
        # PyMySQL interpolates percent sequences only when parameters are supplied.
        if params:
            _ensure_percent_escaped(sql)
        try:
            return self._connection().exec_driver_sql(sql, params)
        except Exception:
            logger.opt(exception=True).error(f"MySQL 执行失败: {sql}")
            raise


class MysqlPool:
    """Preserve the connection factory API; the SQLAlchemy Engine owns the pool."""

    def connection(self, name: str = "default") -> MysqlConnection:
        return MysqlConnection(lambda: get_engine(name))


mysql_pool = MysqlPool()
