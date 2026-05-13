import pytest

from app.security import SlidingWindowRateLimiter


@pytest.mark.asyncio
async def test_sliding_window_limiter_blocks_after_threshold():
    limiter = SlidingWindowRateLimiter(max_attempts=2, window_seconds=60)
    key = "127.0.0.1:user@example.com"

    assert await limiter.is_limited(key) is False
    await limiter.record_failure(key)
    assert await limiter.is_limited(key) is False

    await limiter.record_failure(key)
    assert await limiter.is_limited(key) is True
    assert await limiter.retry_after_seconds(key) > 0


@pytest.mark.asyncio
async def test_sliding_window_reset_clears_limit():
    limiter = SlidingWindowRateLimiter(max_attempts=1, window_seconds=60)
    key = "127.0.0.1:user@example.com"

    await limiter.record_failure(key)
    assert await limiter.is_limited(key) is True

    await limiter.reset(key)
    assert await limiter.is_limited(key) is False
    assert await limiter.retry_after_seconds(key) == 0
