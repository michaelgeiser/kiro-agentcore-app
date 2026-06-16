# Feature: agentic-evaluation, Properties 8, 11: Retry backoff and error notifications
"""Property-based tests for exponential backoff with jitter and error notification
structure compliance.

Validates: Requirements 5.4, 9.3, 11.2
"""

from datetime import datetime, timezone

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.strategies import composite
from pydantic import ValidationError

from models.data_models import ErrorNotification, RetryConfig
from services.retry import _compute_delay

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

non_empty_text = st.text(min_size=1, max_size=100)


@composite
def valid_retry_config(draw):
    """Generate a valid RetryConfig instance with realistic parameters."""
    base_delay = draw(st.floats(min_value=0.01, max_value=10.0, allow_nan=False, allow_infinity=False))
    max_delay = draw(st.floats(min_value=base_delay, max_value=120.0, allow_nan=False, allow_infinity=False))
    backoff_multiplier = draw(st.floats(min_value=1.0, max_value=5.0, allow_nan=False, allow_infinity=False))
    max_attempts = draw(st.integers(min_value=1, max_value=10))
    jitter = draw(st.booleans())

    return RetryConfig(
        max_attempts=max_attempts,
        base_delay_seconds=base_delay,
        backoff_multiplier=backoff_multiplier,
        max_delay_seconds=max_delay,
        jitter=jitter,
    )


@composite
def valid_retry_config_with_jitter(draw):
    """Generate a valid RetryConfig with jitter enabled."""
    base_delay = draw(st.floats(min_value=0.01, max_value=10.0, allow_nan=False, allow_infinity=False))
    max_delay = draw(st.floats(min_value=base_delay, max_value=120.0, allow_nan=False, allow_infinity=False))
    backoff_multiplier = draw(st.floats(min_value=1.0, max_value=5.0, allow_nan=False, allow_infinity=False))
    max_attempts = draw(st.integers(min_value=1, max_value=10))

    return RetryConfig(
        max_attempts=max_attempts,
        base_delay_seconds=base_delay,
        backoff_multiplier=backoff_multiplier,
        max_delay_seconds=max_delay,
        jitter=True,
    )


@composite
def valid_retry_config_no_jitter(draw):
    """Generate a valid RetryConfig with jitter disabled."""
    base_delay = draw(st.floats(min_value=0.01, max_value=10.0, allow_nan=False, allow_infinity=False))
    max_delay = draw(st.floats(min_value=base_delay, max_value=120.0, allow_nan=False, allow_infinity=False))
    backoff_multiplier = draw(st.floats(min_value=1.0, max_value=5.0, allow_nan=False, allow_infinity=False))
    max_attempts = draw(st.integers(min_value=1, max_value=10))

    return RetryConfig(
        max_attempts=max_attempts,
        base_delay_seconds=base_delay,
        backoff_multiplier=backoff_multiplier,
        max_delay_seconds=max_delay,
        jitter=False,
    )


# ISO 8601 timestamps strategy
iso_timestamp = st.datetimes(
    min_value=datetime(2000, 1, 1),
    max_value=datetime(2099, 12, 31),
).map(lambda dt: dt.isoformat())


@composite
def valid_error_notification(draw):
    """Generate a valid ErrorNotification instance."""
    return ErrorNotification(
        submission_id=draw(non_empty_text),
        component_name=draw(non_empty_text),
        error_type=draw(non_empty_text),
        error_message=draw(non_empty_text),
        retry_count_exhausted=draw(st.integers(min_value=0, max_value=100)),
        timestamp=draw(iso_timestamp),
    )


# ---------------------------------------------------------------------------
# Property 8: Exponential backoff with jitter
# ---------------------------------------------------------------------------


@pytest.mark.property
@settings(max_examples=100, deadline=500)
@given(config=valid_retry_config(), attempt=st.integers(min_value=1, max_value=10))
def test_backoff_delay_lower_bound(config: RetryConfig, attempt: int) -> None:
    """For any valid RetryConfig and attempt number, the computed delay
    SHALL be greater than or equal to the base_delay_seconds.

    Without jitter the minimum is the base delay (for attempt 1). With jitter,
    the delay is base * multiplier^(attempt-1) capped at max_delay, plus up
    to 50% jitter, so it is always >= base_delay for attempt >= 1.

    **Validates: Requirements 5.4**
    """
    # Clamp attempt to valid range
    attempt = min(attempt, config.max_attempts)

    delay = _compute_delay(attempt, config)

    # Delay must be non-negative
    assert delay >= 0

    # The base calculation without jitter is: base * multiplier^(attempt-1)
    # capped at max_delay. Since multiplier >= 1 and attempt >= 1,
    # the minimum possible base calculation is base_delay (at attempt=1).
    # Jitter only adds to the delay, so delay >= base_delay always holds.
    assert delay >= config.base_delay_seconds


@pytest.mark.property
@settings(max_examples=100, deadline=500)
@given(config=valid_retry_config_with_jitter(), attempt=st.integers(min_value=1, max_value=10))
def test_backoff_delay_upper_bound_with_jitter(config: RetryConfig, attempt: int) -> None:
    """For any valid RetryConfig with jitter enabled and attempt number,
    the computed delay SHALL satisfy:
    delay <= min(base * multiplier^(attempt-1), max_delay) * 1.5

    The 1.5 factor accounts for the maximum 50% jitter addition.

    **Validates: Requirements 5.4**
    """
    attempt = min(attempt, config.max_attempts)

    delay = _compute_delay(attempt, config)

    # The theoretical max is the base calculation capped at max_delay, plus 50% jitter
    base_calc = config.base_delay_seconds * (config.backoff_multiplier ** (attempt - 1))
    capped = min(base_calc, config.max_delay_seconds)
    upper_bound = capped * 1.5

    assert delay <= upper_bound


