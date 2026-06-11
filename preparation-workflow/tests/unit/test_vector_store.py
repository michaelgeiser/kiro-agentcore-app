"""Unit tests for vector store service.

Tests build_vector_metadata, store_vectors routing, S3 storage, and
error handling for unsupported vector store types.

Requirements: 11.1, 11.2, 11.3, 11.4
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from src.models.embedding_result import EmbeddingResult
from src.models.vector_metadata import VectorMetadata
from src.services.vector_store import build_vector_metadata, store_vectors


def _make_embedding_result(
    submission_id: str = "sub-001",
    user_id: str = "user-123",
    chunk_index: int = 0,
    chunk_timestamp_start: float = 0.0,
    chunk_timestamp_end: float = 10.0,
    embedding_vector: list[float] | None = None,
    embedding_model_version: str = "nova-v1",
) -> EmbeddingResult:
    """Helper to create EmbeddingResult instances for tests."""
    return EmbeddingResult(
        submission_id=submission_id,
        user_id=user_id,
        chunk_index=chunk_index,
        chunk_timestamp_start=chunk_timestamp_start,
        chunk_timestamp_end=chunk_timestamp_end,
        embedding_vector=embedding_vector or [0.1, 0.2, 0.3],
        embedding_model_version=embedding_model_version,
    )


class TestBuildVectorMetadata:
    """Tests for build_vector_metadata function."""

    def test_extracts_all_metadata_fields(self):
        result = _make_embedding_result(
            submission_id="sub-abc",
            user_id="user-xyz",
            chunk_index=5,
            chunk_timestamp_start=10.0,
            chunk_timestamp_end=20.0,
            embedding_model_version="nova-v2",
        )
        metadata = build_vector_metadata(result)

        assert isinstance(metadata, VectorMetadata)
        assert metadata.submission_id == "sub-abc"
        assert metadata.user_id == "user-xyz"
        assert metadata.chunk_index == 5
        assert metadata.chunk_timestamp_start == 10.0
        assert metadata.chunk_timestamp_end == 20.0
        assert metadata.embedding_model_version == "nova-v2"

    def test_does_not_include_embedding_vector(self):
        result = _make_embedding_result(embedding_vector=[1.0, 2.0, 3.0, 4.0])
        metadata = build_vector_metadata(result)
        metadata_dict = metadata.model_dump()

        assert "embedding_vector" not in metadata_dict

    def test_preserves_zero_chunk_index(self):
        result = _make_embedding_result(chunk_index=0)
        metadata = build_vector_metadata(result)
        assert metadata.chunk_index == 0


class TestStoreVectors:
    """Tests for store_vectors function."""

    def test_empty_results_returns_zero_count(self):
        result = store_vectors([], "my-bucket", "s3")
        assert result["stored_count"] == 0
        assert result["vector_store_location"] == ""

    def test_unsupported_type_raises_value_error(self):
        results = [_make_embedding_result()]
        with pytest.raises(ValueError, match="Unsupported vector store type"):
            store_vectors(results, "endpoint", "redis")

    def test_type_matching_is_case_insensitive(self):
        results = [_make_embedding_result()]
        with patch("src.services.vector_store.boto3.client") as mock_boto:
            mock_s3 = MagicMock()
            mock_boto.return_value = mock_s3

            result = store_vectors(results, "my-bucket", "S3")
            assert result["stored_count"] == 1

    @patch("src.services.vector_store.boto3.client")
    def test_s3_stores_correct_number(self, mock_boto):
        mock_s3 = MagicMock()
        mock_boto.return_value = mock_s3

        results = [
            _make_embedding_result(chunk_index=0),
            _make_embedding_result(chunk_index=1, chunk_timestamp_start=10.0, chunk_timestamp_end=20.0),
            _make_embedding_result(chunk_index=2, chunk_timestamp_start=20.0, chunk_timestamp_end=30.0),
        ]

        output = store_vectors(results, "my-bucket", "s3")
        assert output["stored_count"] == 3
        assert mock_s3.put_object.call_count == 3

    @patch("src.services.vector_store.boto3.client")
    def test_s3_key_format(self, mock_boto):
        mock_s3 = MagicMock()
        mock_boto.return_value = mock_s3

        results = [_make_embedding_result(submission_id="sub-999", chunk_index=7)]

        store_vectors(results, "my-bucket", "s3")

        call_kwargs = mock_s3.put_object.call_args[1]
        assert call_kwargs["Bucket"] == "my-bucket"
        assert call_kwargs["Key"] == "sub-999/embeddings/chunk_0007.json"
        assert call_kwargs["ContentType"] == "application/json"

    @patch("src.services.vector_store.boto3.client")
    def test_s3_document_contains_vector_and_metadata(self, mock_boto):
        mock_s3 = MagicMock()
        mock_boto.return_value = mock_s3

        results = [_make_embedding_result(embedding_vector=[1.5, 2.5, 3.5])]

        store_vectors(results, "my-bucket", "s3")

        call_kwargs = mock_s3.put_object.call_args[1]
        body = json.loads(call_kwargs["Body"])
        assert body["embedding_vector"] == [1.5, 2.5, 3.5]
        assert "metadata" in body
        assert body["metadata"]["submission_id"] == "sub-001"
        assert body["metadata"]["user_id"] == "user-123"

    @patch("src.services.vector_store.boto3.client")
    def test_s3_location_format(self, mock_boto):
        mock_s3 = MagicMock()
        mock_boto.return_value = mock_s3

        results = [_make_embedding_result(submission_id="sub-loc")]

        output = store_vectors(results, "test-bucket", "s3")
        assert output["vector_store_location"] == "s3://test-bucket/sub-loc/embeddings"

    @patch("src.services.vector_store.boto3.client")
    def test_s3_put_object_failure_raises(self, mock_boto):
        mock_s3 = MagicMock()
        mock_boto.return_value = mock_s3
        mock_s3.put_object.side_effect = Exception("Access denied")

        results = [_make_embedding_result()]

        with pytest.raises(Exception, match="Access denied"):
            store_vectors(results, "my-bucket", "s3")

    def test_opensearch_returns_count(self):
        results = [
            _make_embedding_result(chunk_index=0),
            _make_embedding_result(chunk_index=1, chunk_timestamp_start=10.0, chunk_timestamp_end=20.0),
        ]

        output = store_vectors(results, "https://opensearch.example.com", "opensearch")
        assert output["stored_count"] == 2
        assert "sub-001" in output["vector_store_location"]
