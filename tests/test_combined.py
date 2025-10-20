from asyncio import gather
from unittest.mock import AsyncMock, Mock, patch

import pytest
from redis.asyncio import Redis

from rate_limiter import RateLimit
from rate_limiter.exceptions import RetryLimitReachedError
from rate_limiter.retry import Retry


async def test_rate_limit_with_retry_on_exception() -> None:
    """Test combining RateLimit with Retry for exception handling."""
    redis_mock = Mock()
    lua_mock = AsyncMock()
    lua_mock.return_value = [0, 1, 0]
    redis_mock.register_script.return_value = lua_mock

    rate_limit = RateLimit(redis=redis_mock, limit=5, window=10)
    retry = Retry(retries=3, backoff_ms=50, retry_on_exceptions=(ValueError,))

    call_count = 0

    async def my_fn() -> str:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ValueError('retry me')
        return 'success'

    # Apply rate limiting first, then retry logic
    rate_limited = rate_limit(fn=my_fn, key='test')
    wrapped = retry(fn=rate_limited, key='test')

    with patch('asyncio.sleep', new=AsyncMock()):
        result = await wrapped()

    assert result == 'success'
    assert call_count == 3


async def test_retry_with_rate_limit_in_reverse_order() -> None:
    """Test combining Retry with RateLimit (reversed order)."""
    redis_mock = Mock()
    lua_mock = AsyncMock()
    lua_mock.return_value = [0, 1, 0]
    redis_mock.register_script.return_value = lua_mock

    rate_limit = RateLimit(redis=redis_mock, limit=5, window=10)
    retry = Retry(retries=3, backoff_ms=50, retry_on_exceptions=(ValueError,))

    call_count = 0

    async def my_fn() -> str:
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise ValueError('retry')
        return 'done'

    # Apply retry first, then rate limiting
    retried = retry(fn=my_fn, key='test')
    wrapped = rate_limit(fn=retried, key='test')

    with patch('asyncio.sleep', new=AsyncMock()):
        result = await wrapped()

    assert result == 'done'
    assert call_count == 2


async def test_rate_limit_blocks_with_retry_exhaustion() -> None:
    """Test that retry exhaustion works with rate limiting."""
    redis_mock = Mock()
    lua_mock = AsyncMock()
    # Rate limit allows, but function always fails
    lua_mock.return_value = [0, 1, 0]
    redis_mock.register_script.return_value = lua_mock

    rate_limit = RateLimit(redis=redis_mock, limit=5, window=10)
    retry = Retry(retries=2, backoff_ms=50, retry_on_exceptions=(ValueError,))

    async def my_fn() -> None:
        raise ValueError('always fail')

    rate_limited = rate_limit(fn=my_fn, key='test')
    wrapped = retry(fn=rate_limited, key='test')

    with (
        pytest.raises(RetryLimitReachedError),
        patch('asyncio.sleep', new=AsyncMock()),
    ):
        await wrapped()


async def test_independent_usage() -> None:
    """Test that RateLimit and Retry can be used independently."""
    # Test RateLimit independently
    redis_mock = Mock()
    lua_mock = AsyncMock()
    lua_mock.return_value = [0, 1, 0]
    redis_mock.register_script.return_value = lua_mock

    rate_limit = RateLimit(redis=redis_mock, limit=5, window=10)

    async def rate_limited_fn() -> str:
        return 'rate limited only'

    wrapped_rate = rate_limit(fn=rate_limited_fn, key='test1')
    result1 = await wrapped_rate()
    assert result1 == 'rate limited only'

    # Test Retry independently
    retry = Retry(retries=2, backoff_ms=50, retry_on_exceptions=(ValueError,))

    call_count = 0

    async def retry_fn() -> str:
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise ValueError('once')
        return 'retry only'

    wrapped_retry = retry(fn=retry_fn, key='test2')

    with patch('asyncio.sleep', new=AsyncMock()):
        result2 = await wrapped_retry()

    assert result2 == 'retry only'


async def test_concurrent_with_transient_failures_and_retry_exhaustion(
    redis_mock: Redis,  # type: ignore[type-arg]
) -> None:
    """Test that some tasks fail when retries are exhausted under concurrent load."""
    limit = 30
    rate_limit = RateLimit(redis=redis_mock, limit=limit, window=1)
    retry = Retry(retries=2, backoff_ms=50, retry_on_exceptions=(ValueError,))

    call_counts: dict[int, int] = {}

    async def flaky_task(i: int) -> str:
        call_counts[i] = call_counts.get(i, 0) + 1
        # Task 30 always fails to exhaust retries
        if i == limit:
            raise ValueError(f'always fails: {i}')
        return f'ok-{i}'

    # Compose: rate limit first, then retry
    rate_limited = rate_limit(flaky_task, key='concurrent_test')
    wrapped = retry(fn=rate_limited, key='concurrent_test')

    async def run_task(i: int) -> str | None:
        try:
            return await wrapped(i)
        except RetryLimitReachedError:
            return None

    # Launch 31 concurrent tasks
    tasks = [run_task(i) for i in range(limit + 1)]

    with patch('asyncio.sleep', new=AsyncMock()):
        results = await gather(*tasks)

    allowed = [r for r in results if r is not None]
    denied = [r for r in results if r is None]

    # Verify that 30 succeed and 1 fails (task 30 exhausted retries)
    assert len(allowed) == limit
    assert len(denied) == 1

    # Ensure all allowed results are unique and sequential
    assert all(r.startswith('ok-') for r in allowed)
    assert len(set(allowed)) == len(allowed)

    # Verify task 30 was attempted twice (initial + 1 retry)
    assert call_counts[30] == 2
