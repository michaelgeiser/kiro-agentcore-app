"""Embedding service for creating vector embeddings from audio chunks.

Uses Amazon Bedrock InvokeModel with Amazon Nova Multimodal Embeddings
(amazon.nova-2-multimodal-embeddings-v1:0) to create vector embeddings
from audio chunks stored in S3.

Audio chunks must be <= 30 seconds to use the synchronous SINGLE_EMBEDDING API.
The chunking service already enforces this via the chunk_size_seconds config.

Requirements: 4.1, 4.2, 10.1
"""

import json
import logging
from typing import Any

import boto3

from models.audio_chunk import AudioChunk
from models.embedding_result import EmbeddingResult
from services.batch_processor import group_into_batches, process_batches

logger = logging.getLogger(__name__)

DEFAULT_MODEL_ID = "amazon.nova-2-multimodal-embeddings-v1:0"
DEFAULT_EMBEDDING_DIMENSION = 1024


def _create_bedrock_client() -> Any:
    """Create a Bedrock Runtime client."""
    return boto3.client("bedrock-runtime")


def _build_invoke_payload(s3_bucket: str, s3_chunk_key: str, dimension: int = DEFAULT_EMBEDDING_DIMENSION) -> dict:
    """Build the request payload for Nova multimodal embeddings synchronous invocation.

    Uses the SINGLE_EMBEDDING taskType with audio input via S3 URI.

    Args:
        s3_bucket: The S3 bucket containing the audio chunk.
        s3_chunk_key: The S3 key of the audio chunk.
        dimension: Embedding dimension (256, 384, 1024, or 3072).

    Returns:
        A dictionary payload for the Bedrock InvokeModel API.
    """
    s3_uri = f"s3://{s3_bucket}/{s3_chunk_key}"

    # Determine audio format from the file extension
    extension = s3_chunk_key.rsplit(".", 1)[-1].lower() if "." in s3_chunk_key else "mp3"

    return {
        "taskType": "SINGLE_EMBEDDING",
        "singleEmbeddingParams": {
            "embeddingPurpose": "GENERIC_INDEX",
            "embeddingDimension": dimension,
            "audio": {
                "format": extension,
                "source": {
                    "s3Location": {"uri": s3_uri}
                },
            },
        },
    }


def _parse_embedding_response(response_body: bytes) -> list[float]:
    """Parse the embedding vector from Bedrock Nova embeddings response.

    Nova embeddings returns: {"embeddings": [{"embeddingType": "AUDIO", "embedding": [...]}]}

    Args:
        response_body: Raw response body bytes from Bedrock InvokeModel.

    Returns:
        The embedding vector as a list of floats.

    Raises:
        ValueError: If the response does not contain an embedding vector.
    """
    parsed = json.loads(response_body)

    embeddings = parsed.get("embeddings")
    if embeddings is None or not isinstance(embeddings, list) or len(embeddings) == 0:
        # Try legacy format with single "embedding" key
        embedding = parsed.get("embedding")
        if embedding is not None and isinstance(embedding, list) and len(embedding) > 0:
            return embedding
        raise ValueError(
            f"Bedrock response does not contain valid embeddings. Got keys: {list(parsed.keys())}"
        )

    # Get the first embedding from the list
    first_embedding = embeddings[0]
    vector = first_embedding.get("embedding")
    if vector is None or not isinstance(vector, list) or len(vector) == 0:
        raise ValueError(
            "Bedrock response embedding entry does not contain a valid vector."
        )

    return vector


