import asyncio
from collections.abc import Callable, Coroutine
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest

from rate_limiter import RateLimit


async def test_successful_execution() -> None:
    """Test that the function executes successfully when limit is not reached."""
    redis_mock = Mock()
    lua_mock = AsyncMock()
    lua_mock.return_value = [0, 1, 0]
    redis_mock.register_script.return_value = lua_mock

    rate_limit = RateLimit(
        redis=redis_mock,
        limit=5,
        window=10,
    )

    executed = False

    async def my_fn() -> int:
        nonlocal executed
        executed = True
        return 42

    wrapped = rate_limit(fn=my_fn, key='test')
    result = await wrapped()
    assert executed
    assert result == 42


async def test_rate_limit_waits_when_exceeded() -> None:
    """Test that the limiter waits when the rate limit is exceeded."""
    redis_mock = Mock()
    lua_mock = AsyncMock()
    # first call blocked, second call allowed
    lua_mock.side_effect = [
        [1, 0, 100],
        [2, 1, 0],
    ]
    redis_mock.register_script.return_value = lua_mock

    rate_limit = RateLimit(
        redis=redis_mock,
        limit=1,
        window=10,
    )

    executed = False

    async def my_fn() -> str:
        nonlocal executed
        executed = True
        return 'done'

    sleep_calls: list[float] = []

    async def fake_sleep(duration: float) -> None:
        sleep_calls.append(duration)

    bound: Callable[[float], Coroutine[Any, Any, None]] = asyncio.sleep
    asyncio.sleep = fake_sleep  # type: ignore[assignment]

    try:
        wrapped = rate_limit(fn=my_fn, key='test')
        result = await wrapped()
    finally:
        asyncio.sleep = bound  # type: ignore[assignment]

    assert executed
    assert result == 'done'
    # Should wait the wait_ms from Lua script
    assert sleep_calls == [0.1]


async def test_is_allowed_returns_correct_values() -> None:
    """Test that is_allowed returns correct allowed status and wait time."""
    redis_mock = Mock()
    lua_mock = AsyncMock()
    lua_mock.return_value = [5, 0, 500]
    redis_mock.register_script.return_value = lua_mock

    rate_limit = RateLimit(
        redis=redis_mock,
        limit=3,
        window=10,
    )

    allowed, wait_ms = await rate_limit.is_allowed('test_key')
    assert allowed is False
    assert wait_ms == 500


async def test_wait_until_allowed() -> None:
    """Test that wait_until_allowed waits when not allowed."""
    redis_mock = Mock()
    lua_mock = AsyncMock()
    lua_mock.return_value = [5, 0, 200]
    redis_mock.register_script.return_value = lua_mock

    rate_limit = RateLimit(
        redis=redis_mock,
        limit=3,
        window=10,
    )

    sleep_calls: list[float] = []

    async def fake_sleep(duration: float) -> None:
        sleep_calls.append(duration)

    bound: Callable[[float], Coroutine[Any, Any, None]] = asyncio.sleep
    asyncio.sleep = fake_sleep  # type: ignore[assignment]

    try:
        await rate_limit.wait_until_allowed('test_key')
    finally:
        asyncio.sleep = bound  # type: ignore[assignment]

    assert sleep_calls == [0.2]


async def test_exception_propagates_immediately() -> None:
    """Test that exceptions in wrapped functions propagate immediately."""
    redis_mock = Mock()
    lua_mock = AsyncMock()
    lua_mock.return_value = [0, 1, 0]
    redis_mock.register_script.return_value = lua_mock

    rate_limit = RateLimit(
        redis=redis_mock,
        limit=1,
        window=10,
    )

    async def my_fn() -> None:
        raise RuntimeError('error in function')

    wrapped = rate_limit(fn=my_fn, key='test')

    with pytest.raises(RuntimeError, match='error in function'):
        await wrapped()


async def test_high_rps_limit_concurrent(redis_mock: Any) -> None:
    """Ensure that RateLimit correctly enforces 30 RPS under concurrent load."""
    limiter = RateLimit(redis=redis_mock, limit=30, window=1)

    async def dummy_task(i: int) -> str:
        await asyncio.sleep(0)
        return f'ok-{i}'

    limited_task = limiter(dummy_task, key='high_rps:test')

    # Launch 31 concurrent tasks
    tasks = [limited_task(i) for i in range(31)]
    results = await asyncio.gather(*tasks)

    # All should succeed (some may wait)
    assert len(results) == 31
    assert all(r.startswith('ok-') for r in results)
    assert len(set(results)) == len(results)
