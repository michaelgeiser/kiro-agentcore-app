"""Unit tests for embedding service.

Tests create_embedding with mocked Bedrock InvokeModel responses
using the Nova multimodal embeddings synchronous API format.

Requirements: 4.1, 4.2, 10.1
"""

import io
import json
from unittest.mock import MagicMock

import pytest

from models.audio_chunk import AudioChunk
from models.embedding_result import EmbeddingResult
from services.embedding import (
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


def _mock_nova_response(embedding: list[float]) -> dict:
    """Create a mock Bedrock Nova embeddings response."""
    response_body = json.dumps({
        "embeddings": [{"embeddingType": "AUDIO", "embedding": embedding}]
    }).encode("utf-8")
    return {"body": io.BytesIO(response_body)}


class TestBuildInvokePayload:
    """Tests for _build_invoke_payload helper."""

    def test_constructs_correct_structure(self):
        payload = _build_invoke_payload("my-bucket", "path/to/chunk.mp3")
        assert payload["taskType"] == "SINGLE_EMBEDDING"
        params = payload["singleEmbeddingParams"]
        assert params["embeddingPurpose"] == "GENERIC_INDEX"
        assert params["audio"]["source"]["s3Location"]["uri"] == "s3://my-bucket/path/to/chunk.mp3"

    def test_detects_audio_format_from_extension(self):
        payload = _build_invoke_payload("bucket", "path/to/file.wav")
        assert payload["singleEmbeddingParams"]["audio"]["format"] == "wav"

    def test_custom_dimension(self):
        payload = _build_invoke_payload("bucket", "key.mp3", dimension=3072)
        assert payload["singleEmbeddingParams"]["embeddingDimension"] == 3072


class TestParseEmbeddingResponse:
    """Tests for _parse_embedding_response helper."""

    def test_parses_nova_format(self):
        body = json.dumps({
            "embeddings": [{"embeddingType": "AUDIO", "embedding": [0.1, 0.2, 0.3]}]
        }).encode("utf-8")
        result = _parse_embedding_response(body)
        assert result == [0.1, 0.2, 0.3]

    def test_parses_legacy_format(self):
        body = json.dumps({"embedding": [0.4, 0.5]}).encode("utf-8")
        result = _parse_embedding_response(body)
        assert result == [0.4, 0.5]

    def test_raises_on_missing_embeddings(self):
        body = json.dumps({"result": "something"}).encode("utf-8")
        with pytest.raises(ValueError, match="does not contain valid embeddings"):
            _parse_embedding_response(body)

    def test_raises_on_empty_embedding_list(self):
        body = json.dumps({"embeddings": []}).encode("utf-8")
        with pytest.raises(ValueError, match="does not contain valid embeddings"):
            _parse_embedding_response(body)


class TestCreateEmbedding:
    """Tests for create_embedding function."""

    def test_successful_invocation(self):
        chunk = _make_audio_chunk(chunk_index=2, start=60.0, end=90.0)
        embedding_vector = [0.1, 0.2, 0.3, 0.4, 0.5]

        mock_client = MagicMock()
        mock_client.invoke_model.return_value = _mock_nova_response(embedding_vector)

        result = create_embedding(
            audio_chunk=chunk,
            s3_bucket="test-bucket",
            embedding_model_id="amazon.nova-2-multimodal-embeddings-v1:0",
            bedrock_client=mock_client,
        )

        assert isinstance(result, EmbeddingResult)
        assert result.submission_id == "sub-001"
        assert result.user_id == "user-001"
        assert result.chunk_index == 2
        assert result.chunk_timestamp_start == 60.0
        assert result.chunk_timestamp_end == 90.0
        assert result.embedding_vector == embedding_vector

    def test_passes_correct_model_id(self):
        chunk = _make_audio_chunk()
        mock_client = MagicMock()
        mock_client.invoke_model.return_value = _mock_nova_response([1.0])

        create_embedding(
            audio_chunk=chunk,
            s3_bucket="bucket",
            embedding_model_id="my-custom-model",
            bedrock_client=mock_client,
        )

        call_kwargs = mock_client.invoke_model.call_args[1]
        assert call_kwargs["modelId"] == "my-custom-model"

    def test_raises_runtime_error_on_bedrock_failure(self):
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
        chunk = AudioChunk(
            chunk_index=5,
            s3_chunk_key="processed/userA/subB/chunks/chunk_0005.mp3",
            timestamp_start_seconds=150.0,
            timestamp_end_seconds=180.0,
            submission_id="subB",
            user_id="userA",
        )
        mock_client = MagicMock()
        mock_client.invoke_model.return_value = _mock_nova_response([0.5, 0.6])

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


class TestCreateEmbeddingsBatch:
    """Tests for create_embeddings_batch function."""

    def _make_chunks(self, count: int) -> list[AudioChunk]:
        chunks = []
        for i in range(count):
            start = i * 30.0
            end = (i + 1) * 30.0
            chunks.append(_make_audio_chunk(chunk_index=i, start=start, end=end))
        return chunks

    def test_individual_processing(self):
        chunks = self._make_chunks(3)
        mock_client = MagicMock()
        mock_client.invoke_model.side_effect = [
            _mock_nova_response([0.1, 0.2]),
            _mock_nova_response([0.3, 0.4]),
            _mock_nova_response([0.5, 0.6]),
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

    def test_single_chunk(self):
        chunks = self._make_chunks(1)
        mock_client = MagicMock()
        mock_client.invoke_model.return_value = _mock_nova_response([0.5])

        results = create_embeddings_batch(
            audio_chunks=chunks,
            s3_bucket="bucket",
            embedding_model_id="model-id",
            batch_processing_enabled=False,
            bedrock_client=mock_client,
        )

        assert len(results) == 1
        assert results[0].chunk_index == 0
