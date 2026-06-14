"""Unit tests for batch processor service.

Tests group_into_batches and process_batches with single chunk,
batch_size=1, and batch_size > chunk_count scenarios.

Requirements: 10.1, 10.2
"""

import math
from unittest.mock import MagicMock

import pytest

from models.audio_chunk import AudioChunk
from models.embedding_result import EmbeddingResult
from services.batch_processor import group_into_batches, process_batches


def _make_audio_chunk(
    chunk_index: int = 0,
    submission_id: str = "sub-001",
    user_id: str = "user-001",
) -> AudioChunk:
    """Helper to create an AudioChunk for testing."""
    start = chunk_index * 30.0
    end = (chunk_index + 1) * 30.0
    return AudioChunk(
        chunk_index=chunk_index,
        s3_chunk_key=f"processed/{user_id}/{submission_id}/chunks/chunk_{chunk_index:04d}.mp3",
        timestamp_start_seconds=start,
        timestamp_end_seconds=end,
        submission_id=submission_id,
        user_id=user_id,
    )


def _make_chunks(count: int) -> list[AudioChunk]:
    """Create a list of sequential audio chunks."""
    return [_make_audio_chunk(chunk_index=i) for i in range(count)]


def _mock_process_fn(chunk: AudioChunk) -> EmbeddingResult:
    """A simple mock processing function that returns an EmbeddingResult."""
    return EmbeddingResult(
        submission_id=chunk.submission_id,
        user_id=chunk.user_id,
        chunk_index=chunk.chunk_index,
        chunk_timestamp_start=chunk.timestamp_start_seconds,
        chunk_timestamp_end=chunk.timestamp_end_seconds,
        embedding_vector=[float(chunk.chunk_index) * 0.1],
        embedding_model_version="test-model-v1",
    )


class TestGroupIntoBatches:
    """Tests for group_into_batches function."""

    def test_single_chunk(self):
        """A single chunk produces one batch containing that chunk."""
        chunks = _make_chunks(1)
        batches = group_into_batches(chunks, batch_size=5)

        assert len(batches) == 1
        assert len(batches[0]) == 1
        assert batches[0][0].chunk_index == 0

    def test_batch_size_equals_one(self):
        """batch_size=1 produces one batch per chunk."""
        chunks = _make_chunks(4)
        batches = group_into_batches(chunks, batch_size=1)

        assert len(batches) == 4
        for i, batch in enumerate(batches):
            assert len(batch) == 1
            assert batch[0].chunk_index == i

    def test_batch_size_greater_than_chunk_count(self):
        """When batch_size > number of chunks, all chunks fit in one batch."""
        chunks = _make_chunks(3)
        batches = group_into_batches(chunks, batch_size=10)

        assert len(batches) == 1
        assert len(batches[0]) == 3
        for i, chunk in enumerate(batches[0]):
            assert chunk.chunk_index == i

    def test_exact_multiple_of_batch_size(self):
        """When chunk count is exact multiple of batch_size, no partial batch."""
        chunks = _make_chunks(6)
        batches = group_into_batches(chunks, batch_size=3)

        assert len(batches) == 2
        assert len(batches[0]) == 3
        assert len(batches[1]) == 3

    def test_non_exact_multiple_produces_partial_last_batch(self):
        """When chunk count is not a multiple, last batch is partial."""
        chunks = _make_chunks(5)
        batches = group_into_batches(chunks, batch_size=2)

        assert len(batches) == 3
        assert len(batches[0]) == 2
        assert len(batches[1]) == 2
        assert len(batches[2]) == 1

    def test_preserves_chunk_order(self):
        """Chunks within and across batches maintain original order."""
        chunks = _make_chunks(7)
        batches = group_into_batches(chunks, batch_size=3)

        flat = [chunk for batch in batches for chunk in batch]
        for i, chunk in enumerate(flat):
            assert chunk.chunk_index == i

    def test_produces_correct_batch_count(self):
        """Number of batches equals ceil(chunk_count / batch_size)."""
        chunks = _make_chunks(10)
        batch_size = 3
        batches = group_into_batches(chunks, batch_size)

        expected_count = math.ceil(len(chunks) / batch_size)
        assert len(batches) == expected_count

    def test_empty_chunks_raises_value_error(self):
        """Empty chunk list raises ValueError."""
        with pytest.raises(ValueError, match="chunks list must not be empty"):
            group_into_batches([], batch_size=5)

    def test_invalid_batch_size_raises_value_error(self):
        """batch_size < 1 raises ValueError."""
        chunks = _make_chunks(2)
        with pytest.raises(ValueError, match="batch_size must be >= 1"):
            group_into_batches(chunks, batch_size=0)


class TestProcessBatches:
    """Tests for process_batches function."""

    def test_processes_single_batch(self):
        """Single batch with multiple chunks processes all chunks."""
        chunks = _make_chunks(3)
        batches = [chunks]

        results = process_batches(batches, _mock_process_fn)

        assert len(results) == 3
        for i, result in enumerate(results):
            assert result.chunk_index == i

    def test_processes_multiple_batches(self):
        """Multiple batches are processed in sequence."""
        chunks = _make_chunks(5)
        batches = group_into_batches(chunks, batch_size=2)

        results = process_batches(batches, _mock_process_fn)

        assert len(results) == 5
        for i, result in enumerate(results):
            assert result.chunk_index == i

    def test_preserves_order_across_batches(self):
        """Results maintain original chunk order across all batches."""
        chunks = _make_chunks(6)
        batches = group_into_batches(chunks, batch_size=2)

        results = process_batches(batches, _mock_process_fn)

        for i, result in enumerate(results):
            assert result.chunk_index == i
            assert result.embedding_vector == [float(i) * 0.1]

    def test_calls_process_fn_for_each_chunk(self):
        """process_fn is called exactly once per chunk."""
        chunks = _make_chunks(4)
        batches = group_into_batches(chunks, batch_size=2)
        mock_fn = MagicMock(side_effect=_mock_process_fn)

        results = process_batches(batches, mock_fn)

        assert mock_fn.call_count == 4
        assert len(results) == 4

    def test_empty_batches_returns_empty(self):
        """Empty batches list returns empty results."""
        results = process_batches([], _mock_process_fn)
        assert results == []
