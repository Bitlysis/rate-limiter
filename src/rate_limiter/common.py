import asyncio
import logging
import typing as t
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Callable

from redis.asyncio import Redis

type TargetFunction[T, **P] = Callable[P, Awaitable[T]]

log = logging.getLogger('rate_limiter')


def rate_limit(
        redis: Redis,
        limit: int,
        tries: int,
        key: str,
        allowed_exceptions: t.Tuple[t.Type[Exception], ...] = (),
        interval: int = 1,
        logger: logging.Logger = log,
) -> t.Callable[[TargetFunction], TargetFunction]:
    def wrapper(fn: TargetFunction) -> TargetFunction:
        async def wrapped(*args: P.args, **kwargs: P.kwargs) -> t.Any:  # type: ignore
            for try_idx in range(tries):
                logger.info('Try to run %s for the %s try.', fn.__name__, try_idx + 1)

                if (counter := int(await redis.incr(key))) >= limit - 1:
                    await redis.decr(key)
                    log.info('Counter is: %s', counter)
                    logger.info('Max counter tries (%s) reached. Sleep and wait.', limit)
                    await asyncio.sleep(interval)
                    continue

                try:
                    result = await fn(*args, **kwargs)
                    logger.info('Got result from the %s try.', try_idx + 1)
                    return result
                except allowed_exceptions:
                    pass
                finally:
                    await redis.decr(key)

                logger.info('Sleep %s seconds before retry.', interval)
                await asyncio.sleep(interval)

            logger.info('All retry attempts failed. Stop trying.')

        return wrapped

    return wrapper


@dataclass
class RateLimit:
    redis: Redis
    limit: int
    tries: int
    allowed_exceptions: tuple[type[Exception], ...] = ()
    interval: int | float = 1
    logger: logging.Logger = log

    def __call__[T, **P](self, fn: TargetFunction[T, P], key: str) -> TargetFunction[T, P]:
        async def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:  # type: ignore
            for try_idx in range(self.tries):
                self.logger.info('Try to run %s for the %s try.', fn.__name__, try_idx + 1)

                res = await self.redis.incr(key)
                if (counter := int(res)) >= self.limit - 1:
                    await self.redis.decr(key)
                    log.info('Counter is: %s', counter)
                    self.logger.info('Max counter tries (%s) reached. Sleep and wait.', self.limit)
                    await asyncio.sleep(self.interval)
                    continue

                try:
                    result = await fn(*args, **kwargs)
                    self.logger.info('Got result from the %s try.', try_idx + 1)
                    return result
                except self.allowed_exceptions:
                    pass
                finally:
                    await self.redis.decr(key)

                self.logger.info('Sleep %s seconds before retry.', self.interval)
                await asyncio.sleep(self.interval)

            self.logger.error('All retry attempts failed. Stop trying.')

        return wrapped
