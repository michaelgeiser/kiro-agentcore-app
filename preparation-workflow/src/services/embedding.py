"""Embedding service for creating vector embeddings from audio chunks.

Uses Amazon Bedrock StartAsyncInvoke with Amazon Nova Multimodal Embeddings
to create vector embeddings from audio chunks stored in S3.

The Nova multimodal embeddings model (amazon.nova-2-multimodal-embeddings-v1:0)
only supports async invocation. This service submits the job, polls for
completion, then reads the result from the S3 output location.

Requirements: 4.1, 4.2, 10.1
"""

import json
import logging
import time
import uuid
from typing import Any

import boto3

from models.audio_chunk import AudioChunk
from models.embedding_result import EmbeddingResult
from services.batch_processor import group_into_batches, process_batches

logger = logging.getLogger(__name__)

# Polling configuration for async invocation
DEFAULT_POLL_INTERVAL_SECONDS = 5
MAX_POLL_ATTEMPTS = 60  # 5 minutes max at 5s intervals

DEFAULT_MODEL_ID = "amazon.nova-2-multimodal-embeddings-v1:0"


def _create_bedrock_client() -> Any:
    """Create a Bedrock Runtime client."""
    return boto3.client("bedrock-runtime")


def _create_s3_client() -> Any:
    """Create an S3 client."""
    return boto3.client("s3")


def _build_async_model_input(s3_bucket: str, s3_chunk_key: str) -> dict:
    """Build the model input for Nova multimodal embeddings async invocation.

    Args:
        s3_bucket: The S3 bucket containing the audio chunk.
        s3_chunk_key: The S3 key of the audio chunk.

    Returns:
        Model input dict for StartAsyncInvoke.
    """
    s3_uri = f"s3://{s3_bucket}/{s3_chunk_key}"
    return {
        "inputAudio": s3_uri,
    }


def _poll_async_invocation(
    bedrock_client: Any,
    invocation_arn: str,
    poll_interval: int = DEFAULT_POLL_INTERVAL_SECONDS,
    max_attempts: int = MAX_POLL_ATTEMPTS,
) -> dict:
    """Poll an async invocation until completion.

    Args:
        bedrock_client: The boto3 bedrock-runtime client.
        invocation_arn: The ARN of the async invocation.
        poll_interval: Seconds between poll attempts.
        max_attempts: Maximum polling attempts.

    Returns:
        The completed invocation response.

    Raises:
        RuntimeError: If the invocation fails or times out.
    """
    for attempt in range(max_attempts):
        response = bedrock_client.get_async_invoke(invocationArn=invocation_arn)
        status = response.get("status", "Unknown")

        if status == "Completed":
            logger.info("Async invocation completed: %s", invocation_arn)
            return response
        elif status == "Failed":
            failure_message = response.get("failureMessage", "Unknown failure")
            raise RuntimeError(
                f"Bedrock async invocation failed: {failure_message}"
            )
        elif status in ("InProgress", "Submitted"):
            logger.debug(
                "Async invocation %s status: %s (attempt %d/%d)",
                invocation_arn, status, attempt + 1, max_attempts,
            )
            time.sleep(poll_interval)
        else:
            logger.warning(
                "Unexpected async invocation status: %s", status
            )
            time.sleep(poll_interval)

    raise RuntimeError(
        f"Bedrock async invocation timed out after {max_attempts * poll_interval}s: {invocation_arn}"
    )


def _read_embedding_from_s3(s3_output_uri: str, s3_client: Any = None) -> list[float]:
    """Read the embedding vector from the S3 output location.

    Args:
        s3_output_uri: The S3 URI where Bedrock wrote the result.
        s3_client: Optional S3 client.

    Returns:
        The embedding vector as a list of floats.
    """
    if s3_client is None:
        s3_client = _create_s3_client()

    # Parse s3://bucket/key from the URI
    if s3_output_uri.startswith("s3://"):
        path = s3_output_uri[5:]
    else:
        path = s3_output_uri

    bucket = path.split("/")[0]
    key = "/".join(path.split("/")[1:])

    # The output might be in a subdirectory; look for the output file
    # Bedrock async writes output.json or similar in the output prefix
    response = s3_client.list_objects_v2(Bucket=bucket, Prefix=key)
    contents = response.get("Contents", [])

    if not contents:
        raise RuntimeError(
            f"No output files found at s3://{bucket}/{key}"
        )

    # Read the first (or only) output file
    output_key = contents[0]["Key"]
    obj = s3_client.get_object(Bucket=bucket, Key=output_key)
    body = obj["Body"].read()
    parsed = json.loads(body)

    # Extract embedding from response
    embedding = parsed.get("embedding")
    if embedding is None:
        raise ValueError(
            f"Bedrock async output does not contain 'embedding' field. Got keys: {list(parsed.keys())}"
        )
    if not isinstance(embedding, list) or len(embedding) == 0:
        raise ValueError(
            "Bedrock async output 'embedding' field is not a non-empty list."
        )

    return embedding


