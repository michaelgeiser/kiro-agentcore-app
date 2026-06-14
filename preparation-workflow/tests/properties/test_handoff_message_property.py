# Feature: preparation-workflow, Property 9: Handoff message completeness
"""Property-based tests for HandoffMessage completeness.

Validates: Requirements 7.3
"""
from hypothesis import given, settings
from hypothesis import strategies as st

from models.handoff_message import HandoffMessage

# Strategies
non_empty_text = st.text(min_size=1)
positive_int = st.integers(min_value=1)


@settings(max_examples=100, deadline=500)
@given(
    submission_id=non_empty_text,
    user_id=non_empty_text,
    s3_file_key=non_empty_text,
    vector_store_location=non_empty_text,
    chunk_count=positive_int,
    presentation_title=non_empty_text,
)
def test_handoff_message_contains_all_fields(
    submission_id: str,
    user_id: str,
    s3_file_key: str,
    vector_store_location: str,
    chunk_count: int,
    presentation_title: str,
) -> None:
    """Constructed HandoffMessage must contain all 6 required fields with values matching inputs exactly.

    **Validates: Requirements 7.3**
    """
    message = HandoffMessage(
        submission_id=submission_id,
        user_id=user_id,
        s3_file_key=s3_file_key,
        vector_store_location=vector_store_location,
        chunk_count=chunk_count,
        presentation_title=presentation_title,
    )

    # Assert all fields are present
    assert hasattr(message, "submission_id")
    assert hasattr(message, "user_id")
    assert hasattr(message, "s3_file_key")
    assert hasattr(message, "vector_store_location")
    assert hasattr(message, "chunk_count")
    assert hasattr(message, "presentation_title")

    # Assert each value matches the input exactly
    assert message.submission_id == submission_id
    assert message.user_id == user_id
    assert message.s3_file_key == s3_file_key
    assert message.vector_store_location == vector_store_location
    assert message.chunk_count == chunk_count
    assert message.presentation_title == presentation_title
