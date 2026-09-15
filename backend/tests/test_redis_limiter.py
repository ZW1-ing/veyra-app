"""Redis 限流：多实例共享计数；没配 Redis 时退回进程内实现。"""

from app.core.config import Settings
from app.core.ratelimit import RedisRateLimiter, SlidingWindowLimiter, build_rate_limiter


class FakeRedis:
    """够用的内存版 Redis：只实现限流用到的那几个 zset 命令。

    用假客户端而不是真 Redis：测试要能在任何环境跑，
    而且这里要验证的是窗口裁剪与计数逻辑，不是 Redis 本身。
    """

    def __init__(self) -> None:
        self.zsets: dict[str, dict[str, float]] = {}

    def pipeline(self):
        return FakePipeline(self)

    def zrange(self, key: str, start: int, end: int, withscores: bool = False):
        items = sorted(self.zsets.get(key, {}).items(), key=lambda kv: kv[1])
        sliced = items[start : end + 1] if end >= 0 else items[start:]
        return sliced if withscores else [member for member, _ in sliced]

    def scan_iter(self, pattern: str):
        prefix = pattern.rstrip("*")
        return [key for key in list(self.zsets) if key.startswith(prefix)]

    def delete(self, key: str) -> None:
        self.zsets.pop(key, None)


class FakePipeline:
    def __init__(self, client: FakeRedis) -> None:
        self._client = client
        self._ops: list[tuple] = []

    def zremrangebyscore(self, key: str, minimum, maximum):
        self._ops.append(("zremrangebyscore", key, minimum, maximum))
        return self

    def zcard(self, key: str):
        self._ops.append(("zcard", key))
        return self

    def zadd(self, key: str, mapping: dict):
        self._ops.append(("zadd", key, mapping))
        return self

    def expire(self, key: str, seconds: int):
        self._ops.append(("expire", key, seconds))
        return self

    def execute(self) -> list:
        results = []
        for op in self._ops:
            if op[0] == "zremrangebyscore":
                _, key, minimum, maximum = op
                bucket = self._client.zsets.get(key, {})
                for member in [m for m, score in bucket.items() if minimum <= score <= maximum]:
                    bucket.pop(member, None)
                results.append(len(bucket))
            elif op[0] == "zcard":
                results.append(len(self._client.zsets.get(op[1], {})))
            elif op[0] == "zadd":
                _, key, mapping = op
                self._client.zsets.setdefault(key, {}).update(mapping)
                results.append(len(mapping))
            elif op[0] == "expire":
                results.append(True)
        self._ops.clear()
        return results


def test_redis_limiter_allows_up_to_limit_then_blocks():
    limiter = RedisRateLimiter(FakeRedis())

    assert limiter.check("k1", limit=2, now=1000.0) == (True, 0)
    assert limiter.check("k1", limit=2, now=1000.5) == (True, 0)

    allowed, retry_after = limiter.check("k1", limit=2, now=1001.0)
    assert allowed is False
    assert retry_after >= 1


def test_redis_limiter_slides_window_and_isolates_keys():
    limiter = RedisRateLimiter(FakeRedis())

    limiter.check("k1", limit=1, now=1000.0)
    assert limiter.check("k1", limit=1, now=1005.0)[0] is False

    # 窗口滑过 60 秒后，旧的计数应当被清掉
    assert limiter.check("k1", limit=1, now=1061.0) == (True, 0)

    # 不同 key 各算各的
    assert limiter.check("k2", limit=1, now=1000.0) == (True, 0)


def test_redis_limiter_counts_are_shared_between_instances():
    """两个 RedisRateLimiter 实例共用同一个 Redis，计数应当互通——这正是多实例部署要的效果。"""
    client = FakeRedis()
    instance_a = RedisRateLimiter(client)
    instance_b = RedisRateLimiter(client)

    assert instance_a.check("same-key", limit=1, now=2000.0) == (True, 0)
    assert instance_b.check("same-key", limit=1, now=2000.1)[0] is False


def test_build_rate_limiter_picks_implementation_by_config():
    assert isinstance(build_rate_limiter(Settings(redis_url="")), SlidingWindowLimiter)

    # 配了但连不上时不能把服务拖垮，应当退回进程内实现
    fallback = build_rate_limiter(Settings(redis_url="redis://127.0.0.1:1/0"))
    assert isinstance(fallback, SlidingWindowLimiter)
