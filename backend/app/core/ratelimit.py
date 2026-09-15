"""限流：进程内版本用于单机，Redis 版本用于多实例。

两者的接口一致（check(key, limit) -> (是否放行, 需等待秒数)），
所以多实例部署时只需要把 REDIS_URL 配上，业务代码不用动。
"""

import threading
import time
from collections import deque
from typing import Protocol


class RateLimiter(Protocol):
    def check(self, key: str, limit: int, now: float | None = None) -> tuple[bool, int]:
        """返回 (是否放行, 需要等待的秒数)。"""
        ...

    def reset(self) -> None: ...


class SlidingWindowLimiter:
    """进程内滑动窗口：单机零依赖，但多实例部署时各算各的，限流会失真。"""

    def __init__(self, window_seconds: float = 60.0) -> None:
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, now: float | None = None) -> tuple[bool, int]:
        """返回 (是否放行, 需要等待的秒数)。"""
        if limit <= 0:
            return True, 0

        moment = time.monotonic() if now is None else now
        with self._lock:
            bucket = self._hits.setdefault(key, deque())
            cutoff = moment - self.window_seconds
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()

            if len(bucket) >= limit:
                retry_after = max(1, int(self.window_seconds - (moment - bucket[0])) + 1)
                return False, retry_after

            bucket.append(moment)
            return True, 0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


class RedisRateLimiter:
    """基于 Redis 有序集合的滑动窗口，多实例共享同一份计数。

    每个 key 一个 zset：成员是「时间戳:随机后缀」，分数是时间戳。
    每次请求先清掉窗口外的成员，再看剩余数量是否超限。
    用 zset 而不是计数器是因为计数器无法表达「最近 60 秒」这种滑动窗口。
    """

    WINDOW_SECONDS = 60.0

    def __init__(self, client, key_prefix: str = "veyra:rl:") -> None:
        self._client = client
        self._prefix = key_prefix

    def check(self, key: str, limit: int, now: float | None = None) -> tuple[bool, int]:
        if limit <= 0:
            return True, 0

        moment = time.time() if now is None else now
        redis_key = f"{self._prefix}{key}"
        cutoff = moment - self.WINDOW_SECONDS

        pipe = self._client.pipeline()
        pipe.zremrangebyscore(redis_key, 0, cutoff)
        pipe.zcard(redis_key)
        _, used = pipe.execute()

        if int(used) >= limit:
            oldest = self._client.zrange(redis_key, 0, 0, withscores=True)
            oldest_at = float(oldest[0][1]) if oldest else moment
            retry_after = max(1, int(self.WINDOW_SECONDS - (moment - oldest_at)) + 1)
            return False, retry_after

        # 成员名带时间戳，避免同一毫秒内的并发请求互相覆盖
        member = f"{moment}:{time.monotonic_ns()}"
        pipe = self._client.pipeline()
        pipe.zadd(redis_key, {member: moment})
        pipe.expire(redis_key, int(self.WINDOW_SECONDS) + 1)
        pipe.execute()
        return True, 0

    def reset(self) -> None:
        # 跨实例共享的计数不能靠单机 clean 掉；测试里用独立的 key 前缀隔离
        for redis_key in self._client.scan_iter(f"{self._prefix}*"):
            self._client.delete(redis_key)


# 进程级单例：所有请求共用同一个计数器
limiter = SlidingWindowLimiter()


def build_rate_limiter(settings) -> RateLimiter:
    """按配置选实现：配了 REDIS_URL 就用 Redis，否则退回进程内。"""
    redis_url = (getattr(settings, "redis_url", "") or "").strip()
    if not redis_url:
        return limiter

    try:
        import redis  # 延迟导入：没配 Redis 的环境不需要这个依赖

        client = redis.Redis.from_url(redis_url, decode_responses=True)
        # 必须显式 ping：from_url 只是解析地址，不会真的连接，
        # 配错了要等到第一个请求才炸——那时候服务已经在跑了
        client.ping()
        return RedisRateLimiter(client)
    except Exception as exc:  # noqa: BLE001 Redis 起不来时不能把服务拖垮
        import logging

        logging.getLogger(__name__).warning(
            "Redis 不可用，限流退回进程内实现：%s", exc
        )
        return limiter