def create_embedding(
    audio_chunk: AudioChunk,
    s3_bucket: str,
    embedding_model_id: str,
    embedding_dimension: int = DEFAULT_EMBEDDING_DIMENSION,
    bedrock_client: Any = None,
) -> EmbeddingResult:
    """Invoke Bedrock synchronously to create an embedding from an audio chunk.

    Uses the SINGLE_EMBEDDING taskType which supports audio <= 30 seconds.

    Args:
        audio_chunk: AudioChunk with the S3 key of the audio chunk.
        s3_bucket: The S3 bucket containing the chunk.
        embedding_model_id: The Bedrock model ID.
        embedding_dimension: Output embedding dimension (256, 384, 1024, or 3072).
        bedrock_client: Optional pre-configured bedrock-runtime client.

    Returns:
        EmbeddingResult with embedding vector and metadata.

    Raises:
        RuntimeError: If the Bedrock invocation fails.
    """
    if bedrock_client is None:
        bedrock_client = _create_bedrock_client()

    payload = _build_invoke_payload(s3_bucket, audio_chunk.s3_chunk_key, embedding_dimension)

    logger.info(
        "Invoking Bedrock model %s for chunk %d of submission %s",
        embedding_model_id,
        audio_chunk.chunk_index,
        audio_chunk.submission_id,
    )

    try:
        response = bedrock_client.invoke_model(
            modelId=embedding_model_id,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(payload),
        )
    except Exception as e:
        logger.error(
            "Bedrock invocation failed for chunk %d of submission %s: %s",
            audio_chunk.chunk_index,
            audio_chunk.submission_id,
            str(e),
        )
        raise RuntimeError(
            f"Bedrock invocation failed for chunk {audio_chunk.chunk_index}: {str(e)}"
        ) from e

    response_body = response["body"].read()
    embedding_vector = _parse_embedding_response(response_body)

    return EmbeddingResult(
        submission_id=audio_chunk.submission_id,
        user_id=audio_chunk.user_id,
        chunk_index=audio_chunk.chunk_index,
        chunk_timestamp_start=audio_chunk.timestamp_start_seconds,
        chunk_timestamp_end=audio_chunk.timestamp_end_seconds,
        embedding_vector=embedding_vector,
        embedding_model_version=embedding_model_id,
    )


def create_embeddings_batch(
    audio_chunks: list[AudioChunk],
    s3_bucket: str,
    embedding_model_id: str,
    batch_processing_enabled: bool = False,
    batch_size: int = 10,
    embedding_dimension: int = DEFAULT_EMBEDDING_DIMENSION,
    bedrock_client: Any = None,
) -> list[EmbeddingResult]:
    """Create embeddings for multiple audio chunks.

    Args:
        audio_chunks: List of AudioChunk objects to process.
        s3_bucket: The S3 bucket containing the chunks.
        embedding_model_id: The Bedrock model ID.
        batch_processing_enabled: Whether to use batch grouping.
        batch_size: Number of chunks per batch when batch processing is enabled.
        embedding_dimension: Output embedding dimension.
        bedrock_client: Optional pre-configured bedrock-runtime client.

    Returns:
        List of EmbeddingResult objects in the same order as input chunks.
    """
    if bedrock_client is None:
        bedrock_client = _create_bedrock_client()

    def _process_chunk(chunk: AudioChunk) -> EmbeddingResult:
        return create_embedding(
            audio_chunk=chunk,
            s3_bucket=s3_bucket,
            embedding_model_id=embedding_model_id,
            embedding_dimension=embedding_dimension,
            bedrock_client=bedrock_client,
        )

    if not batch_processing_enabled:
        logger.info(
            "Processing %d chunks individually for embedding.", len(audio_chunks)
        )
        results: list[EmbeddingResult] = []
        for chunk in audio_chunks:
            result = _process_chunk(chunk)
            results.append(result)
        return results
    else:
        logger.info(
            "Processing %d chunks in batches of %d for embedding.",
            len(audio_chunks),
            batch_size,
        )
        batches = group_into_batches(audio_chunks, batch_size)
        return process_batches(batches, _process_chunk)


def handler(event, context):
    """AWS Lambda handler entry point for embedding creation.

    Called per-chunk by the Step Functions Map state.
    Expects event with: chunk (dict), config (dict), submission_id, user_id.
    """
    import os

    chunk_data = event["chunk"]
    config = event.get("config", {})

    audio_chunk = AudioChunk(
        chunk_index=chunk_data["chunk_index"],
        s3_chunk_key=chunk_data["s3_chunk_key"],
        timestamp_start_seconds=chunk_data["timestamp_start_seconds"],
        timestamp_end_seconds=chunk_data["timestamp_end_seconds"],
        submission_id=chunk_data.get("submission_id", event.get("submission_id", "")),
        user_id=chunk_data.get("user_id", event.get("user_id", "")),
    )

    env_name = os.environ.get("ENV_NAME", "dev")
    s3_bucket = config.get("uploads_bucket", f"prescoach-{env_name}-kiro-uploads")
    embedding_model_id = config.get("embedding_model_id", DEFAULT_MODEL_ID)

    result = create_embedding(
        audio_chunk=audio_chunk,
        s3_bucket=s3_bucket,
        embedding_model_id=embedding_model_id,
    )

    return result.model_dump()
