"""Property test for audio chunking correctness.

Property 6: Audio Chunking Correctness
Validates: Requirements 4.3

For any audio duration (> 0), chunk size (> 0), and overlap (>= 0, < chunk_size),
calculate_chunks SHALL produce chunks where:
(a) the first chunk starts at timestamp 0,
(b) the last chunk ends at or after the total audio duration,
(c) consecutive chunks overlap by exactly the configured overlap amount,
(d) no audio content is skipped between chunks.
"""

import pytest
from hypothesis import given, settings, assume
from hypothesis.strategies import floats, integers, composite

from src.services.chunking import calculate_chunks


@composite
def chunking_params(draw):
    """Generate valid chunking parameters.

    Produces (total_duration, chunk_size, chunk_overlap) where:
    - total_duration > 0
    - chunk_size >= 1
    - 0 <= chunk_overlap < chunk_size
    """
    total_duration = draw(floats(min_value=0.1, max_value=10000.0, allow_nan=False, allow_infinity=False))
    chunk_size = draw(integers(min_value=1, max_value=300))
    chunk_overlap = draw(integers(min_value=0, max_value=chunk_size - 1))
    return total_duration, chunk_size, chunk_overlap


@pytest.mark.property
@settings(max_examples=100, deadline=500)
@given(params=chunking_params())
def test_first_chunk_starts_at_zero(params: tuple) -> None:
    """**Validates: Requirements 4.3**

    For any valid chunking parameters, the first chunk SHALL start at timestamp 0.
    """
    total_duration, chunk_size, chunk_overlap = params
    chunks = calculate_chunks(total_duration, chunk_size, chunk_overlap)

    assert len(chunks) >= 1
    assert chunks[0][0] == 0.0


@pytest.mark.property
@settings(max_examples=100, deadline=500)
@given(params=chunking_params())
def test_last_chunk_covers_end(params: tuple) -> None:
    """**Validates: Requirements 4.3**

    For any valid chunking parameters, the last chunk SHALL end at or after
    the total audio duration.
    """
    total_duration, chunk_size, chunk_overlap = params
    chunks = calculate_chunks(total_duration, chunk_size, chunk_overlap)

    assert chunks[-1][1] >= total_duration


@pytest.mark.property
@settings(max_examples=100, deadline=500)
@given(params=chunking_params())
def test_consecutive_chunks_overlap_correctly(params: tuple) -> None:
    """**Validates: Requirements 4.3**

    For any valid chunking parameters, consecutive chunks SHALL have their start
    positions separated by exactly (chunk_size - overlap).
    """
    total_duration, chunk_size, chunk_overlap = params
    chunks = calculate_chunks(total_duration, chunk_size, chunk_overlap)

    step_size = chunk_size - chunk_overlap
    for i in range(len(chunks) - 1):
        expected_next_start = chunks[i][0] + step_size
        assert abs(chunks[i + 1][0] - expected_next_start) < 1e-9, (
            f"Chunk {i+1} start {chunks[i+1][0]} != expected {expected_next_start}"
        )


@pytest.mark.property
@settings(max_examples=100, deadline=500)
@given(params=chunking_params())
def test_no_gaps_between_chunks(params: tuple) -> None:
    """**Validates: Requirements 4.3**

    For any valid chunking parameters, there SHALL be no gaps between consecutive
    chunks — each subsequent chunk's start must be at or before the previous chunk's end.
    """
    total_duration, chunk_size, chunk_overlap = params
    chunks = calculate_chunks(total_duration, chunk_size, chunk_overlap)

    for i in range(len(chunks) - 1):
        assert chunks[i + 1][0] <= chunks[i][1], (
            f"Gap detected: chunk {i} ends at {chunks[i][1]} but chunk {i+1} starts at {chunks[i+1][0]}"
        )


@pytest.mark.property
@settings(max_examples=100, deadline=500)
@given(params=chunking_params())
def test_at_least_one_chunk_produced(params: tuple) -> None:
    """**Validates: Requirements 4.3**

    For any valid chunking parameters with duration > 0,
    at least one chunk SHALL be produced.
    """
    total_duration, chunk_size, chunk_overlap = params
    chunks = calculate_chunks(total_duration, chunk_size, chunk_overlap)

    assert len(chunks) >= 1
