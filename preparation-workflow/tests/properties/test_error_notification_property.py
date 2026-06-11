"""Property-based test for WorkflowErrorNotification completeness.

**Validates: Requirements 6.4, 9.2**

Property 8: Error Notification Completeness
For any failure context with submission_id, step_name, error_type, error_message,
retry_count_exhausted, and timestamp, the constructed WorkflowErrorNotification
SHALL contain all required fields, and the timestamp SHALL be in valid ISO 8601 format.
"""

from datetime import datetime, timezone

from hypothesis import given, settings
from hypothesis import strategies as st

from src.models.error_notification import WorkflowErrorNotification


# Strategy: non-empty strings for required text fields
non_empty_text = st.text(min_size=1, max_size=100).filter(lambda s: s.strip())

# Strategy: non-negative integers for retry_count_exhausted
non_negative_int = st.integers(min_value=0, max_value=1000)

# Strategy: generate valid ISO 8601 timestamps from datetime objects
iso8601_timestamps = st.datetimes(
    min_value=datetime(2000, 1, 1),
    max_value=datetime(2100, 1, 1),
    timezones=st.just(timezone.utc),
).map(lambda dt: dt.isoformat())

# Strategy: optional queue_name (None or non-empty string)
optional_queue_name = st.one_of(st.none(), non_empty_text)


@settings(max_examples=100, deadline=500)
@given(
    submission_id=non_empty_text,
    step_name=non_empty_text,
    error_type=non_empty_text,
    error_message=non_empty_text,
    retry_count_exhausted=non_negative_int,
    timestamp=iso8601_timestamps,
    queue_name=optional_queue_name,
)
def test_error_notification_completeness(
    submission_id: str,
    step_name: str,
    error_type: str,
    error_message: str,
    retry_count_exhausted: int,
    timestamp: str,
    queue_name: str | None,
) -> None:
    """Property 8: Error Notification Completeness.

    Validates: Requirements 6.4, 9.2

    For any failure context, the constructed WorkflowErrorNotification SHALL
    contain all required fields with matching values, and the timestamp SHALL
    be in valid ISO 8601 format.
    """
    notification = WorkflowErrorNotification(
        submission_id=submission_id,
        step_name=step_name,
        error_type=error_type,
        error_message=error_message,
        retry_count_exhausted=retry_count_exhausted,
        timestamp=timestamp,
        queue_name=queue_name,
    )

    # Assert all required fields match exactly
    assert notification.submission_id == submission_id
    assert notification.step_name == step_name
    assert notification.error_type == error_type
    assert notification.error_message == error_message
    assert notification.retry_count_exhausted == retry_count_exhausted
    assert notification.timestamp == timestamp
    assert notification.queue_name == queue_name

    # Validate that the timestamp is valid ISO 8601
    parsed = datetime.fromisoformat(notification.timestamp.replace("Z", "+00:00"))
    assert isinstance(parsed, datetime)
