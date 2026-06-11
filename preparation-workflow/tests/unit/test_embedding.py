"""Unit tests for embedding service.

Tests create_embedding with mocked Bedrock responses and
create_embeddings_batch with both individual and batch processing modes.

Requirements: 4.1, 4.2, 10.1
"""

import io
import json
from unittest.mock import MagicMock

import pytest

from src.models.audio_chunk import AudioChunk
from src.models.embedding_result import EmbeddingResult
from src.services.embedding import (
    _build_invoke_payload,
    _parse_embedding_response,
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


def _mock_bedrock_response(embedding: list[float]) -> MagicMock:
    """Create a mock Bedrock response with the given embedding vector."""
    response_body = json.dumps({"embedding": embedding}).encode("utf-8")
    mock_response = {
        "body": io.BytesIO(response_body),
    }
    return mock_response


class TestBuildInvokePayload:
    """Tests for _build_invoke_payload helper."""

    def test_constructs_s3_uri(self):
        payload = _build_invoke_payload("my-bucket", "path/to/chunk.mp3")
        assert payload["inputAudio"] == "s3://my-bucket/path/to/chunk.mp3"

    def test_text_and_image_are_none(self):
        payload = _build_invoke_payload("bucket", "key")
        assert payload["inputText"] is None
        assert payload["inputImage"] is None


class TestParseEmbeddingResponse:
    """Tests for _parse_embedding_response helper."""

    def test_parses_valid_response(self):
        body = json.dumps({"embedding": [0.1, 0.2, 0.3]}).encode("utf-8")
        result = _parse_embedding_response(body)
        assert result == [0.1, 0.2, 0.3]

    def test_raises_on_missing_embedding_field(self):
        body = json.dumps({"result": "something"}).encode("utf-8")
        with pytest.raises(ValueError, match="does not contain an 'embedding' field"):
            _parse_embedding_response(body)

    def test_raises_on_empty_embedding_list(self):
        body = json.dumps({"embedding": []}).encode("utf-8")
        with pytest.raises(ValueError, match="not a non-empty list"):
            _parse_embedding_response(body)

    def test_raises_on_non_list_embedding(self):
        body = json.dumps({"embedding": "not-a-list"}).encode("utf-8")
        with pytest.raises(ValueError, match="not a non-empty list"):
            _parse_embedding_response(body)


class TestCreateEmbedding:
    """Tests for create_embedding function."""

    def test_successful_invocation(self):
        """Bedrock invocation succeeds and returns an EmbeddingResult."""
        chunk = _make_audio_chunk(chunk_index=2, start=60.0, end=90.0)
        embedding_vector = [0.1, 0.2, 0.3, 0.4, 0.5]

        mock_client = MagicMock()
        mock_client.invoke_model.return_value = _mock_bedrock_response(embedding_vector)

        result = create_embedding(
            audio_chunk=chunk,
            s3_bucket="test-bucket",
            embedding_model_id="amazon.titan-embed-image-v1",
            bedrock_client=mock_client,
        )

        assert isinstance(result, EmbeddingResult)
        assert result.submission_id == "sub-001"
        assert result.user_id == "user-001"
        assert result.chunk_index == 2
        assert result.chunk_timestamp_start == 60.0
        assert result.chunk_timestamp_end == 90.0
        assert result.embedding_vector == embedding_vector
        assert result.embedding_model_version == "amazon.titan-embed-image-v1"

    def test_passes_correct_model_id(self):
        """Verifies the correct model ID is passed to Bedrock."""
        chunk = _make_audio_chunk()
        mock_client = MagicMock()
        mock_client.invoke_model.return_value = _mock_bedrock_response([1.0])

        create_embedding(
            audio_chunk=chunk,
            s3_bucket="bucket",
            embedding_model_id="my-custom-model",
            bedrock_client=mock_client,
        )

        call_kwargs = mock_client.invoke_model.call_args[1]
        assert call_kwargs["modelId"] == "my-custom-model"

    def test_passes_correct_payload(self):
        """Verifies the S3 URI is correctly included in the request body."""
        chunk = _make_audio_chunk()
        mock_client = MagicMock()
        mock_client.invoke_model.return_value = _mock_bedrock_response([1.0])

        create_embedding(
            audio_chunk=chunk,
            s3_bucket="my-bucket",
            embedding_model_id="model-id",
            bedrock_client=mock_client,
        )

        call_kwargs = mock_client.invoke_model.call_args[1]
        body = json.loads(call_kwargs["body"])
        expected_uri = f"s3://my-bucket/{chunk.s3_chunk_key}"
        assert body["inputAudio"] == expected_uri

    def test_raises_runtime_error_on_bedrock_failure(self):
        """Bedrock invocation raises an exception."""
        chunk = _make_audio_chunk()
        mock_client = MagicMock()
        mock_client.invoke_model.side_effect = Exception("Throttling")

        with pytest.raises(RuntimeError, match="Bedrock invocation failed"):
            create_embedding(
                audio_chunk=chunk,
                s3_bucket="bucket",
                embedding_model_id="model-id",
                bedrock_client=mock_client,
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
        mock_client = MagicMock()
        mock_client.invoke_model.return_value = _mock_bedrock_response([0.5, 0.6])

        result = create_embedding(
            audio_chunk=chunk,
            s3_bucket="bucket",
            embedding_model_id="embed-model-v2",
            bedrock_client=mock_client,
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

    def test_individual_processing(self):
        """When batch_processing_enabled=False, processes chunks individually."""
        chunks = self._make_chunks(3)
        mock_client = MagicMock()
        mock_client.invoke_model.side_effect = [
            _mock_bedrock_response([0.1, 0.2]),
            _mock_bedrock_response([0.3, 0.4]),
            _mock_bedrock_response([0.5, 0.6]),
        ]

        results = create_embeddings_batch(
            audio_chunks=chunks,
            s3_bucket="bucket",
            embedding_model_id="model-id",
            batch_processing_enabled=False,
            bedrock_client=mock_client,
        )

        assert len(results) == 3
        assert results[0].chunk_index == 0
        assert results[1].chunk_index == 1
        assert results[2].chunk_index == 2
        assert mock_client.invoke_model.call_count == 3

    def test_batch_processing_enabled(self):
        """When batch_processing_enabled=True, groups chunks into batches."""
        chunks = self._make_chunks(5)
        mock_client = MagicMock()
        mock_client.invoke_model.side_effect = [
            _mock_bedrock_response([float(i)]) for i in range(5)
        ]

        results = create_embeddings_batch(
            audio_chunks=chunks,
            s3_bucket="bucket",
            embedding_model_id="model-id",
            batch_processing_enabled=True,
            batch_size=2,
            bedrock_client=mock_client,
        )

        assert len(results) == 5
        # Order must be preserved
        for i, result in enumerate(results):
            assert result.chunk_index == i
        assert mock_client.invoke_model.call_count == 5

    def test_batch_size_larger_than_chunks(self):
        """Batch size larger than chunk count still works correctly."""
        chunks = self._make_chunks(2)
        mock_client = MagicMock()
        mock_client.invoke_model.side_effect = [
            _mock_bedrock_response([1.0]),
            _mock_bedrock_response([2.0]),
        ]

        results = create_embeddings_batch(
            audio_chunks=chunks,
            s3_bucket="bucket",
            embedding_model_id="model-id",
            batch_processing_enabled=True,
            batch_size=10,
            bedrock_client=mock_client,
        )

        assert len(results) == 2
        assert results[0].chunk_index == 0
        assert results[1].chunk_index == 1

    def test_single_chunk(self):
        """Processing a single chunk works in both modes."""
        chunks = self._make_chunks(1)
        mock_client = MagicMock()
        mock_client.invoke_model.return_value = _mock_bedrock_response([0.5])

        result_individual = create_embeddings_batch(
            audio_chunks=chunks,
            s3_bucket="bucket",
            embedding_model_id="model-id",
            batch_processing_enabled=False,
            bedrock_client=mock_client,
        )

        assert len(result_individual) == 1
        assert result_individual[0].chunk_index == 0

    def test_preserves_order(self):
        """Results maintain the same order as input chunks."""
        chunks = self._make_chunks(4)
        mock_client = MagicMock()
        mock_client.invoke_model.side_effect = [
            _mock_bedrock_response([float(i) + 0.1]) for i in range(4)
        ]

        results = create_embeddings_batch(
            audio_chunks=chunks,
            s3_bucket="bucket",
            embedding_model_id="model-id",
            batch_processing_enabled=True,
            batch_size=3,
            bedrock_client=mock_client,
        )

        for i, result in enumerate(results):
            assert result.chunk_index == i
            assert result.embedding_vector == [float(i) + 0.1]