@pytest.mark.property
@settings(max_examples=100, deadline=500)
@given(config=valid_retry_config_no_jitter(), attempt=st.integers(min_value=1, max_value=10))
def test_backoff_delay_exact_without_jitter(config: RetryConfig, attempt: int) -> None:
    """For any valid RetryConfig with jitter disabled and attempt number,
    the computed delay SHALL equal exactly:
    min(base * multiplier^(attempt-1), max_delay)

    Without jitter, delay is deterministic.

    **Validates: Requirements 5.4**
    """
    attempt = min(attempt, config.max_attempts)

    delay = _compute_delay(attempt, config)

    # Exact expected value without jitter
    expected = min(
        config.base_delay_seconds * (config.backoff_multiplier ** (attempt - 1)),
        config.max_delay_seconds,
    )

    assert delay == pytest.approx(expected, rel=1e-9)


@pytest.mark.property
@settings(max_examples=100, deadline=500)
@given(config=valid_retry_config_no_jitter())
def test_backoff_delays_non_decreasing_without_jitter(config: RetryConfig) -> None:
    """For any valid RetryConfig without jitter, successive delays SHALL be
    non-decreasing (each attempt delay >= previous attempt delay).

    **Validates: Requirements 5.4**
    """
    delays = [
        _compute_delay(attempt, config)
        for attempt in range(1, config.max_attempts + 1)
    ]

    for i in range(1, len(delays)):
        assert delays[i] >= delays[i - 1], (
            f"Delay at attempt {i + 1} ({delays[i]}) < "
            f"delay at attempt {i} ({delays[i - 1]})"
        )


# ---------------------------------------------------------------------------
# Property 11: Error notification structure compliance
# ---------------------------------------------------------------------------


@pytest.mark.property
@settings(max_examples=100, deadline=500)
@given(notification=valid_error_notification())
def test_error_notification_contains_all_required_fields(
    notification: ErrorNotification,
) -> None:
    """For any valid ErrorNotification, it SHALL contain all required fields:
    submission_id, component_name, error_type, error_message,
    retry_count_exhausted, and timestamp.

    **Validates: Requirements 9.3, 11.2**
    """
    # All required fields must be present and non-empty strings (except retry_count)
    assert notification.submission_id and len(notification.submission_id) >= 1
    assert notification.component_name and len(notification.component_name) >= 1
    assert notification.error_type and len(notification.error_type) >= 1
    assert notification.error_message and len(notification.error_message) >= 1
    assert notification.retry_count_exhausted >= 0
    assert notification.timestamp and len(notification.timestamp) >= 1


@pytest.mark.property
@settings(max_examples=100, deadline=500)
@given(notification=valid_error_notification())
def test_error_notification_timestamp_is_valid_iso8601(
    notification: ErrorNotification,
) -> None:
    """For any valid ErrorNotification, the timestamp SHALL be a valid
    ISO 8601 datetime string that can be parsed without error.

    **Validates: Requirements 9.3, 11.2**
    """
    # The model's field_validator already enforces ISO 8601 on construction.
    # This test verifies the property holds: parsing the timestamp succeeds.
    ts = notification.timestamp
    parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    assert isinstance(parsed, datetime)


@pytest.mark.property
@settings(max_examples=100, deadline=500)
@given(
    submission_id=non_empty_text,
    component_name=non_empty_text,
    error_type=non_empty_text,
    error_message=non_empty_text,
    retry_count=st.integers(min_value=0, max_value=100),
    timestamp=iso_timestamp,
)
def test_error_notification_construction_from_raw_fields(
    submission_id: str,
    component_name: str,
    error_type: str,
    error_message: str,
    retry_count: int,
    timestamp: str,
) -> None:
    """For any valid error context fields, constructing an ErrorNotification
    SHALL succeed and preserve all field values exactly as provided.

    **Validates: Requirements 9.3, 11.2**
    """
    notification = ErrorNotification(
        submission_id=submission_id,
        component_name=component_name,
        error_type=error_type,
        error_message=error_message,
        retry_count_exhausted=retry_count,
        timestamp=timestamp,
    )

    assert notification.submission_id == submission_id
    assert notification.component_name == component_name
    assert notification.error_type == error_type
    assert notification.error_message == error_message
    assert notification.retry_count_exhausted == retry_count
    assert notification.timestamp == timestamp


@pytest.mark.property
@settings(max_examples=100, deadline=500)
@given(notification=valid_error_notification())
def test_error_notification_serialization_round_trip(
    notification: ErrorNotification,
) -> None:
    """For any valid ErrorNotification, serializing to JSON and deserializing
    back SHALL produce an identical ErrorNotification.

    **Validates: Requirements 9.3, 11.2**
    """
    json_str = notification.model_dump_json()
    restored = ErrorNotification.model_validate_json(json_str)

    assert restored == notification
    assert restored.submission_id == notification.submission_id
    assert restored.component_name == notification.component_name
    assert restored.error_type == notification.error_type
    assert restored.error_message == notification.error_message
    assert restored.retry_count_exhausted == notification.retry_count_exhausted
    assert restored.timestamp == notification.timestamp
