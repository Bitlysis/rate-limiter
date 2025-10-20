import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import wraps

from redis.asyncio import Redis

log = logging.getLogger(__name__)

type TargetFunction[T, **P] = Callable[P, Awaitable[T]]


SLIDING_WINDOW_LUA_SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2]) * 1000
local limit = tonumber(ARGV[3])

redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
redis.call('ZADD', key, now, tostring(now))
local count = redis.call('ZCARD', key)
redis.call('EXPIRE', key, ARGV[2])

if count <= limit then
    return {count, 1, 0}
else
    local earliest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')[2]
    local wait = window - (now - earliest)
    return {count, 0, wait}
end
"""

@dataclass
class RateLimit:
    redis: Redis  # type: ignore
    limit: int
    window: int = 1

    def __post_init__(self) -> None:
        self._lua_script = self.redis.register_script(SLIDING_WINDOW_LUA_SCRIPT)

    async def is_allowed(self, key: str) -> tuple[bool, int]:
        now: int = int(time.time() * 1000)
        count, allowed, wait_ms = await self._lua_script(
            keys=[key],
            args=[now, self.window, self.limit],
        )
        log.info(
            'Limiter stats. count: %s, allowed: %s, wait ms: %s',
            count,
            allowed,
            wait_ms,
        )
        return bool(allowed), int(wait_ms)

    async def wait_until_allowed(self, key: str) -> None:
        allowed, wait_ms = await self.is_allowed(key)
        if not allowed:
            log.info('Rate limited. Waiting %s ms before allowing execution.', wait_ms)
            await asyncio.sleep(wait_ms / 1000)

    def __call__[T, **P](
        self,
        fn: TargetFunction[T, P],
        *,
        key: str,
    ) -> TargetFunction[T, P]:
        @wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            await self.wait_until_allowed(key)
            return await fn(*args, **kwargs)
        return wrapper
