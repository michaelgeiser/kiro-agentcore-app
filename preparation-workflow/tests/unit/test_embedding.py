"""Unit tests for embedding service.

Tests create_embedding with mocked Bedrock async invocation and S3 output,
and create_embeddings_batch with both individual and batch processing modes.

Requirements: 4.1, 4.2, 10.1
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from models.audio_chunk import AudioChunk
from models.embedding_result import EmbeddingResult
from services.embedding import (
    _build_async_model_input,
    create_embedding,
    create_embeddings_batch,
)


def _make_audio_chunk(
    chunk_index: int = 0,
    submission_id: str = "sub-001",
    user_id: str = "user-001",
    start: float = 0.0,
    end: float = 30.0,
) -> AudioChunk:
    """Helper to create an AudioChunk for testing."""
    return AudioChunk(
        chunk_index=chunk_index,
        s3_chunk_key=f"processed/{user_id}/{submission_id}/chunks/chunk_{chunk_index:04d}.mp3",
        timestamp_start_seconds=start,
        timestamp_end_seconds=end,
        submission_id=submission_id,
        user_id=user_id,
    )


def _mock_bedrock_async(mock_client, embedding_vector):
    """Set up mock bedrock client for successful async invocation."""
    mock_client.start_async_invoke.return_value = {
        "invocationArn": "arn:aws:bedrock:us-east-1:123456:async-invoke/test-123"
    }
    mock_client.get_async_invoke.return_value = {
        "status": "Completed",
        "outputDataConfig": {
            "s3OutputDataConfig": {
                "s3Uri": "s3://test-bucket/embeddings-output/sub-001/chunk_0000/abc123/"
            }
        },
    }


def _mock_s3_output(mock_s3, embedding_vector):
    """Set up mock S3 client to return embedding output."""
    mock_s3.list_objects_v2.return_value = {
        "Contents": [{"Key": "embeddings-output/sub-001/chunk_0000/abc123/output.json"}]
    }
    mock_s3.get_object.return_value = {
        "Body": MagicMock(read=lambda: json.dumps({"embedding": embedding_vector}).encode())
    }


class TestBuildAsyncModelInput:
    """Tests for _build_async_model_input helper."""

    def test_constructs_s3_uri(self):
        payload = _build_async_model_input("my-bucket", "path/to/chunk.mp3")
        assert payload["inputAudio"] == "s3://my-bucket/path/to/chunk.mp3"


class TestCreateEmbedding:
    """Tests for create_embedding function with async invocation."""

    def test_successful_invocation(self):
        """Bedrock async invocation succeeds and returns an EmbeddingResult."""
        chunk = _make_audio_chunk(chunk_index=2, start=60.0, end=90.0)
        embedding_vector = [0.1, 0.2, 0.3, 0.4, 0.5]

        mock_bedrock = MagicMock()
        mock_s3 = MagicMock()
        _mock_bedrock_async(mock_bedrock, embedding_vector)
        _mock_s3_output(mock_s3, embedding_vector)

        result = create_embedding(
            audio_chunk=chunk,
            s3_bucket="test-bucket",
            embedding_model_id="amazon.nova-2-multimodal-embeddings-v1:0",
            bedrock_client=mock_bedrock,
            s3_client=mock_s3,
        )

        assert isinstance(result, EmbeddingResult)
        assert result.submission_id == "sub-001"
        assert result.user_id == "user-001"
        assert result.chunk_index == 2
        assert result.chunk_timestamp_start == 60.0
        assert result.chunk_timestamp_end == 90.0
        assert result.embedding_vector == embedding_vector
        assert result.embedding_model_version == "amazon.nova-2-multimodal-embeddings-v1:0"

    def test_passes_correct_model_id(self):
        """Verifies the correct model ID is passed to StartAsyncInvoke."""
        chunk = _make_audio_chunk()
        mock_bedrock = MagicMock()
        mock_s3 = MagicMock()
        _mock_bedrock_async(mock_bedrock, [1.0])
        _mock_s3_output(mock_s3, [1.0])

        create_embedding(
            audio_chunk=chunk,
            s3_bucket="bucket",
            embedding_model_id="my-custom-model",
            bedrock_client=mock_bedrock,
            s3_client=mock_s3,
        )

        call_kwargs = mock_bedrock.start_async_invoke.call_args[1]
        assert call_kwargs["modelId"] == "my-custom-model"

    def test_raises_runtime_error_on_bedrock_failure(self):
        """Bedrock StartAsyncInvoke raises an exception."""
        chunk = _make_audio_chunk()
        mock_bedrock = MagicMock()
        mock_s3 = MagicMock()
        mock_bedrock.start_async_invoke.side_effect = Exception("ValidationException")

        with pytest.raises(RuntimeError, match="Bedrock async invocation failed"):
            create_embedding(
                audio_chunk=chunk,
                s3_bucket="bucket",
                embedding_model_id="model-id",
                bedrock_client=mock_bedrock,
                s3_client=mock_s3,
            )

    def test_raises_on_failed_status(self):
        """Bedrock async invocation returns Failed status."""
        chunk = _make_audio_chunk()
        mock_bedrock = MagicMock()
        mock_s3 = MagicMock()
        mock_bedrock.start_async_invoke.return_value = {
            "invocationArn": "arn:aws:bedrock:us-east-1:123:async-invoke/fail-123"
        }
        mock_bedrock.get_async_invoke.return_value = {
            "status": "Failed",
            "failureMessage": "Invalid model input",
        }

        with pytest.raises(RuntimeError, match="Bedrock async invocation failed"):
            create_embedding(
                audio_chunk=chunk,
                s3_bucket="bucket",
                embedding_model_id="model-id",
                bedrock_client=mock_bedrock,
                s3_client=mock_s3,
            )

    def test_maps_chunk_metadata_correctly(self):
        """Verifies that AudioChunk fields map to EmbeddingResult fields."""
        chunk = AudioChunk(
            chunk_index=5,
            s3_chunk_key="processed/userA/subB/chunks/chunk_0005.mp3",
            timestamp_start_seconds=150.0,
            timestamp_end_seconds=180.0,
            submission_id="subB",
            user_id="userA",
        )
        mock_bedrock = MagicMock()
        mock_s3 = MagicMock()
        _mock_bedrock_async(mock_bedrock, [0.5, 0.6])
        _mock_s3_output(mock_s3, [0.5, 0.6])

        result = create_embedding(
            audio_chunk=chunk,
            s3_bucket="bucket",
            embedding_model_id="embed-model-v2",
            bedrock_client=mock_bedrock,
            s3_client=mock_s3,
        )

        assert result.submission_id == "subB"
        assert result.user_id == "userA"
        assert result.chunk_index == 5
        assert result.chunk_timestamp_start == 150.0
        assert result.chunk_timestamp_end == 180.0
        assert result.embedding_model_version == "embed-model-v2"


class TestCreateEmbeddingsBatch:
    """Tests for create_embeddings_batch function."""

    def _make_chunks(self, count: int) -> list[AudioChunk]:
        """Create a list of sequential audio chunks."""
        chunks = []
        for i in range(count):
            start = i * 30.0
            end = (i + 1) * 30.0
            chunks.append(_make_audio_chunk(chunk_index=i, start=start, end=end))
        return chunks

    def _setup_mocks(self, count: int):
        """Set up bedrock and s3 mocks for multiple invocations."""
        mock_bedrock = MagicMock()
        mock_s3 = MagicMock()

        mock_bedrock.start_async_invoke.return_value = {
            "invocationArn": "arn:aws:bedrock:us-east-1:123:async-invoke/batch-123"
        }
        mock_bedrock.get_async_invoke.return_value = {
            "status": "Completed",
            "outputDataConfig": {
                "s3OutputDataConfig": {
                    "s3Uri": "s3://bucket/output/"
                }
            },
        }
        mock_s3.list_objects_v2.return_value = {
            "Contents": [{"Key": "output/result.json"}]
        }

        # Return different embeddings for each call
        embedding_responses = [
            json.dumps({"embedding": [float(i) + 0.1]}).encode()
            for i in range(count)
        ]
        mock_s3.get_object.side_effect = [
            {"Body": MagicMock(read=lambda b=body: b)}
            for body in embedding_responses
        ]

        return mock_bedrock, mock_s3

    def test_individual_processing(self):
        """When batch_processing_enabled=False, processes chunks individually."""
        chunks = self._make_chunks(3)
        mock_bedrock, mock_s3 = self._setup_mocks(3)

        results = create_embeddings_batch(
            audio_chunks=chunks,
            s3_bucket="bucket",
            embedding_model_id="model-id",
            batch_processing_enabled=False,
            bedrock_client=mock_bedrock,
            s3_client=mock_s3,
        )

        assert len(results) == 3
        assert results[0].chunk_index == 0
        assert results[1].chunk_index == 1
        assert results[2].chunk_index == 2
        assert mock_bedrock.start_async_invoke.call_count == 3

    def test_single_chunk(self):
        """Processing a single chunk works."""
        chunks = self._make_chunks(1)
        mock_bedrock, mock_s3 = self._setup_mocks(1)

        results = create_embeddings_batch(
            audio_chunks=chunks,
            s3_bucket="bucket",
            embedding_model_id="model-id",
            batch_processing_enabled=False,
            bedrock_client=mock_bedrock,
            s3_client=mock_s3,
        )

        assert len(results) == 1
        assert results[0].chunk_index == 0
