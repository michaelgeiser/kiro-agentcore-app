# Feature: upload-and-storage, Property 8: Submission response mapping includes all fields
"""Property-based tests for submission response mapping.

Validates: Requirements 7.3
"""
import os
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

from hypothesis import given, settings
from hypothesis import strategies as st

from src.models.submission import ProcessingStatus, SubmissionRecord

# Strategies for building random SubmissionRecords
submission_ids = st.uuids().map(str)
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
processing_statuses = st.sampled_from(list(ProcessingStatus))
completion_dates = st.none() | st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2030, 12, 31),
    timezones=st.just(timezone.utc),
).map(lambda dt: dt.isoformat())
report_links = st.none() | st.text(min_size=1, alphabet=st.characters(whitelist_categories=("L", "N", "P")))

submission_records = st.builds(
    SubmissionRecord,
    submission_id=submission_ids,
    user_id=user_ids,
    original_file_name=file_names,
    presentation_title=titles,
    description=descriptions,
    s3_file_key=s3_keys,
    content_type=content_types,
    file_size_bytes=file_sizes,
    upload_date=upload_dates,
    processing_status=processing_statuses,
    completion_date=completion_dates,
    report_link=report_links,
)

# We need to set DYNAMODB_TABLE_NAME before importing the handler module,
# because DynamoService is instantiated at module level.
with patch.dict(os.environ, {"DYNAMODB_TABLE_NAME": "test-table"}):
    from src.handlers.get_submissions import _map_record_to_response


EXPECTED_KEYS = {
    "id",
    "title",
    "fileName",
    "description",
    "dateUploaded",
    "status",
    "dateCompleted",
    "reportUrl",
}


@settings(max_examples=100)
@given(record=submission_records)
def test_submission_response_mapping_includes_all_fields(
    record: SubmissionRecord,
) -> None:
    """For any SubmissionRecord, the mapped response contains exactly 8 required
    fields with values matching the source record fields.

    **Validates: Requirements 7.3**
    """
    response = _map_record_to_response(record)

    # Assert exactly the 8 required keys are present
    assert set(response.keys()) == EXPECTED_KEYS, (
        f"Expected keys {EXPECTED_KEYS}, got {set(response.keys())}"
    )

    # Assert values map correctly from the record
    assert response["id"] == record.submission_id
    assert response["title"] == record.presentation_title
    assert response["fileName"] == record.original_file_name
    assert response["description"] == record.description
    assert response["dateUploaded"] == record.upload_date
    assert response["status"] == record.processing_status.value
    assert response["dateCompleted"] == record.completion_date
    assert response["reportUrl"] == record.report_link
