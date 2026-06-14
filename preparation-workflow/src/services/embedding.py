"""Embedding service for creating vector embeddings from audio chunks.

Invokes Amazon Bedrock with audio chunks to create vector embeddings.
Supports both individual and batch invocation based on configuration.

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


def _create_bedrock_client() -> Any:
    """Create a Bedrock Runtime client.

    Returns:
        A boto3 bedrock-runtime client.
    """
    return boto3.client("bedrock-runtime")


def _build_invoke_payload(s3_bucket: str, s3_chunk_key: str) -> dict:
    """Build the request payload for Bedrock model invocation.

    Constructs the S3 URI for the audio chunk and wraps it in the
    expected Bedrock input format for embedding models.

    Args:
        s3_bucket: The S3 bucket containing the audio chunk.
        s3_chunk_key: The S3 key of the audio chunk.

    Returns:
        A dictionary payload for the Bedrock InvokeModel API.
    """
    s3_uri = f"s3://{s3_bucket}/{s3_chunk_key}"
    return {
        "inputText": None,
        "inputImage": None,
        "inputAudio": s3_uri,
    }


def _parse_embedding_response(response_body: bytes) -> list[float]:
    """Parse the embedding vector from Bedrock response.

    Args:
        response_body: Raw response body bytes from Bedrock InvokeModel.

    Returns:
        The embedding vector as a list of floats.

    Raises:
        ValueError: If the response does not contain an embedding vector.
    """
    parsed = json.loads(response_body)
    embedding = parsed.get("embedding")
    if embedding is None:
        raise ValueError(
            "Bedrock response does not contain an 'embedding' field."
        )
    if not isinstance(embedding, list) or len(embedding) == 0:
        raise ValueError(
            "Bedrock response 'embedding' field is not a non-empty list."
        )
    return embedding


def create_embedding(
    audio_chunk: AudioChunk,
    s3_bucket: str,
    embedding_model_id: str,
    bedrock_client: Any = None,
) -> EmbeddingResult:
    """Invoke Bedrock to create an embedding from an audio chunk.

    Args:
        audio_chunk: AudioChunk with the S3 key of the audio chunk.
        s3_bucket: The S3 bucket containing the chunk.
        embedding_model_id: The Bedrock model ID (e.g., "amazon.titan-embed-image-v1").
        bedrock_client: Optional pre-configured bedrock-runtime client.
            If None, a new client is created.

    Returns:
        EmbeddingResult with embedding vector and metadata.

    Raises:
        RuntimeError: If the Bedrock invocation fails.
    """
    if bedrock_client is None:
        bedrock_client = _create_bedrock_client()

    payload = _build_invoke_payload(s3_bucket, audio_chunk.s3_chunk_key)

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
    bedrock_client: Any = None,
) -> list[EmbeddingResult]:
    """Create embeddings for multiple audio chunks.

    Supports both individual and batch processing based on configuration.
    When batch processing is disabled, chunks are processed sequentially.
    When enabled, chunks are grouped into batches of the configured size
    using the batch_processor service.

    Args:
        audio_chunks: List of AudioChunk objects to process.
        s3_bucket: The S3 bucket containing the chunks.
        embedding_model_id: The Bedrock model ID.
        batch_processing_enabled: Whether to use batch grouping.
        batch_size: Number of chunks per batch when batch processing is enabled.
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
            bedrock_client=bedrock_client,
        )

    if not batch_processing_enabled:
        # Individual processing: invoke one chunk at a time
        logger.info(
            "Processing %d chunks individually for embedding.", len(audio_chunks)
        )
        results: list[EmbeddingResult] = []
        for chunk in audio_chunks:
            result = _process_chunk(chunk)
            results.append(result)
        return results
    else:
        # Batch processing: group chunks and process each batch
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

    # Get the S3 bucket from the chunk key or config
    s3_bucket = config.get("uploads_bucket", "prescoach-dev-kiro-uploads")
    embedding_model_id = config.get("embedding_model_id", "amazon.nova-embed-multimodal-v1:0")

    result = create_embedding(
        audio_chunk=audio_chunk,
        s3_bucket=s3_bucket,
        embedding_model_id=embedding_model_id,
    )

    return result.model_dump()
