"""Unit tests for the retry service.

Tests retry logic including first-attempt success, retries exhausted,
backoff timing, decorator usage, and jitter behavior.

Requirements: 5.4, 6.6
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from models.data_models import RetryConfig
from services.retry import _compute_delay, execute_with_retry, retry_with_backoff


class TestComputeDelay:
    """Tests for the _compute_delay helper function."""

    def test_first_attempt_returns_base_delay(self):
        """First attempt delay equals the base delay (multiplier^0 = 1)."""
        config = RetryConfig(base_delay_seconds=1.0, backoff_multiplier=2.0, jitter=False)
        assert _compute_delay(1, config) == 1.0

    def test_second_attempt_applies_multiplier(self):
        """Second attempt delay is base * multiplier^1."""
        config = RetryConfig(base_delay_seconds=1.0, backoff_multiplier=2.0, jitter=False)
        assert _compute_delay(2, config) == 2.0

    def test_third_attempt_applies_multiplier_squared(self):
        """Third attempt delay is base * multiplier^2."""
        config = RetryConfig(base_delay_seconds=1.0, backoff_multiplier=2.0, jitter=False)
        assert _compute_delay(3, config) == 4.0

    def test_delay_capped_at_max(self):
        """Delay is capped at max_delay_seconds regardless of computation."""
        config = RetryConfig(
            base_delay_seconds=10.0,
            backoff_multiplier=10.0,
            max_delay_seconds=5.0,
            jitter=False,
        )
        # 10 * 10^2 = 1000, but capped at 5.0
        assert _compute_delay(3, config) == 5.0

    def test_jitter_adds_up_to_50_percent(self):
        """Jitter adds between 0 and 50% of the computed delay."""
        config = RetryConfig(base_delay_seconds=2.0, backoff_multiplier=2.0, jitter=True)
        # Attempt 1: base delay = 2.0, with jitter: 2.0 to 3.0
        delays = [_compute_delay(1, config) for _ in range(200)]
        assert all(2.0 <= d <= 3.0 for d in delays)
        # Verify jitter produces varying values
        assert len(set(delays)) > 1

    def test_no_jitter_produces_deterministic_delay(self):
        """Without jitter, delay is deterministic."""
        config = RetryConfig(base_delay_seconds=1.5, backoff_multiplier=3.0, jitter=False)
        delays = [_compute_delay(2, config) for _ in range(10)]
        assert all(d == 4.5 for d in delays)

    def test_custom_backoff_multiplier(self):
        """Custom backoff multiplier is applied correctly."""
        config = RetryConfig(base_delay_seconds=1.0, backoff_multiplier=3.0, jitter=False)
        assert _compute_delay(1, config) == 1.0
        assert _compute_delay(2, config) == 3.0
        assert _compute_delay(3, config) == 9.0


class TestExecuteWithRetry:
    """Tests for execute_with_retry standalone function."""

    @pytest.mark.asyncio
    async def test_success_on_first_attempt(self):
        """Function succeeds on first attempt without retries."""
        func = AsyncMock(return_value="result")
        config = RetryConfig(max_attempts=3, base_delay_seconds=0.01, jitter=False)

        result = await execute_with_retry(func, config)

        assert result == "result"
        assert func.call_count == 1

    @pytest.mark.asyncio
    async def test_success_after_retries(self):
        """Function succeeds after initial failures."""
        func = AsyncMock(side_effect=[ValueError("fail1"), ValueError("fail2"), "ok"])
        config = RetryConfig(max_attempts=3, base_delay_seconds=0.01, jitter=False)

        result = await execute_with_retry(func, config)

        assert result == "ok"
        assert func.call_count == 3

    @pytest.mark.asyncio
    async def test_raises_after_all_retries_exhausted(self):
        """Last exception is re-raised when all retries are exhausted."""
        func = AsyncMock(side_effect=RuntimeError("persistent failure"))
        config = RetryConfig(max_attempts=3, base_delay_seconds=0.01, jitter=False)

        with pytest.raises(RuntimeError, match="persistent failure"):
            await execute_with_retry(func, config)

        assert func.call_count == 3

    @pytest.mark.asyncio
    async def test_passes_args_and_kwargs(self):
        """Arguments and keyword arguments are forwarded to the function."""
        func = AsyncMock(return_value="done")
        config = RetryConfig(max_attempts=1)

        await execute_with_retry(func, config, "arg1", "arg2", key="value")

        func.assert_called_once_with("arg1", "arg2", key="value")

    @pytest.mark.asyncio
    async def test_uses_default_config_when_none(self):
        """Default RetryConfig is used when config is None."""
        func = AsyncMock(return_value="ok")

        result = await execute_with_retry(func, None)

        assert result == "ok"
        func.assert_called_once()

    @pytest.mark.asyncio
    async def test_respects_max_attempts_of_one(self):
        """With max_attempts=1, no retry occurs."""
        func = AsyncMock(side_effect=ValueError("fail"))
        config = RetryConfig(max_attempts=1, base_delay_seconds=0.01)

        with pytest.raises(ValueError, match="fail"):
            await execute_with_retry(func, config)

        assert func.call_count == 1

    @pytest.mark.asyncio
    async def test_backoff_timing_increases(self):
        """Delays between retries increase exponentially."""
        sleep_calls = []

        async def mock_sleep(seconds):
            sleep_calls.append(seconds)

        func = AsyncMock(side_effect=[ValueError("e1"), ValueError("e2"), ValueError("e3")])
        config = RetryConfig(
            max_attempts=3, base_delay_seconds=1.0, backoff_multiplier=2.0, jitter=False
        )

        with patch("src.services.retry.asyncio.sleep", side_effect=mock_sleep):
            with pytest.raises(ValueError):
                await execute_with_retry(func, config)

        # attempt 1 failed → delay = 1.0 * 2^0 = 1.0
        # attempt 2 failed → delay = 1.0 * 2^1 = 2.0
        assert sleep_calls == [1.0, 2.0]


class TestRetryWithBackoffDecorator:
    """Tests for the retry_with_backoff decorator."""

    @pytest.mark.asyncio
    async def test_decorator_success_on_first_attempt(self):
        """Decorated function succeeds without retries."""

        @retry_with_backoff(RetryConfig(max_attempts=3, base_delay_seconds=0.01))
        async def always_succeeds():
            return "hello"

        result = await always_succeeds()
        assert result == "hello"

    @pytest.mark.asyncio
    async def test_decorator_retries_on_failure(self):
        """Decorated function retries and eventually succeeds."""
        call_count = 0

        @retry_with_backoff(RetryConfig(max_attempts=3, base_delay_seconds=0.01, jitter=False))
        async def eventual_success():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError(f"attempt {call_count}")
            return "finally"

        result = await eventual_success()
        assert result == "finally"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_decorator_raises_after_exhaustion(self):
        """Decorated function raises after all attempts fail."""

        @retry_with_backoff(RetryConfig(max_attempts=2, base_delay_seconds=0.01, jitter=False))
        async def always_fails():
            raise IOError("disk full")

        with pytest.raises(IOError, match="disk full"):
            await always_fails()

    @pytest.mark.asyncio
    async def test_decorator_preserves_function_name(self):
        """Decorator preserves the original function name."""

        @retry_with_backoff(RetryConfig(max_attempts=1))
        async def my_function():
            return True

        assert my_function.__name__ == "my_function"

    @pytest.mark.asyncio
    async def test_decorator_with_default_config(self):
        """Decorator works with default config (no arguments)."""

        @retry_with_backoff()
        async def simple():
            return 42

        result = await simple()
        assert result == 42

    @pytest.mark.asyncio
    async def test_decorator_with_arguments(self):
        """Decorated function receives arguments correctly."""

        @retry_with_backoff(RetryConfig(max_attempts=1))
        async def add(a, b, offset=0):
            return a + b + offset

        result = await add(3, 4, offset=1)
        assert result == 8
