"""Synchronous SQLAlchemy 2.1 Engine and Session setup for MySQL.

The ORM and raw SQL layer (app.core.db.mysql) share one Engine and pool per
database. The pure-Python PyMySQL driver avoids a libmysqlclient dependency.
Engines are lazy: no connection is attempted until an engine is requested.
"""

import threading

from sqlalchemy import URL, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.logger import logger

_DRIVER = "mysql+pymysql"

_engines: dict[str, Engine] = {}
_factories: dict[str, sessionmaker[Session]] = {}
_lock = threading.Lock()


def get_engine(name: str = "default") -> Engine:
    engine = _engines.get(name)
    if engine is not None:
        return engine
    with _lock:
        if name not in _engines:
            _engines[name] = _build_engine(name)
        return _engines[name]


def get_session_factory(name: str = "default") -> sessionmaker[Session]:
    factory = _factories.get(name)
    if factory is not None:
        return factory
    # Get the engine before locking factories to avoid nesting the same non-reentrant lock.
    engine = get_engine(name)
    with _lock:
        if name not in _factories:
            _factories[name] = sessionmaker(bind=engine, expire_on_commit=False)
        return _factories[name]


def dispose_all() -> None:
    with _lock:
        for engine in _engines.values():
            engine.dispose()
        _engines.clear()
        _factories.clear()


def build_url(cfg) -> URL:
    """Build a SQLAlchemy URL from one database config, also used by Alembic offline mode."""
    return URL.create(
        _DRIVER,
        username=cfg.user,
        password=cfg.password.get_secret_value(),
        host=cfg.host,
        port=cfg.port,
        database=cfg.database,
        query={"charset": settings.DB_CHARSET},
    )


def _build_engine(name: str) -> Engine:
    cfg = settings.MYSQL_DATABASES.get(name)
    if cfg is None:
        raise RuntimeError(f"MySQL 连接 {name!r} 未配置，可用: {sorted(settings.MYSQL_DATABASES)}")
    engine = create_engine(
        build_url(cfg),
        pool_size=settings.MYSQL_POOL_MAX_CONNECTIONS,
        max_overflow=0,
        pool_timeout=settings.MYSQL_POOL_TIMEOUT,
        pool_recycle=settings.MYSQL_POOL_RECYCLE,
        pool_pre_ping=True,
        connect_args={
            "connect_timeout": settings.MYSQL_CONNECT_TIMEOUT,
            "read_timeout": settings.MYSQL_READ_TIMEOUT,
            "write_timeout": settings.MYSQL_WRITE_TIMEOUT,
        },
        future=True,
    )
    logger.info(
        f"ORM[{name}] 引擎就绪 {cfg.host}:{cfg.port}/{cfg.database} "
        f"driver={_DRIVER} pool={settings.MYSQL_POOL_MAX_CONNECTIONS}"
    )
    return engine
