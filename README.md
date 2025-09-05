# Async Rate Limiter (Sliding Window + Lua + Redis)

A Python async rate limiter using Redis and Lua with sliding window algorithm.  
Supports retries, exponential backoff, and optional exception handling.

---

## Installation

```bash
pip install redis asyncio
```

---

## Usage

### Basic usage with inline function

```python
import asyncio
import redis.asyncio as aioredis
from rate_limit_module import RateLimit  # replace with your module
from rate_limiter.exceptions import RetryLimitReached

redis_client = aioredis.Redis(host='localhost', port=6379, db=0)

rate_limit = RateLimit(
    redis=redis_client,
    limit=5,
    window=10,
    retries=3,
    backoff_ms=200,
    backoff_factor=2.0,
    retry_on_exceptions=(ValueError,),
)

async def my_task():
    print('Task executed.')
    return 42

wrapped = rate_limit(fn=my_task, key='task_key')

try:
    result = await wrapped()
    print(result)
except RetryLimitReached:
    print('All retry attempts exhausted.')
```

### Using as a decorator

```python
rate_limit = RateLimit(
    redis=redis_client,
    limit=3,
    window=5,
    retries=4,
    backoff_ms=100,
    backoff_factor=1.5,
)

@rate_limit(key='decorated_task')
async def my_decorated_task():
    print('Decorated task executed.')
    return 'done'

try:
    await my_decorated_task()
except RetryLimitReached:
    print('Rate limit retry attempts exhausted.')
```

---

## Exception behavior

After all retries are used without success, the limiter **raises `RetryLimitReached`** exception  
instead—making it easier to handle failure explicitly in your code.

---

## Features

- Sliding window rate limiting using Redis + Lua
- Async-friendly
- Retries with exponential backoff configurable
- Optional exception-based retry logic
- Raises `RetryLimitReached` when retry attempts are exhausted
- Supports both inline wrapper and decorator syntax

---

## License

MIT License
