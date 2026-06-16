"""Retry logic with exponential backoff and jitter.

Provides both a decorator and a standalone utility function for retrying
async operations with configurable exponential backoff and optional jitter.
"""

import asyncio
import functools
import logging
import random
from collections.abc import Callable
from typing import Any, TypeVar

from models.data_models import RetryConfig

logger = logging.getLogger(__name__)

T = TypeVar("T")


def _compute_delay(attempt: int, config: RetryConfig) -> float:
    """Compute the backoff delay for a given attempt number.

    Args:
        attempt: The current attempt number (1-indexed, where 1 is the first retry).
        config: Retry configuration parameters.

    Returns:
        The computed delay in seconds, capped at max_delay_seconds,
        with optional random jitter applied.
    """
    # Exponential backoff: base_delay * backoff_multiplier^(attempt - 1)
    delay = config.base_delay_seconds * (config.backoff_multiplier ** (attempt - 1))

    # Cap at max delay
    delay = min(delay, config.max_delay_seconds)

    # Add random jitter of up to 50% of the computed delay
    if config.jitter:
        jitter_amount = random.uniform(0, 0.5 * delay)  # noqa: S311
        delay += jitter_amount

    return delay


def retry_with_backoff(
    config: RetryConfig | None = None,
) -> Callable:
    """Decorator that retries an async function with exponential backoff and jitter.

    Args:
        config: Retry configuration. Uses sensible defaults if not provided.

    Returns:
        A decorator that wraps async functions with retry logic.

    Example:
        @retry_with_backoff(RetryConfig(max_attempts=5))
        async def fetch_data():
            ...

        @retry_with_backoff()
        async def store_result():
            ...
    """
    if config is None:
        config = RetryConfig()

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception: Exception | None = None

            for attempt in range(1, config.max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as exc:
                    last_exception = exc

                    if attempt >= config.max_attempts:
                        logger.error(
                            "Function '%s' failed after %d attempts. "
                            "Last error: %s: %s",
                            func.__name__,
                            config.max_attempts,
                            type(exc).__name__,
                            exc,
                        )
                        raise

                    delay = _compute_delay(attempt, config)
                    logger.warning(
                        "Function '%s' failed on attempt %d/%d "
                        "(%s: %s). Retrying in %.2f seconds...",
                        func.__name__,
                        attempt,
                        config.max_attempts,
                        type(exc).__name__,
                        exc,
                        delay,
                    )
                    await asyncio.sleep(delay)

            # This should never be reached, but satisfies type checkers
            raise last_exception  # type: ignore[misc]

        return wrapper

    return decorator


async def execute_with_retry(
    func: Callable[..., Any],
    config: RetryConfig | None = None,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Execute an async function with retry semantics.

    Non-decorator alternative for calling any async function with retry logic.

    Args:
        func: The async function to execute.
        config: Retry configuration. Uses sensible defaults if not provided.
        *args: Positional arguments to pass to the function.
        **kwargs: Keyword arguments to pass to the function.

    Returns:
        The return value of the successfully executed function.

    Raises:
        The last exception raised by the function if all retries are exhausted.

    Example:
        result = await execute_with_retry(
            fetch_data,
            RetryConfig(max_attempts=5),
            url="https://example.com",
        )
    """
    if config is None:
        config = RetryConfig()

    last_exception: Exception | None = None

    for attempt in range(1, config.max_attempts + 1):
        try:
            return await func(*args, **kwargs)
        except Exception as exc:
            last_exception = exc

            if attempt >= config.max_attempts:
                logger.error(
                    "Function '%s' failed after %d attempts. "
                    "Last error: %s: %s",
                    func.__name__,
                    config.max_attempts,
                    type(exc).__name__,
                    exc,
                )
                raise

            delay = _compute_delay(attempt, config)
            logger.warning(
                "Function '%s' failed on attempt %d/%d "
                "(%s: %s). Retrying in %.2f seconds...",
                func.__name__,
                attempt,
                config.max_attempts,
                type(exc).__name__,
                exc,
                delay,
            )
            await asyncio.sleep(delay)

    # This should never be reached, but satisfies type checkers
    raise last_exception  # type: ignore[misc]
