"""Unit tests for audio chunking service.

Tests calculate_chunks and chunk_audio with edge cases including:
- Audio shorter than chunk size
- Exact multiple of step size
- Zero overlap
- Standard overlap
- Very short and very long audio

Requirements: 4.2, 4.3
"""

import pytest

from models.audio_chunk import AudioChunk
from services.chunking import calculate_chunks, chunk_audio


class TestCalculateChunks:
    """Tests for calculate_chunks function."""

    def test_audio_shorter_than_chunk_size(self):
        """Audio shorter than chunk_size produces 1 chunk covering full duration."""
        chunks = calculate_chunks(
            total_duration_seconds=10.0,
            chunk_size_seconds=30,
            chunk_overlap_seconds=5,
        )
        assert len(chunks) == 1
        assert chunks[0][0] == 0.0
        # The chunk end should be chunk_size (30) since it extends beyond duration
        assert chunks[0][1] >= 10.0

    def test_audio_exactly_equal_to_chunk_size_no_overlap(self):
        """Audio exactly equal to chunk_size with zero overlap produces 1 chunk."""
        chunks = calculate_chunks(
            total_duration_seconds=30.0,
            chunk_size_seconds=30,
            chunk_overlap_seconds=0,
        )
        assert len(chunks) == 1
        assert chunks[0] == (0.0, 30.0)

    def test_audio_exact_multiple_of_step_size(self):
        """Audio that is an exact multiple of step_size produces correct number of chunks."""
        # step_size = chunk_size - overlap = 30 - 10 = 20
        # total = 60, so starts: 0, 20, 40 → 3 chunks
        chunks = calculate_chunks(
            total_duration_seconds=60.0,
            chunk_size_seconds=30,
            chunk_overlap_seconds=10,
        )
        assert len(chunks) == 3
        assert chunks[0] == (0.0, 30.0)
        assert chunks[1] == (20.0, 50.0)
        assert chunks[2] == (40.0, 70.0)

    def test_zero_overlap(self):
        """Zero overlap produces non-overlapping chunks."""
        # step_size = 30 - 0 = 30
        # total = 90, starts: 0, 30, 60 → 3 chunks
        chunks = calculate_chunks(
            total_duration_seconds=90.0,
            chunk_size_seconds=30,
            chunk_overlap_seconds=0,
        )
        assert len(chunks) == 3
        assert chunks[0] == (0.0, 30.0)
        assert chunks[1] == (30.0, 60.0)
        assert chunks[2] == (60.0, 90.0)

    def test_zero_overlap_no_gap(self):
        """With zero overlap, chunks are contiguous with no gaps."""
        chunks = calculate_chunks(
            total_duration_seconds=90.0,
            chunk_size_seconds=30,
            chunk_overlap_seconds=0,
        )
        for i in range(len(chunks) - 1):
            # Next chunk starts where previous chunk ends
            assert chunks[i + 1][0] == chunks[i][1]

    def test_standard_overlap_correct_boundaries(self):
        """Standard overlap produces correct start/end boundaries."""
        # step_size = 30 - 5 = 25
        # total = 100, starts: 0, 25, 50, 75 → 4 chunks
        chunks = calculate_chunks(
            total_duration_seconds=100.0,
            chunk_size_seconds=30,
            chunk_overlap_seconds=5,
        )
        assert len(chunks) == 4
        assert chunks[0] == (0.0, 30.0)
        assert chunks[1] == (25.0, 55.0)
        assert chunks[2] == (50.0, 80.0)
        assert chunks[3] == (75.0, 105.0)

    def test_consecutive_overlap_amount(self):
        """Consecutive chunks overlap by exactly the configured overlap amount."""
        overlap = 10
        chunk_size = 30
        chunks = calculate_chunks(
            total_duration_seconds=100.0,
            chunk_size_seconds=chunk_size,
            chunk_overlap_seconds=overlap,
        )
        for i in range(len(chunks) - 1):
            # Overlap = end of chunk[i] - start of chunk[i+1]
            actual_overlap = chunks[i][1] - chunks[i + 1][0]
            assert actual_overlap == overlap

    def test_first_chunk_starts_at_zero(self):
        """First chunk always starts at 0."""
        chunks = calculate_chunks(
            total_duration_seconds=120.0,
            chunk_size_seconds=30,
            chunk_overlap_seconds=5,
        )
        assert chunks[0][0] == 0.0

    def test_last_chunk_covers_total_duration(self):
        """Last chunk end is at or beyond total duration."""
        chunks = calculate_chunks(
            total_duration_seconds=45.0,
            chunk_size_seconds=30,
            chunk_overlap_seconds=5,
        )
        assert chunks[-1][1] >= 45.0

    def test_invalid_total_duration_zero(self):
        """Zero duration raises ValueError."""
        with pytest.raises(ValueError, match="total_duration_seconds must be > 0"):
            calculate_chunks(
                total_duration_seconds=0.0,
                chunk_size_seconds=30,
                chunk_overlap_seconds=5,
            )

    def test_invalid_total_duration_negative(self):
        """Negative duration raises ValueError."""
        with pytest.raises(ValueError, match="total_duration_seconds must be > 0"):
            calculate_chunks(
                total_duration_seconds=-10.0,
                chunk_size_seconds=30,
                chunk_overlap_seconds=5,
            )

    def test_invalid_chunk_size_zero(self):
        """Zero chunk_size raises ValueError."""
        with pytest.raises(ValueError, match="chunk_size_seconds must be > 0"):
            calculate_chunks(
                total_duration_seconds=60.0,
                chunk_size_seconds=0,
                chunk_overlap_seconds=0,
            )

    def test_invalid_overlap_negative(self):
        """Negative overlap raises ValueError."""
        with pytest.raises(ValueError, match="chunk_overlap_seconds must be >= 0"):
            calculate_chunks(
                total_duration_seconds=60.0,
                chunk_size_seconds=30,
                chunk_overlap_seconds=-1,
            )

    def test_invalid_overlap_equals_chunk_size(self):
        """Overlap equal to chunk_size raises ValueError."""
        with pytest.raises(
            ValueError, match="chunk_overlap_seconds must be < chunk_size_seconds"
        ):
            calculate_chunks(
                total_duration_seconds=60.0,
                chunk_size_seconds=30,
                chunk_overlap_seconds=30,
            )


