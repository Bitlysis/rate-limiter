import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import wraps

from rate_limiter.exceptions import RetryLimitReachedError

log = logging.getLogger(__name__)

type TargetFunction[T, **P] = Callable[P, Awaitable[T]]


@dataclass
class Retry:
    retries: int = 3
    backoff_ms: int = 10
    backoff_factor: float = 1.0
    retry_on_exceptions: tuple[type[BaseException], ...] = ()

    def __call__[T, **P](
        self,
        fn: TargetFunction[T, P],
        *,
        key: str,
    ) -> TargetFunction[T, P]:
        @wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            delay: float = self.backoff_ms
            last_exception: BaseException | None = None

            for attempt in range(1, self.retries + 1):
                try:
                    return await fn(*args, **kwargs)
                except self.retry_on_exceptions as e:
                    last_exception = e
                    log.warning(
                        'Exception %s occurred during execution of %s, retrying. '
                        'Attempt %s/%s.',
                        e,
                        key,
                        attempt,
                        self.retries,
                    )
                    if attempt < self.retries:
                        log.info(
                            'Retrying %s in %s ms. Attempt %s/%s.',
                            key,
                            delay,
                            attempt,
                            self.retries,
                        )
                        await asyncio.sleep(delay / 1000)
                        delay *= self.backoff_factor
                except Exception:
                    log.exception('Unhandled exception in wrapped function.')
                    raise

            log.error('All %s attempts exhausted for %s. Giving up.', self.retries, key)
            raise RetryLimitReachedError('Attempts limit reached.') from last_exception

        return wrapper
