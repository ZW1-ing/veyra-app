"""进程内滑动窗口限流。

为什么自己写而不上 Redis：这一步的目标是「单机部署不被打爆」，
进程内实现零依赖、零运维。真要多实例部署时，把 SlidingWindowLimiter
换成基于 Redis 的实现即可，接口保持不变。
"""

import threading
import time
from collections import deque


class SlidingWindowLimiter:
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


# 进程级单例：所有请求共用同一个计数器
limiter = SlidingWindowLimiter()
