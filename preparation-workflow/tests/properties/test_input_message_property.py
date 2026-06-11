"""Property test for InputMessage round-trip serialization.

Property 1: Message Parsing Round-Trip
Validates: Requirements 1.2

For any valid InputMessage with arbitrary non-empty string values,
serializing to JSON and deserializing back produces an identical message.
"""

import pytest
from hypothesis import given, settings
from hypothesis.strategies import text

from src.models.input_message import InputMessage

# Strategy for generating non-empty strings (min_length=1 matches the model constraint)
non_empty_text = text(min_size=1)


@pytest.mark.property
@settings(max_examples=100, deadline=500)
@given(
    submission_id=non_empty_text,
    user_id=non_empty_text,
    s3_bucket=non_empty_text,
    s3_file_key=non_empty_text,
    original_file_name=non_empty_text,
    presentation_title=non_empty_text,
)
def test_input_message_round_trip(
    submission_id: str,
    user_id: str,
    s3_bucket: str,
    s3_file_key: str,
    original_file_name: str,
    presentation_title: str,
) -> None:
    """**Validates: Requirements 1.2**

    For any valid InputMessage with arbitrary string values for all fields,
    serializing the message to JSON and then deserializing it back SHALL
    produce an identical InputMessage with all fields preserved exactly.
    """
    original = InputMessage(
        submission_id=submission_id,
        user_id=user_id,
        s3_bucket=s3_bucket,
        s3_file_key=s3_file_key,
        original_file_name=original_file_name,
        presentation_title=presentation_title,
    )

    # Serialize to JSON and deserialize back
    json_str = original.model_dump_json()
    restored = InputMessage.model_validate_json(json_str)

    # Assert round-trip produces identical message
    assert restored == original
    assert restored.submission_id == submission_id
    assert restored.user_id == user_id
    assert restored.s3_bucket == s3_bucket
    assert restored.s3_file_key == s3_file_key
    assert restored.original_file_name == original_file_name
    assert restored.presentation_title == presentation_title
