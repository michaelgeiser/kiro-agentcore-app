"""Property test for invalid message rejection.

Property 2: Invalid Message Rejection
Validates: Requirements 1.4

For any JSON object that is missing one or more required fields,
the parse_message function SHALL reject the input and return an error result.
"""

import json

import pytest
from hypothesis import given, settings
from hypothesis.strategies import composite, sets, sampled_from, text

from src.handlers.parse_message import parse_message

# All required fields for a valid InputMessage
REQUIRED_FIELDS = [
    "submission_id",
    "user_id",
    "s3_bucket",
    "s3_file_key",
    "original_file_name",
    "presentation_title",
]

# Strategy for generating non-empty strings (valid field values)
non_empty_text = text(min_size=1)


@composite
def incomplete_message(draw):
    """Generate a JSON object with one or more required fields missing.

    Strategy: build a full valid dict, then randomly remove 1+ fields.
    """
    # Build a complete valid message
    full_message = {
        "submission_id": draw(non_empty_text),
        "user_id": draw(non_empty_text),
        "s3_bucket": draw(non_empty_text),
        "s3_file_key": draw(non_empty_text),
        "original_file_name": draw(non_empty_text),
        "presentation_title": draw(non_empty_text),
    }

    # Randomly select 1 or more fields to remove
    fields_to_remove = draw(
        sets(sampled_from(REQUIRED_FIELDS), min_size=1)
    )

    # Remove selected fields
    for field in fields_to_remove:
        del full_message[field]

    return full_message


@pytest.mark.property
@settings(max_examples=100, deadline=500)
@given(message_dict=incomplete_message())
def test_invalid_message_rejection(message_dict: dict) -> None:
    """**Validates: Requirements 1.4**

    For any JSON object that is missing one or more required fields
    (submission_id, user_id, s3_bucket, s3_file_key, original_file_name,
    presentation_title), the parse_message function SHALL reject the input
    and return an error result rather than a valid InputMessage.
    """
    message_body = json.dumps(message_dict)
    result = parse_message(message_body)

    assert result["valid"] is False
    assert "error" in result
    assert isinstance(result["error"], str)
    assert len(result["error"]) > 0
