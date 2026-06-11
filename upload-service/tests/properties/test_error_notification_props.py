# Feature: upload-and-storage, Property 10: SNS error notification construction
"""
Property-based tests for SNS error notification construction.

**Validates: Requirements 8.2**

For any valid combination of error notification inputs (submission_id, error_type,
error_message, timestamp, service_component, orphaned_s3_key), the constructed
ErrorNotification should contain all required fields with values matching the inputs,
and the timestamp should be a valid ISO 8601 string.
"""

from datetime import datetime, timezone

from hypothesis import given, settings
from hypothesis import strategies as st

from src.models.submission import ErrorNotification, ErrorType


# Strategy for generating valid ISO 8601 timestamps
iso8601_timestamps = st.datetimes(
    min_value=datetime(2000, 1, 1),
    max_value=datetime(2100, 1, 1),
    timezones=st.just(timezone.utc),
).map(lambda dt: dt.isoformat())


@settings(max_examples=100)
@given(
    submission_id=st.none() | st.text(min_size=1),
    error_type=st.sampled_from(ErrorType),
    error_message=st.text(min_size=1),
    timestamp=iso8601_timestamps,
    service_component=st.text(min_size=1),
    orphaned_s3_key=st.none() | st.text(min_size=1),
)
def test_error_notification_has_all_required_fields(
    submission_id: str | None,
    error_type: ErrorType,
    error_message: str,
    timestamp: str,
    service_component: str,
    orphaned_s3_key: str | None,
) -> None:
    """All required fields are present in the constructed ErrorNotification."""
    notification = ErrorNotification(
        submission_id=submission_id,
        error_type=error_type,
        error_message=error_message,
        timestamp=timestamp,
        service_component=service_component,
        orphaned_s3_key=orphaned_s3_key,
    )

    # All required fields must be present
    assert hasattr(notification, "submission_id")
    assert hasattr(notification, "error_type")
    assert hasattr(notification, "error_message")
    assert hasattr(notification, "timestamp")
    assert hasattr(notification, "service_component")
    assert hasattr(notification, "orphaned_s3_key")


@settings(max_examples=100)
@given(
    submission_id=st.none() | st.text(min_size=1),
    error_type=st.sampled_from(ErrorType),
    error_message=st.text(min_size=1),
    timestamp=iso8601_timestamps,
    service_component=st.text(min_size=1),
    orphaned_s3_key=st.none() | st.text(min_size=1),
)
def test_error_notification_values_match_inputs(
    submission_id: str | None,
    error_type: ErrorType,
    error_message: str,
    timestamp: str,
    service_component: str,
    orphaned_s3_key: str | None,
) -> None:
    """All field values in the constructed ErrorNotification match the provided inputs."""
    notification = ErrorNotification(
        submission_id=submission_id,
        error_type=error_type,
        error_message=error_message,
        timestamp=timestamp,
        service_component=service_component,
        orphaned_s3_key=orphaned_s3_key,
    )

    assert notification.submission_id == submission_id
    assert notification.error_type == error_type
    assert notification.error_message == error_message
    assert notification.timestamp == timestamp
    assert notification.service_component == service_component
    assert notification.orphaned_s3_key == orphaned_s3_key


@settings(max_examples=100)
@given(
    submission_id=st.none() | st.text(min_size=1),
    error_type=st.sampled_from(ErrorType),
    error_message=st.text(min_size=1),
    timestamp=iso8601_timestamps,
    service_component=st.text(min_size=1),
    orphaned_s3_key=st.none() | st.text(min_size=1),
)
def test_error_notification_timestamp_is_valid_iso8601(
    submission_id: str | None,
    error_type: ErrorType,
    error_message: str,
    timestamp: str,
    service_component: str,
    orphaned_s3_key: str | None,
) -> None:
    """The timestamp field is a valid ISO 8601 string."""
    notification = ErrorNotification(
        submission_id=submission_id,
        error_type=error_type,
        error_message=error_message,
        timestamp=timestamp,
        service_component=service_component,
        orphaned_s3_key=orphaned_s3_key,
    )

    # Timestamp must be parseable as ISO 8601
    parsed = datetime.fromisoformat(notification.timestamp)
    assert parsed is not None
    assert parsed.tzinfo is not None  # Must include timezone info
