# Async Rate Limiter (Sliding Window + Lua + Redis)

A Python async rate limiter using Redis and Lua with sliding window algorithm.
Supports retries, exponential backoff, and optional exception handling.


---

## Usage

### Basic usage with inline function

```python
import asyncio
import redis.asyncio as aioredis
from rate_limit_module import RateLimit  # replace with your module

redis_client = aioredis.Redis(host='localhost', port=6379, db=0)

rate_limit = RateLimit(redis=redis_client, limit=5, window=10)

async def main():
    async def my_task():
        print("Task executed")
        return 42

    wrapped = rate_limit(fn=my_task, key="my_task_key")
    result = await wrapped()
    print(result)

asyncio.run(main())
```

---

### Using as a decorator

```python
rate_limit = RateLimit(redis=redis_client, limit=3, window=5)

@rate_limit(key="decorated_task")
async def my_decorated_task():
    print("Decorated task executed")
    return "done"

asyncio.run(my_decorated_task())
```

---

### Handling exceptions with retries

```python
rate_limit = RateLimit(
    redis=redis_client,
    limit=2,
    window=10,
    retry_on_exceptions=(ValueError,),
    backoff_ms=200,
    backoff_factor=2
)

@rate_limit(key="task_with_retry")
async def risky_task():
    # may raise ValueError
    ...
```

---

## Features

- Sliding window rate limiting using Redis + Lua
- Async-friendly
- Supports retries with exponential backoff
- Optional exception handling for retries
- Works as inline wrapper or decorator

---

## Installation

```bash
    pip install rate-limiter-decorator
```

---

## Tests

```bash
    poetry run pytest tests
```
---

## License

MIT License
