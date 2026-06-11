"""Property test for batch grouping correctness.

Property 10: Batch Grouping Correctness
Validates: Requirements 10.1, 10.2

For any list of audio chunks (length >= 1) and batch_size (>= 1),
group_into_batches SHALL produce exactly ceil(len(chunks) / batch_size) batches,
each batch SHALL contain at most batch_size chunks, all chunks SHALL appear in
exactly one batch, and chunk order SHALL be preserved.
"""

import math

import pytest
from hypothesis import given, settings
from hypothesis.strategies import integers, composite, lists

from src.models.audio_chunk import AudioChunk
from src.services.batch_processor import group_into_batches


def make_audio_chunk(index: int) -> AudioChunk:
    """Build an AudioChunk with the given index for testing."""
    return AudioChunk(
        chunk_index=index,
        s3_chunk_key=f"chunks/user1/sub1/chunk_{index}.wav",
        timestamp_start_seconds=float(index * 10),
        timestamp_end_seconds=float(index * 10 + 10),
        submission_id="sub-001",
        user_id="user-001",
    )


@composite
def batch_params(draw):
    """Generate valid batch grouping parameters.

    Produces (chunks, batch_size) where:
    - chunks is a list of AudioChunk objects with length >= 1 (up to 100)
    - batch_size is an integer >= 1 (up to 50)
    """
    chunk_count = draw(integers(min_value=1, max_value=100))
    batch_size = draw(integers(min_value=1, max_value=50))
    chunks = [make_audio_chunk(i) for i in range(chunk_count)]
    return chunks, batch_size


@pytest.mark.property
@settings(max_examples=100, deadline=500)
@given(params=batch_params())
def test_correct_number_of_batches(params: tuple) -> None:
    """**Validates: Requirements 10.1, 10.2**

    For any valid chunk list and batch_size, group_into_batches SHALL produce
    exactly ceil(chunk_count / batch_size) batches.
    """
    chunks, batch_size = params
    batches = group_into_batches(chunks, batch_size)

    expected_batch_count = math.ceil(len(chunks) / batch_size)
    assert len(batches) == expected_batch_count, (
        f"Expected {expected_batch_count} batches, got {len(batches)}"
    )


@pytest.mark.property
@settings(max_examples=100, deadline=500)
@given(params=batch_params())
def test_each_batch_at_most_batch_size(params: tuple) -> None:
    """**Validates: Requirements 10.1, 10.2**

    For any valid chunk list and batch_size, each batch SHALL contain
    at most batch_size chunks.
    """
    chunks, batch_size = params
    batches = group_into_batches(chunks, batch_size)

    for i, batch in enumerate(batches):
        assert len(batch) <= batch_size, (
            f"Batch {i} has {len(batch)} chunks, exceeds batch_size {batch_size}"
        )


@pytest.mark.property
@settings(max_examples=100, deadline=500)
@given(params=batch_params())
def test_all_chunks_appear_exactly_once(params: tuple) -> None:
    """**Validates: Requirements 10.1, 10.2**

    For any valid chunk list and batch_size, flattening all batches SHALL
    produce a list identical to the original chunks (all appear exactly once).
    """
    chunks, batch_size = params
    batches = group_into_batches(chunks, batch_size)

    flattened = [chunk for batch in batches for chunk in batch]
    assert len(flattened) == len(chunks), (
        f"Flattened has {len(flattened)} chunks, expected {len(chunks)}"
    )
    assert flattened == chunks, "Flattened batches do not match original chunk list"


@pytest.mark.property
@settings(max_examples=100, deadline=500)
@given(params=batch_params())
def test_order_preserved(params: tuple) -> None:
    """**Validates: Requirements 10.1, 10.2**

    For any valid chunk list and batch_size, the chunk_index values in the
    flattened result SHALL be strictly increasing.
    """
    chunks, batch_size = params
    batches = group_into_batches(chunks, batch_size)

    flattened = [chunk for batch in batches for chunk in batch]
    indices = [chunk.chunk_index for chunk in flattened]

    for i in range(len(indices) - 1):
        assert indices[i] < indices[i + 1], (
            f"Order not preserved: chunk_index {indices[i]} at position {i} "
            f"is not less than {indices[i + 1]} at position {i + 1}"
        )
