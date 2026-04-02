from app.security import SlidingWindowRateLimiter


def test_sliding_window_limiter_blocks_after_threshold():
    limiter = SlidingWindowRateLimiter(max_attempts=2, window_seconds=60)
    key = "127.0.0.1:user@example.com"

    assert limiter.is_limited(key) is False
    limiter.record_failure(key)
    assert limiter.is_limited(key) is False

    limiter.record_failure(key)
    assert limiter.is_limited(key) is True
    assert limiter.retry_after_seconds(key) > 0


def test_sliding_window_reset_clears_limit():
    limiter = SlidingWindowRateLimiter(max_attempts=1, window_seconds=60)
    key = "127.0.0.1:user@example.com"

    limiter.record_failure(key)
    assert limiter.is_limited(key) is True

    limiter.reset(key)
    assert limiter.is_limited(key) is False
    assert limiter.retry_after_seconds(key) == 0
