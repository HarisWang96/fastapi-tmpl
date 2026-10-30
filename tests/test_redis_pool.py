"""Redis pool tests: concurrent first access creates one pool, and close disconnects it."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

import app.core.db.redis as redis_module
from app.core.config import RedisConfig


class CountingPool:
    instances: list["CountingPool"] = []
    _lock = threading.Lock()

    def __init__(self, **kwargs) -> None:
        # Widen the creation window so callers would create duplicates without a lock.
        time.sleep(0.02)
        self.kwargs = kwargs
        self.disconnected = False
        with CountingPool._lock:
            CountingPool.instances.append(self)

    def disconnect(self) -> None:
        self.disconnected = True


@pytest.fixture()
def isolated_redis(monkeypatch):
    CountingPool.instances = []
    monkeypatch.setattr(redis_module, "ConnectionPool", CountingPool)
    monkeypatch.setattr(redis_module, "_pools", {})
    monkeypatch.setattr(
        redis_module.settings,
        "REDIS_DATABASES",
        {"race": RedisConfig(host="127.0.0.1", password="secret")},
    )
    return redis_module


def test_concurrent_first_access_builds_one_pool(isolated_redis):
    workers = 16
    barrier = threading.Barrier(workers)

    def get_pool() -> object:
        barrier.wait()
        return isolated_redis._pool("race", 0)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        pools = list(executor.map(lambda _: get_pool(), range(workers)))

    assert len(CountingPool.instances) == 1
    assert all(pool is pools[0] for pool in pools)
    assert isolated_redis._pools[("race", 0)] is pools[0]


def test_pool_uses_instance_config_and_target_db(isolated_redis):
    pool = isolated_redis._pool("race", 3)

    assert pool.kwargs["host"] == "127.0.0.1"
    assert pool.kwargs["db"] == 3
    assert pool.kwargs["password"] == "secret"
    assert pool.kwargs["decode_responses"] is True


def test_close_all_disconnects_and_clears(isolated_redis):
    pool = isolated_redis._pool("race", 0)
    isolated_redis.close_all()

    assert pool.disconnected is True
    assert isolated_redis._pools == {}


def test_unconfigured_instance_raises(isolated_redis):
    with pytest.raises(RuntimeError, match="未配置"):
        isolated_redis._pool("missing", 0)
