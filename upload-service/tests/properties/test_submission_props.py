# Feature: upload-and-storage, Property 5: Submission record construction
"""Property-based tests for submission record construction.

Validates: Requirements 4.2, 4.3
"""
import re
import uuid
from datetime import datetime, timezone

from hypothesis import given, settings
from hypothesis import strategies as st

from src.models.submission import SubmissionRecord

# UUID v4 regex pattern
UUID_V4_REGEX = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)

# Strategies
user_ids = st.text(min_size=1, alphabet=st.characters(whitelist_categories=("L", "N")))
file_names = st.text(
    min_size=1, alphabet=st.characters(whitelist_categories=("L", "N"))
).map(lambda s: s + ".mp3")
titles = st.text(min_size=1, alphabet=st.characters(whitelist_categories=("L", "N", "Z")))
descriptions = st.none() | st.text(min_size=1)
s3_keys = st.text(min_size=1, alphabet=st.characters(whitelist_categories=("L", "N", "P")))
content_types = st.sampled_from([
    "audio/mpeg", "audio/wav", "audio/x-m4a", "audio/aac",
    "video/mp4", "video/quicktime", "video/webm",
])
file_sizes = st.integers(min_value=1, max_value=500 * 1024 * 1024)
upload_dates = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2030, 12, 31),
    timezones=st.just(timezone.utc),
).map(lambda dt: dt.isoformat())


@settings(max_examples=100)
@given(
    user_id=user_ids,
    original_file_name=file_names,
    presentation_title=titles,
    description=descriptions,
    s3_file_key=s3_keys,
    content_type=content_types,
    file_size_bytes=file_sizes,
    upload_date=upload_dates,
)
def test_submission_record_defaults(
    user_id: str,
    original_file_name: str,
    presentation_title: str,
    description: str | None,
    s3_file_key: str,
    content_type: str,
    file_size_bytes: int,
    upload_date: str,
) -> None:
    """Constructed SubmissionRecord has correct defaults: processing_status is Pending,
    completion_date is None, and report_link is None.

    **Validates: Requirements 4.2, 4.3**
    """
    submission_id = str(uuid.uuid4())

    record = SubmissionRecord(
        submission_id=submission_id,
        user_id=user_id,
        original_file_name=original_file_name,
        presentation_title=presentation_title,
        description=description,
        s3_file_key=s3_file_key,
        content_type=content_type,
        file_size_bytes=file_size_bytes,
        upload_date=upload_date,
    )

    # processing_status defaults to "Pending"
    assert record.processing_status == "Pending"
    assert record.processing_status.value == "Pending"

    # completion_date defaults to None
    assert record.completion_date is None

    # report_link defaults to None
    assert record.report_link is None


@settings(max_examples=100)
@given(
    user_id=user_ids,
    original_file_name=file_names,
    presentation_title=titles,
    s3_file_key=s3_keys,
    content_type=content_types,
    file_size_bytes=file_sizes,
    upload_date=upload_dates,
)
def test_submission_id_matches_uuid_v4(
    user_id: str,
    original_file_name: str,
    presentation_title: str,
    s3_file_key: str,
    content_type: str,
    file_size_bytes: int,
    upload_date: str,
) -> None:
    """submission_id must match UUID v4 regex pattern.

    **Validates: Requirements 4.2, 4.3**
    """
    submission_id = str(uuid.uuid4())

    record = SubmissionRecord(
        submission_id=submission_id,
        user_id=user_id,
        original_file_name=original_file_name,
        presentation_title=presentation_title,
        s3_file_key=s3_file_key,
        content_type=content_type,
        file_size_bytes=file_size_bytes,
        upload_date=upload_date,
    )

    assert UUID_V4_REGEX.match(record.submission_id), (
        f"submission_id '{record.submission_id}' does not match UUID v4 format"
    )


@settings(max_examples=100)
@given(
    user_id=user_ids,
    original_file_name=file_names,
    presentation_title=titles,
    s3_file_key=s3_keys,
    content_type=content_types,
    file_size_bytes=file_sizes,
    upload_date=upload_dates,
)
def test_upload_date_is_valid_iso8601(
    user_id: str,
    original_file_name: str,
    presentation_title: str,
    s3_file_key: str,
    content_type: str,
    file_size_bytes: int,
    upload_date: str,
) -> None:
    """upload_date must be a valid ISO 8601 timestamp.

    **Validates: Requirements 4.2, 4.3**
    """
    submission_id = str(uuid.uuid4())

    record = SubmissionRecord(
        submission_id=submission_id,
        user_id=user_id,
        original_file_name=original_file_name,
        presentation_title=presentation_title,
        s3_file_key=s3_file_key,
        content_type=content_type,
        file_size_bytes=file_size_bytes,
        upload_date=upload_date,
    )

    # Verify upload_date can be parsed as ISO 8601
    parsed = datetime.fromisoformat(record.upload_date)
    assert parsed is not None
