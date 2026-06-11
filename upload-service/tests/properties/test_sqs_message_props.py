# Feature: upload-and-storage, Property 6: SQS message body construction
"""Property-based tests for SQS message body construction.

Validates: Requirements 5.2
"""
from hypothesis import given, settings
from hypothesis import strategies as st

from src.models.sqs_message import SqsMessageBody

# Strategies
non_empty_text = st.text(min_size=1)


@settings(max_examples=100)
@given(
    submission_id=non_empty_text,
    user_id=non_empty_text,
    s3_file_key=non_empty_text,
    original_file_name=non_empty_text,
    presentation_title=non_empty_text,
)
def test_sqs_message_body_contains_all_fields(
    submission_id: str,
    user_id: str,
    s3_file_key: str,
    original_file_name: str,
    presentation_title: str,
) -> None:
    """Constructed SqsMessageBody must contain all 5 required fields with values matching inputs exactly.

    **Validates: Requirements 5.2**
    """
    message = SqsMessageBody(
        submission_id=submission_id,
        user_id=user_id,
        s3_file_key=s3_file_key,
        original_file_name=original_file_name,
        presentation_title=presentation_title,
    )

    # Assert all fields are present
    assert hasattr(message, "submission_id")
    assert hasattr(message, "user_id")
    assert hasattr(message, "s3_file_key")
    assert hasattr(message, "original_file_name")
    assert hasattr(message, "presentation_title")

    # Assert each value matches the input exactly
    assert message.submission_id == submission_id
    assert message.user_id == user_id
    assert message.s3_file_key == s3_file_key
    assert message.original_file_name == original_file_name
    assert message.presentation_title == presentation_title
