"""Redis pools decode responses to strings; cache values use JSON rather than eval."""

import json
import threading
from typing import Any

from redis import ConnectionPool, StrictRedis

from app.core.config import settings
from app.core.logger import logger

_pools: dict[tuple[str, int], ConnectionPool] = {}
_lock = threading.Lock()


def get_redis(instance: str = "default", db: int | None = None) -> StrictRedis:
    target_db = settings.REDIS_DEFAULT_DB if db is None else db
    return StrictRedis(connection_pool=_pool(instance, target_db))


def set_cache(key: str, value: Any, ttl: int = 7200) -> None:
    get_redis().set(key, json.dumps(value, ensure_ascii=False, default=str), ttl)


def get_cache(key: str) -> Any:
    raw = get_redis().get(key)
    return json.loads(raw) if raw else None


def close_all() -> None:
    with _lock:
        pools = list(_pools.values())
        _pools.clear()
    for pool in pools:
        pool.disconnect()


def _pool(instance: str, db: int) -> ConnectionPool:
    key = (instance, db)
    pool = _pools.get(key)
    if pool is not None:
        return pool
    # Serialize first access so concurrent callers cannot create and leak duplicate pools.
    with _lock:
        pool = _pools.get(key)
        if pool is None:
            pool = _build_pool(instance, db)
            _pools[key] = pool
        return pool


def _build_pool(instance: str, db: int) -> ConnectionPool:
    cfg = settings.REDIS_DATABASES.get(instance)
    if cfg is None:
        raise RuntimeError(
            f"Redis 实例 {instance!r} 未配置，可用: {sorted(settings.REDIS_DATABASES)}"
        )

    pool = ConnectionPool(
        host=cfg.host,
        port=cfg.port,
        username=cfg.username,
        password=cfg.password.get_secret_value(),
        db=db,
        decode_responses=True,
        max_connections=settings.REDIS_MAX_CONNECTIONS,
        socket_connect_timeout=settings.REDIS_CONNECT_TIMEOUT,
        socket_timeout=settings.REDIS_TIMEOUT,
    )
    logger.info(f"Redis[{instance}/{db}] 连接池就绪 {cfg.host}:{cfg.port}")
    return pool
