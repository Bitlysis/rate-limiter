# Async Rate Limiter (Sliding Window + Lua + Redis)

A Python async rate limiter using Redis and Lua with sliding window algorithm.
Now with **decoupled rate limiting and retry logic** for maximum flexibility.

---

## Installation

```bash
pip install redis asyncio
```

---

## Usage

### Basic Rate Limiting

```python
import redis.asyncio as aioredis
from rate_limiter import RateLimit

redis_client = aioredis.Redis(host='localhost', port=6379, db=0)

rate_limit = RateLimit(
    redis=redis_client,
    limit=5,
    window=10,  # 5 requests per 10 seconds
)

async def my_task():
    print('Task executed.')
    return 42

# Inline wrapper
wrapped = rate_limit(fn=my_task, key='task_key')
result = await wrapped()

# Or as decorator
@rate_limit(key='decorated_task')
async def my_decorated_task():
    print('Decorated task executed.')
    return 'done'

await my_decorated_task()
```

### Basic Retry Logic

```python
from rate_limiter import Retry
from rate_limiter.exceptions import RetryLimitReachedError

retry = Retry(
    retries=3,
    backoff_ms=200,
    backoff_factor=2.0,
    retry_on_exceptions=(ValueError,),
)

async def flaky_task():
    # Might raise ValueError
    return 'success'

wrapped = retry(fn=flaky_task, key='flaky_key')

try:
    result = await wrapped()
except RetryLimitReachedError:
    print('All retry attempts exhausted.')
```

### Combining Rate Limiting and Retry

You can compose both wrappers for advanced use cases:

```python
from rate_limiter import RateLimit, Retry
from rate_limiter.exceptions import RetryLimitReachedError

redis_client = aioredis.Redis(host='localhost', port=6379, db=0)

rate_limit = RateLimit(redis=redis_client, limit=5, window=10)
retry = Retry(
    retries=3,
    backoff_ms=100,
    backoff_factor=2.0,
    retry_on_exceptions=(ValueError, ConnectionError),
)

async def my_task():
    # Task that needs both rate limiting and retry logic
    return 'result'

# Apply rate limiting first, then retry logic
rate_limited = rate_limit(fn=my_task, key='task_key')
wrapped = retry(fn=rate_limited, key='task_key')

try:
    result = await wrapped()
except RetryLimitReachedError:
    print('Failed after all retries')
```

### Advanced: Manual Rate Limit Checks

```python
from rate_limiter import RateLimit

rate_limit = RateLimit(redis=redis_client, limit=10, window=60)

# Check if allowed without waiting
allowed, wait_ms = await rate_limit.is_allowed('my_key')
if not allowed:
    print(f'Rate limited. Wait {wait_ms}ms')

# Wait until allowed (blocks if needed)
await rate_limit.wait_until_allowed('my_key')
# Now safe to proceed
```

---

## Architecture

### RateLimit
- **Purpose**: Enforce rate limits using Redis with sliding window algorithm
- **Behavior**: Automatically waits if rate limit is exceeded
- **Parameters**:
  - `redis`: Redis async client
  - `limit`: Max requests allowed in the window
  - `window`: Time window in seconds

### Retry
- **Purpose**: Retry failed operations with exponential backoff
- **Behavior**: Retries on specified exceptions, raises `RetryLimitReachedError` when exhausted
- **Parameters**:
  - `retries`: Number of retry attempts
  - `backoff_ms`: Initial backoff delay in milliseconds
  - `backoff_factor`: Exponential backoff multiplier
  - `retry_on_exceptions`: Tuple of exception types that trigger retries

---

## Features

- **Decoupled architecture**: Use rate limiting and retry independently or together
- Sliding window rate limiting using Redis + Lua (atomic operations)
- Async-friendly with asyncio
- Retries with configurable exponential backoff
- Optional exception-based retry logic
- Supports both inline wrapper and decorator syntax
- Manual rate limit checks for advanced use cases

---

## Exception Behavior

- **RateLimit**: Does not raise exceptions; waits automatically when limit is exceeded
- **Retry**: Raises `RetryLimitReachedError` when all retry attempts are exhausted
- Unhandled exceptions in wrapped functions propagate immediately

---

## License

MIT License
