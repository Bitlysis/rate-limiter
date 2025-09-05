import logging
from unittest.mock import AsyncMock, Mock, patch

import pytest

from rate_limiter import RateLimit
from rate_limiter.exceptions import RetryLimitReached


@pytest.mark.asyncio
async def test_successful_execution():
    """Test that the function executes successfully when limit is not reached."""
    redis_mock = Mock()
    lua_mock = AsyncMock()
    lua_mock.return_value = [0, 1]  # allowed
    redis_mock.register_script.return_value = lua_mock

    rate_limit = RateLimit(redis=redis_mock, limit=5, window=10)

    executed = False

    async def my_fn():
        nonlocal executed
        executed = True
        return 42

    wrapped = rate_limit(fn=my_fn, key='test')
    result = await wrapped()
    assert executed
    assert result == 42

@pytest.mark.asyncio
async def test_rate_limit_hit_with_retry():
    """Test that retries are triggered when the rate limit is hit."""
    redis_mock = Mock()
    lua_mock = AsyncMock()
    lua_mock.side_effect = [[1, 0], [2, 0], [3, 1]]  # first two blocked, third allowed
    redis_mock.register_script.return_value = lua_mock

    rate_limit = RateLimit(redis=redis_mock, limit=1, window=10, backoff_ms=100, backoff_factor=1)

    executed = False

    async def my_fn():
        nonlocal executed
        executed = True
        return "done"

    with patch("asyncio.sleep", new=AsyncMock()) as sleep_mock:
        wrapped = rate_limit(fn=my_fn, key='test')
        result = await wrapped()

    assert executed
    assert result == "done"
    assert sleep_mock.call_count == 2  # two retries before allowed

@pytest.mark.asyncio
async def test_retry_on_exceptions_logged(caplog):
    """Test that exceptions in retry_on_exceptions are logged and retried."""
    redis_mock = Mock()
    lua_mock = AsyncMock()
    lua_mock.return_value = [0, 1]
    redis_mock.register_script.return_value = lua_mock

    rate_limit = RateLimit(
        redis=redis_mock,
        limit=1,
        window=10,
        retry_on_exceptions=(ValueError,),
        backoff_ms=100,
        backoff_factor=1
    )

    async def my_fn():
        raise ValueError("retry me")

    wrapped = rate_limit(fn=my_fn, key='test')
    caplog.set_level(logging.WARNING)
    with (
        pytest.raises(RetryLimitReached),
        patch("asyncio.sleep", new=AsyncMock()),
    ):
        result = await wrapped()

        assert result is None
        assert any('retrying' in r.message for r in caplog.records)

@pytest.mark.asyncio
async def test_unhandled_exception_stops():
    """Test that unhandled exceptions immediately stop the limiter."""
    redis_mock = Mock()
    lua_mock = AsyncMock()
    lua_mock.return_value = [0, 1]
    redis_mock.register_script.return_value = lua_mock

    rate_limit = RateLimit(redis=redis_mock, limit=1, window=10)

    async def my_fn():
        raise RuntimeError("stop")

    wrapped = rate_limit(fn=my_fn, key='test')
    with patch("asyncio.sleep", new=AsyncMock()):
        with pytest.raises(RuntimeError):
            await wrapped()

@pytest.mark.asyncio
async def test_decorator_syntax_usage():
    """Test using the RateLimit object as a decorator with @ syntax."""
    redis_mock = Mock()
    lua_mock = AsyncMock()
    lua_mock.return_value = [0, 1]
    redis_mock.register_script.return_value = lua_mock

    rate_limit = RateLimit(redis=redis_mock, limit=1, window=10)

    executed = False

    @rate_limit(key='test')
    async def my_fn():
        nonlocal executed
        executed = True
        return 'ok'

    with patch("asyncio.sleep", new=AsyncMock()):
        result = await my_fn()

    assert executed
    assert result == 'ok'

@pytest.mark.asyncio
async def test_exponential_backoff_calls():
    """Test that exponential backoff is applied correctly for rate-limited calls."""
    redis_mock = Mock()
    lua_mock = AsyncMock()
    # Lua initially blocks all calls, then allows execution
    lua_mock.side_effect = [[1, 0], [2, 0], [3, 0], [4, 1], [5, 1]]
    redis_mock.register_script.return_value = lua_mock

    rate_limit = RateLimit(
        redis=redis_mock,
        limit=1,
        window=10,
        retries=5,
        backoff_ms=100,
        backoff_factor=2
    )

    call_order = []

    async def my_fn():
        call_order.append("executed")
        return "done"

    wrapped = rate_limit(fn=my_fn, key='test')

    sleep_calls = []

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)

    with patch("asyncio.sleep", new=fake_sleep):
        result = await wrapped()

    assert result == "done"
    # Verify exponential backoff for attempts **before success**
    expected_delays = [0.1, 0.2, 0.4]  # only 3 delays before allowed call
    assert sleep_calls == expected_delays
    assert call_order == ["executed"]
