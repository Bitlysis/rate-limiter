import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from rate_limiter.exceptions import RetryLimitReachedError
from rate_limiter.retry import Retry


async def test_successful_execution_no_retry() -> None:
    """Test that the function executes successfully without needing retries."""
    retry = Retry(retries=3, backoff_ms=100, backoff_factor=1.0)

    executed = False

    async def my_fn() -> int:
        nonlocal executed
        executed = True
        return 42

    wrapped = retry(fn=my_fn, key='test')
    result = await wrapped()
    assert executed
    assert result == 42


async def test_retry_on_exceptions_with_recovery(caplog: pytest.LogCaptureFixture) -> None:
    """Test that exceptions in retry_on_exceptions are retried and eventually succeed."""
    retry = Retry(
        retries=3,
        backoff_ms=50,
        backoff_factor=1.0,
        retry_on_exceptions=(ValueError,),
    )

    call_count = 0

    async def my_fn() -> str:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ValueError('retry me')
        return 'success'

    wrapped = retry(fn=my_fn, key='test')
    caplog.set_level(logging.WARNING)

    with patch('asyncio.sleep', new=AsyncMock()):
        result = await wrapped()

    assert result == 'success'
    assert call_count == 3
    assert any('retrying' in r.message for r in caplog.records)


async def test_retry_exhausted_raises_error(caplog: pytest.LogCaptureFixture) -> None:
    """Test that RetryLimitReachedError is raised when all retries are exhausted."""
    retry = Retry(
        retries=2,
        backoff_ms=50,
        backoff_factor=1.0,
        retry_on_exceptions=(ValueError,),
    )

    async def my_fn() -> None:
        raise ValueError('always fail')

    wrapped = retry(fn=my_fn, key='test')
    caplog.set_level(logging.WARNING)

    with (
        pytest.raises(RetryLimitReachedError) as exc_info,
        patch('asyncio.sleep', new=AsyncMock()),
    ):
        await wrapped()

    assert 'Attempts limit reached' in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, ValueError)


@pytest.mark.asyncio
async def test_unhandled_exception_propagates() -> None:
    """Test that unhandled exceptions immediately propagate without retry."""
    retry = Retry(
        retries=2,
        backoff_ms=50,
        backoff_factor=1.0,
        retry_on_exceptions=(ValueError,),
    )

    call_count = 0

    async def my_fn() -> None:
        nonlocal call_count
        call_count += 1
        raise RuntimeError('stop immediately')

    wrapped = retry(fn=my_fn, key='test')

    with (
        pytest.raises(RuntimeError, match='stop immediately'),
        patch('asyncio.sleep', new=AsyncMock()),
    ):
        await wrapped()

    assert call_count == 1


@pytest.mark.asyncio
async def test_exponential_backoff() -> None:
    """Test that exponential backoff works correctly."""
    retry = Retry(
        retries=3,
        backoff_ms=100,
        backoff_factor=2.0,
        retry_on_exceptions=(ValueError,),
    )

    call_count = 0

    async def my_fn() -> str:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ValueError('retry')
        return 'done'

    wrapped = retry(fn=my_fn, key='test')

    sleep_calls: list[float] = []

    async def fake_sleep(duration: float) -> None:
        sleep_calls.append(duration)

    bound: Callable[[float], Coroutine[Any, Any, None]] = asyncio.sleep
    asyncio.sleep = fake_sleep  # type: ignore[assignment]

    try:
        result = await wrapped()
    finally:
        asyncio.sleep = bound  # type: ignore[assignment]

    assert result == 'done'
    assert sleep_calls == [0.1, 0.2]