def create_embedding(
    audio_chunk: AudioChunk,
    s3_bucket: str,
    embedding_model_id: str,
    output_bucket: str = "",
    bedrock_client: Any = None,
    s3_client: Any = None,
) -> EmbeddingResult:
    """Create an embedding from an audio chunk using Bedrock async invocation.

    Submits a StartAsyncInvoke request, polls for completion, then reads
    the embedding vector from the S3 output location.

    Args:
        audio_chunk: AudioChunk with the S3 key of the audio chunk.
        s3_bucket: The S3 bucket containing the chunk.
        embedding_model_id: The Bedrock model ID.
        output_bucket: S3 bucket for async output. Defaults to same as input bucket.
        bedrock_client: Optional pre-configured bedrock-runtime client.
        s3_client: Optional pre-configured S3 client.

    Returns:
        EmbeddingResult with embedding vector and metadata.

    Raises:
        RuntimeError: If the Bedrock invocation fails.
    """
    if bedrock_client is None:
        bedrock_client = _create_bedrock_client()
    if s3_client is None:
        s3_client = _create_s3_client()
    if not output_bucket:
        output_bucket = s3_bucket

    model_input = _build_async_model_input(s3_bucket, audio_chunk.s3_chunk_key)

    # Unique output prefix for this invocation
    output_prefix = (
        f"embeddings-output/{audio_chunk.submission_id}/"
        f"chunk_{audio_chunk.chunk_index:04d}/{uuid.uuid4().hex[:8]}"
    )
    output_s3_uri = f"s3://{output_bucket}/{output_prefix}/"

    logger.info(
        "Starting async embedding for chunk %d of submission %s (model: %s)",
        audio_chunk.chunk_index,
        audio_chunk.submission_id,
        embedding_model_id,
    )

    try:
        response = bedrock_client.start_async_invoke(
            modelId=embedding_model_id,
            modelInput=model_input,
            outputDataConfig={
                "s3OutputDataConfig": {
                    "s3Uri": output_s3_uri,
                }
            },
        )
    except Exception as e:
        logger.error(
            "Bedrock StartAsyncInvoke failed for chunk %d of submission %s: %s",
            audio_chunk.chunk_index,
            audio_chunk.submission_id,
            str(e),
        )
        raise RuntimeError(
            f"Bedrock async invocation failed for chunk {audio_chunk.chunk_index}: {str(e)}"
        ) from e

    invocation_arn = response["invocationArn"]
    logger.info("Async invocation started: %s", invocation_arn)

    # Poll for completion
    completed_response = _poll_async_invocation(bedrock_client, invocation_arn)

    # Read the output from S3
    output_location = completed_response.get("outputDataConfig", {}).get(
        "s3OutputDataConfig", {}
    ).get("s3Uri", output_s3_uri)

    embedding_vector = _read_embedding_from_s3(output_location, s3_client)

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
    output_bucket: str = "",
    bedrock_client: Any = None,
    s3_client: Any = None,
) -> list[EmbeddingResult]:
    """Create embeddings for multiple audio chunks.

    Args:
        audio_chunks: List of AudioChunk objects to process.
        s3_bucket: The S3 bucket containing the chunks.
        embedding_model_id: The Bedrock model ID.
        batch_processing_enabled: Whether to use batch grouping.
        batch_size: Number of chunks per batch when batch processing is enabled.
        output_bucket: S3 bucket for async output.
        bedrock_client: Optional pre-configured bedrock-runtime client.
        s3_client: Optional pre-configured S3 client.

    Returns:
        List of EmbeddingResult objects in the same order as input chunks.
    """
    if bedrock_client is None:
        bedrock_client = _create_bedrock_client()
    if s3_client is None:
        s3_client = _create_s3_client()

    def _process_chunk(chunk: AudioChunk) -> EmbeddingResult:
        return create_embedding(
            audio_chunk=chunk,
            s3_bucket=s3_bucket,
            embedding_model_id=embedding_model_id,
            output_bucket=output_bucket,
            bedrock_client=bedrock_client,
            s3_client=s3_client,
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
        output_bucket=s3_bucket,  # Use same bucket for output
    )

    return result.model_dump()
