"""Property test for VectorMetadata completeness.

**Validates: Requirements 4.4, 11.3**

Property 7: Vector Metadata Completeness
For any valid submission_id, user_id, chunk_index, chunk_timestamp_start,
chunk_timestamp_end, and embedding_model_version, the constructed VectorMetadata
SHALL contain all six fields with values matching the inputs exactly.
"""

from hypothesis import given, settings
from hypothesis.strategies import floats, integers, text

from src.models.vector_metadata import VectorMetadata


@settings(max_examples=100, deadline=500)
@given(
    submission_id=text(min_size=1),
    user_id=text(min_size=1),
    embedding_model_version=text(min_size=1),
    chunk_index=integers(min_value=0),
    chunk_timestamp_start=floats(min_value=0.0, max_value=100000.0, allow_nan=False, allow_infinity=False),
    positive_delta=floats(min_value=0.001, max_value=100000.0, allow_nan=False, allow_infinity=False),
)
def test_vector_metadata_completeness(
    submission_id: str,
    user_id: str,
    embedding_model_version: str,
    chunk_index: int,
    chunk_timestamp_start: float,
    positive_delta: float,
) -> None:
    """Property 7: Vector Metadata Completeness.

    **Validates: Requirements 4.4, 11.3**

    Generate arbitrary valid inputs and verify VectorMetadata contains all six
    fields with exact matching values.
    """
    chunk_timestamp_end = chunk_timestamp_start + positive_delta

    metadata = VectorMetadata(
        submission_id=submission_id,
        user_id=user_id,
        chunk_index=chunk_index,
        chunk_timestamp_start=chunk_timestamp_start,
        chunk_timestamp_end=chunk_timestamp_end,
        embedding_model_version=embedding_model_version,
    )

    # Assert all six fields match input values exactly
    assert metadata.submission_id == submission_id
    assert metadata.user_id == user_id
    assert metadata.chunk_index == chunk_index
    assert metadata.chunk_timestamp_start == chunk_timestamp_start
    assert metadata.chunk_timestamp_end == chunk_timestamp_end
    assert metadata.embedding_model_version == embedding_model_version