class TestChunkAudio:
    """Tests for chunk_audio function."""

    def test_audio_chunks_have_correct_fields(self):
        """Verify AudioChunk objects have all required fields."""
        chunks = chunk_audio(
            s3_bucket="my-bucket",
            s3_audio_key="processed/user1/sub1/audio.mp3",
            submission_id="sub1",
            user_id="user1",
            chunk_size_seconds=30,
            chunk_overlap_seconds=5,
            total_duration_seconds=60.0,
        )

        for chunk in chunks:
            assert isinstance(chunk, AudioChunk)
            assert hasattr(chunk, "chunk_index")
            assert hasattr(chunk, "s3_chunk_key")
            assert hasattr(chunk, "timestamp_start_seconds")
            assert hasattr(chunk, "timestamp_end_seconds")
            assert hasattr(chunk, "submission_id")
            assert hasattr(chunk, "user_id")

    def test_s3_keys_follow_pattern(self):
        """Verify S3 keys follow pattern: processed/{user_id}/{submission_id}/chunks/chunk_{index:04d}.mp3"""
        chunks = chunk_audio(
            s3_bucket="bucket",
            s3_audio_key="processed/userA/subB/audio.mp3",
            submission_id="subB",
            user_id="userA",
            chunk_size_seconds=30,
            chunk_overlap_seconds=5,
            total_duration_seconds=80.0,
        )

        for i, chunk in enumerate(chunks):
            expected_key = f"processed/userA/subB/chunks/chunk_{i:04d}.mp3"
            assert chunk.s3_chunk_key == expected_key

    def test_chunk_index_sequential_from_zero(self):
        """Verify chunk_index is sequential starting from 0."""
        chunks = chunk_audio(
            s3_bucket="bucket",
            s3_audio_key="processed/u/s/audio.mp3",
            submission_id="s",
            user_id="u",
            chunk_size_seconds=30,
            chunk_overlap_seconds=10,
            total_duration_seconds=100.0,
        )

        for i, chunk in enumerate(chunks):
            assert chunk.chunk_index == i

    def test_submission_id_preserved(self):
        """Verify submission_id is set correctly on all chunks."""
        chunks = chunk_audio(
            s3_bucket="bucket",
            s3_audio_key="audio.mp3",
            submission_id="my-submission-123",
            user_id="my-user",
            chunk_size_seconds=30,
            chunk_overlap_seconds=0,
            total_duration_seconds=60.0,
        )

        for chunk in chunks:
            assert chunk.submission_id == "my-submission-123"
            assert chunk.user_id == "my-user"

    def test_very_short_audio(self):
        """Very short audio (0.5s with 30s chunk_size) produces 1 chunk."""
        chunks = chunk_audio(
            s3_bucket="bucket",
            s3_audio_key="processed/u/s/audio.mp3",
            submission_id="s",
            user_id="u",
            chunk_size_seconds=30,
            chunk_overlap_seconds=5,
            total_duration_seconds=0.5,
        )

        assert len(chunks) == 1
        assert chunks[0].chunk_index == 0
        assert chunks[0].timestamp_start_seconds == 0.0
        assert chunks[0].timestamp_end_seconds >= 0.5

    def test_very_long_audio(self):
        """Very long audio (3600s / 1 hour) produces many chunks correctly."""
        chunks = chunk_audio(
            s3_bucket="bucket",
            s3_audio_key="processed/u/s/audio.mp3",
            submission_id="s",
            user_id="u",
            chunk_size_seconds=30,
            chunk_overlap_seconds=5,
            total_duration_seconds=3600.0,
        )

        # step_size = 30 - 5 = 25, number of chunks = ceil(3600 / 25) = 144
        assert len(chunks) == 144
        assert chunks[0].chunk_index == 0
        assert chunks[-1].chunk_index == 143
        # Last chunk should cover the full duration
        assert chunks[-1].timestamp_end_seconds >= 3600.0

    def test_zero_overlap_chunks(self):
        """Zero overlap produces non-overlapping chunks."""
        chunks = chunk_audio(
            s3_bucket="bucket",
            s3_audio_key="processed/u/s/audio.mp3",
            submission_id="s",
            user_id="u",
            chunk_size_seconds=30,
            chunk_overlap_seconds=0,
            total_duration_seconds=90.0,
        )

        assert len(chunks) == 3
        assert chunks[0].timestamp_start_seconds == 0.0
        assert chunks[0].timestamp_end_seconds == 30.0
        assert chunks[1].timestamp_start_seconds == 30.0
        assert chunks[1].timestamp_end_seconds == 60.0
        assert chunks[2].timestamp_start_seconds == 60.0
        assert chunks[2].timestamp_end_seconds == 90.0
