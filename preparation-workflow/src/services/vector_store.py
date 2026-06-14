"""Vector store service for writing embeddings to configurable storage backends.

Supports routing to different storage backends (S3, OpenSearch) based on
the configured vector_store_type. Extracts metadata from EmbeddingResult
objects and writes embeddings with full metadata for retrieval.

Requirements: 11.1, 11.2, 11.3, 11.4
"""

import json
import logging
from typing import Any

import boto3

from models.embedding_result import EmbeddingResult
from models.vector_metadata import VectorMetadata

logger = logging.getLogger(__name__)


def build_vector_metadata(result: EmbeddingResult) -> VectorMetadata:
    """Extract VectorMetadata from an EmbeddingResult.

    Converts an EmbeddingResult into a VectorMetadata object containing
    all metadata fields needed to link the embedding back to its source.

    Args:
        result: The EmbeddingResult to extract metadata from.

    Returns:
        A VectorMetadata object with fields copied from the EmbeddingResult.
    """
    return VectorMetadata(
        submission_id=result.submission_id,
        user_id=result.user_id,
        chunk_index=result.chunk_index,
        chunk_timestamp_start=result.chunk_timestamp_start,
        chunk_timestamp_end=result.chunk_timestamp_end,
        embedding_model_version=result.embedding_model_version,
    )


def _store_to_s3(
    embedding_results: list[EmbeddingResult],
    endpoint: str,
) -> dict:
    """Store embedding results as JSON files in S3.

    Each embedding is written as a JSON file containing the embedding vector
    and its associated metadata at the path:
        {endpoint}/{submission_id}/embeddings/chunk_{index:04d}.json

    Args:
        embedding_results: List of EmbeddingResult objects to store.
        endpoint: The S3 bucket name to write to.

    Returns:
        Dict with stored_count and vector_store_location.
    """
    s3_client = boto3.client("s3")
    stored_count = 0
    submission_id = embedding_results[0].submission_id if embedding_results else ""

    for result in embedding_results:
        metadata = build_vector_metadata(result)
        document = {
            "embedding_vector": result.embedding_vector,
            "metadata": metadata.model_dump(),
        }

        s3_key = (
            f"{result.submission_id}/embeddings/chunk_{result.chunk_index:04d}.json"
        )

        try:
            s3_client.put_object(
                Bucket=endpoint,
                Key=s3_key,
                Body=json.dumps(document),
                ContentType="application/json",
            )
            stored_count += 1
            logger.debug("Stored embedding chunk %d to s3://%s/%s", result.chunk_index, endpoint, s3_key)
        except Exception as e:
            logger.error(
                "Failed to store embedding chunk %d to S3: %s",
                result.chunk_index,
                str(e),
            )
            raise

    location = f"s3://{endpoint}/{submission_id}/embeddings"
    logger.info(
        "Successfully stored %d embeddings to %s", stored_count, location
    )

    return {
        "stored_count": stored_count,
        "vector_store_location": location,
    }


def _store_to_opensearch(
    embedding_results: list[EmbeddingResult],
    endpoint: str,
) -> dict:
    """Store embedding results to OpenSearch Serverless (placeholder).

    This is a placeholder implementation for OpenSearch Serverless storage.
    The actual implementation will use the OpenSearch client to index
    embeddings with their metadata.

    Args:
        embedding_results: List of EmbeddingResult objects to store.
        endpoint: The OpenSearch Serverless endpoint URL.

    Returns:
        Dict with stored_count and vector_store_location.
    """
    submission_id = embedding_results[0].submission_id if embedding_results else ""
    stored_count = len(embedding_results)

    logger.info(
        "OpenSearch storage placeholder: would store %d embeddings to %s",
        stored_count,
        endpoint,
    )

    return {
        "stored_count": stored_count,
        "vector_store_location": f"{endpoint}/{submission_id}",
    }


def store_vectors(
    embedding_results: list[EmbeddingResult],
    vector_store_endpoint: str,
    vector_store_type: str,
) -> dict:
    """Write embedding vectors with metadata to the configured vector store.

    Routes to the appropriate storage backend based on vector_store_type.
    Each embedding is stored with full VectorMetadata for retrieval.

    Args:
        embedding_results: List of EmbeddingResult objects to store.
        vector_store_endpoint: The vector store endpoint (bucket name for S3,
            URL for OpenSearch).
        vector_store_type: Type of vector store ("s3", "opensearch", etc.).

    Returns:
        Dict with:
        - "stored_count": number of vectors successfully stored
        - "vector_store_location": location/identifier for retrieval

    Raises:
        ValueError: If vector_store_type is not supported.
    """
    if not embedding_results:
        return {
            "stored_count": 0,
            "vector_store_location": "",
        }

    logger.info(
        "Storing %d vectors to %s (type=%s)",
        len(embedding_results),
        vector_store_endpoint,
        vector_store_type,
    )

    vector_store_type_lower = vector_store_type.lower()

    if vector_store_type_lower == "s3":
        return _store_to_s3(embedding_results, vector_store_endpoint)
    elif vector_store_type_lower == "opensearch":
        return _store_to_opensearch(embedding_results, vector_store_endpoint)
    else:
        raise ValueError(
            f"Unsupported vector store type: '{vector_store_type}'. "
            f"Supported types: 's3', 'opensearch'."
        )


def handler(event, context):
    """AWS Lambda handler entry point for vector storage.

    Expects event with: embeddings (list of dicts), submission_id, user_id, config.
    Config should contain vector_store_endpoint and vector_store_type.
    """
    config = event.get("config", {})
    vector_store_endpoint = config.get("vector_store_endpoint", "prescoach-vectors")
    vector_store_type = config.get("vector_store_type", "s3")

    # Strip s3:// prefix if present (endpoint should be just the bucket name for S3)
    if vector_store_endpoint.startswith("s3://"):
        vector_store_endpoint = vector_store_endpoint[5:]

    # Reconstruct EmbeddingResult objects from the Map state output
    embeddings_data = event.get("embeddings", [])
    embedding_results = []

    for item in embeddings_data:
        # Each item from the Map state is {"value": {embedding_result_dict}}
        data = item.get("value", item)
        embedding_results.append(EmbeddingResult(**data))

    result = store_vectors(
        embedding_results=embedding_results,
        vector_store_endpoint=vector_store_endpoint,
        vector_store_type=vector_store_type,
    )

    return result
