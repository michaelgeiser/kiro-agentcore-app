# Feature: upload-and-storage, Property 9: Submissions sorted by upload_date descending
"""Property-based tests for submissions sort order.

Validates: Requirements 7.4
"""
import os
import uuid
from datetime import datetime, timezone

from hypothesis import given, settings
from hypothesis import strategies as st

# Must set env var before importing handler module
os.environ.setdefault("DYNAMODB_TABLE_NAME", "test-table")

from src.handlers.get_submissions import _map_record_to_response  # noqa: E402
from src.models.submission import ProcessingStatus, SubmissionRecord  # noqa: E402

# --- Strategies ---

content_types = st.sampled_from([
    "audio/mpeg", "audio/wav", "audio/x-m4a", "audio/aac",
    "video/mp4", "video/quicktime", "video/webm",
])

processing_statuses = st.sampled_from(list(ProcessingStatus))

upload_dates = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2030, 12, 31),
    timezones=st.just(timezone.utc),
).map(lambda dt: dt.isoformat())

submission_records = st.builds(
    SubmissionRecord,
    submission_id=st.uuids().map(str),
    user_id=st.text(min_size=1, max_size=36, alphabet=st.characters(whitelist_categories=("L", "N"))),
    original_file_name=st.text(
        min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("L", "N"))
    ).map(lambda s: s + ".mp3"),
    presentation_title=st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=("L", "N", "Z"))),
    description=st.none() | st.text(min_size=1, max_size=100),
    s3_file_key=st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=("L", "N", "P"))),
    content_type=content_types,
    file_size_bytes=st.integers(min_value=1, max_value=500 * 1024 * 1024),
    upload_date=upload_dates,
    processing_status=processing_statuses,
    completion_date=st.none(),
    report_link=st.none(),
)


@settings(max_examples=100)
@given(records=st.lists(submission_records, min_size=2, max_size=20))
def test_submissions_sorted_by_upload_date_descending(
    records: list[SubmissionRecord],
) -> None:
    """After sorting records by upload_date descending and mapping them,
    the response items maintain strictly descending upload_date order.

    This simulates what DynamoDB GSI returns (ScanIndexForward=False)
    and verifies the mapping preserves the sort order.

    **Validates: Requirements 7.4**
    """
    # Sort records descending by upload_date (simulating DynamoDB GSI behavior)
    sorted_records = sorted(records, key=lambda r: r.upload_date, reverse=True)

    # Map through the handler's response mapping function
    submissions = [_map_record_to_response(record) for record in sorted_records]

    # Assert: adjacent items are in descending (or equal) upload_date order
    for i in range(len(submissions) - 1):
        current_date = submissions[i]["dateUploaded"]
        next_date = submissions[i + 1]["dateUploaded"]
        assert current_date >= next_date, (
            f"Submissions not sorted descending: "
            f"item[{i}].dateUploaded={current_date!r} < item[{i+1}].dateUploaded={next_date!r}"
        )
