import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional, Tuple, Type

from redis.asyncio import Redis

from rate_limiter.exceptions import RetryLimitReached

log: logging.Logger = logging.getLogger(__name__)

SLIDING_WINDOW_LUA_SCRIPT = '''
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2]) * 1000
local limit = tonumber(ARGV[3])

redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
redis.call('ZADD', key, now, tostring(now))
local count = redis.call('ZCARD', key)
redis.call('EXPIRE', key, ARGV[2])

if count <= limit then
    return {count, 1}
else
    return {count, 0}
end
'''

FnType = Callable[..., Awaitable]


@dataclass
class RateLimit:
    redis: Redis
    limit: int
    window: int = 1
    retries: int = 3
    backoff_ms: int = 200
    backoff_factor: float = 1.0
    retry_on_exceptions: Tuple[Type[BaseException], ...] = ()
    logger: logging.Logger = log

    def __post_init__(self) -> None:
        self._lua_script = self.redis.register_script(SLIDING_WINDOW_LUA_SCRIPT)

    async def is_execution_allowed(self, key: str) -> bool:
        now: int = int(time.time() * 1000)
        count_allowed = await self._lua_script(keys=[key], args=[now, self.window, self.limit])
        count, allowed = count_allowed
        return bool(allowed)

    def __call__(
        self, fn: Optional[FnType] = None, *, key: str
    ) -> Callable[..., Awaitable[Optional[object]]]:
        def decorator(inner_fn: FnType) -> FnType:
            async def wrapper(*args, **kwargs) -> Optional[object]:
                delay: float = self.backoff_ms
                for attempt in range(1, self.retries + 1):
                    try:
                        if await self.is_execution_allowed(key):
                            return await inner_fn(*args, **kwargs)
                    except self.retry_on_exceptions as e:
                        self.logger.warning(
                            'Exception %s occurred during execution of %s, retrying. Attempt %s/%s.',
                            e,
                            key,
                            attempt,
                            self.retries,
                        )
                    except Exception:
                        self.logger.exception(
                            'Unhandled exception in decorated function. Limiter stops.'
                        )
                        raise

                    self.logger.warning(
                        'Rate limit hit for %s. Attempt %s/%s. Retrying in %s ms.',
                        key,
                        attempt,
                        self.retries,
                        delay,
                    )
                    await asyncio.sleep(delay / 1000)
                    delay *= self.backoff_factor

                self.logger.error(
                    'All %s attempts exhausted for %s. Giving up.', self.retries, key
                )
                raise RetryLimitReached('Attempts limit reached.')

            return wrapper  # type: ignore

        return decorator(fn) if fn is not None else decorator
