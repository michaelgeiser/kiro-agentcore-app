"""Audio chunking service for dividing audio into overlapping segments.

Downloads audio from S3, splits it into time-based chunks using pydub,
uploads each chunk back to S3, and returns AudioChunk metadata.
"""

import logging
import os
import tempfile
from typing import Any

import boto3
from pydub import AudioSegment

# Configure pydub to find ffmpeg/ffprobe from Lambda layer (/opt/bin)
if os.environ.get("FFMPEG_BINARY"):
    AudioSegment.converter = os.environ["FFMPEG_BINARY"]
elif os.path.exists("/opt/bin/ffmpeg"):
    AudioSegment.converter = "/opt/bin/ffmpeg"

if os.environ.get("FFPROBE_BINARY"):
    AudioSegment.ffprobe = os.environ["FFPROBE_BINARY"]
elif os.path.exists("/opt/bin/ffprobe"):
    AudioSegment.ffprobe = "/opt/bin/ffprobe"

from models.audio_chunk import AudioChunk

logger = logging.getLogger(__name__)


def calculate_chunks(
    total_duration_seconds: float,
    chunk_size_seconds: int,
    chunk_overlap_seconds: int,
) -> list[tuple[float, float]]:
    """Calculate chunk timestamp boundaries.

    Divides audio of a given duration into overlapping chunks based on configured
    chunk size and overlap parameters.

    Args:
        total_duration_seconds: Total duration of the audio in seconds (must be > 0).
        chunk_size_seconds: Duration of each chunk in seconds (must be > 0).
        chunk_overlap_seconds: Overlap between consecutive chunks in seconds
            (must be >= 0 and < chunk_size_seconds).

    Returns:
        List of (start, end) tuples representing chunk boundaries in seconds.

    Properties that must hold:
    - First chunk starts at 0
    - Last chunk end >= total_duration_seconds
    - Consecutive chunks: chunks[i+1].start = chunks[i].start + (chunk_size - overlap)
    - No gaps between chunks
    """
    if total_duration_seconds <= 0:
        raise ValueError("total_duration_seconds must be > 0")
    if chunk_size_seconds <= 0:
        raise ValueError("chunk_size_seconds must be > 0")
    if chunk_overlap_seconds < 0:
        raise ValueError("chunk_overlap_seconds must be >= 0")
    if chunk_overlap_seconds >= chunk_size_seconds:
        raise ValueError("chunk_overlap_seconds must be < chunk_size_seconds")

    step_size = chunk_size_seconds - chunk_overlap_seconds
    chunks: list[tuple[float, float]] = []

    start = 0.0
    while start < total_duration_seconds:
        end = start + chunk_size_seconds
        chunks.append((start, end))
        start += step_size

    # Ensure the last chunk covers the total duration
    if chunks and chunks[-1][1] < total_duration_seconds:
        last_start = chunks[-1][0]
        chunks[-1] = (last_start, total_duration_seconds)

    return chunks


def chunk_audio(
    s3_bucket: str,
    s3_audio_key: str,
    submission_id: str,
    user_id: str,
    chunk_size_seconds: int,
    chunk_overlap_seconds: int,
    total_duration_seconds: float,
) -> list[AudioChunk]:
    """Divide audio into chunks and upload to S3.

    This is the metadata-only version used by unit tests.
    The handler() function performs the actual splitting and upload.

    Args:
        s3_bucket: S3 bucket where audio is stored.
        s3_audio_key: S3 key of the source audio file.
        submission_id: Unique identifier for the submission.
        user_id: Unique identifier for the user.
        chunk_size_seconds: Duration of each chunk in seconds.
        chunk_overlap_seconds: Overlap between consecutive chunks in seconds.
        total_duration_seconds: Total duration of the audio in seconds.

    Returns:
        List of AudioChunk objects in order.
    """
    chunk_boundaries = calculate_chunks(
        total_duration_seconds=total_duration_seconds,
        chunk_size_seconds=chunk_size_seconds,
        chunk_overlap_seconds=chunk_overlap_seconds,
    )

    audio_chunks: list[AudioChunk] = []

    for index, (start, end) in enumerate(chunk_boundaries):
        s3_chunk_key = (
            f"processed/{user_id}/{submission_id}/chunks/chunk_{index:04d}.mp3"
        )

        chunk = AudioChunk(
            chunk_index=index,
            s3_chunk_key=s3_chunk_key,
            timestamp_start_seconds=start,
            timestamp_end_seconds=end,
            submission_id=submission_id,
            user_id=user_id,
        )
        audio_chunks.append(chunk)

    return audio_chunks


def _download_audio(s3_client: Any, bucket: str, key: str, local_path: str) -> None:
    """Download an audio file from S3."""
    logger.info("Downloading s3://%s/%s to %s", bucket, key, local_path)
    s3_client.download_file(bucket, key, local_path)


def _upload_chunk(s3_client: Any, bucket: str, key: str, local_path: str) -> None:
    """Upload a chunk file to S3."""
    s3_client.upload_file(local_path, bucket, key)
    logger.debug("Uploaded chunk to s3://%s/%s", bucket, key)


def _detect_format(filename: str) -> str:
    """Detect audio format from file extension."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "mp3"
    format_map = {
        "mp3": "mp3",
        "wav": "wav",
        "m4a": "mp4",  # pydub uses 'mp4' for m4a container
        "aac": "aac",
        "mp4": "mp4",
    }
    return format_map.get(ext, "mp3")


def split_and_upload_chunks(
    s3_bucket: str,
    s3_audio_key: str,
    submission_id: str,
    user_id: str,
    chunk_size_seconds: int,
    chunk_overlap_seconds: int,
    s3_client: Any = None,
) -> list[AudioChunk]:
    """Download audio from S3, split into chunks, upload chunks back to S3.

    Args:
        s3_bucket: S3 bucket containing the source audio.
        s3_audio_key: S3 key of the source audio file.
        submission_id: Unique submission identifier.
        user_id: Unique user identifier.
        chunk_size_seconds: Duration of each chunk in seconds.
        chunk_overlap_seconds: Overlap between chunks in seconds.
        s3_client: Optional boto3 S3 client.

    Returns:
        List of AudioChunk objects with S3 keys pointing to uploaded chunks.
    """
    if s3_client is None:
        s3_client = boto3.client("s3")

    audio_format = _detect_format(s3_audio_key)

    with tempfile.TemporaryDirectory() as tmp_dir:
        # Download the source audio
        local_audio_path = os.path.join(tmp_dir, f"source.{audio_format}")
        _download_audio(s3_client, s3_bucket, s3_audio_key, local_audio_path)

        # Load with pydub to get actual duration and perform splitting
        audio = AudioSegment.from_file(local_audio_path, format=audio_format)
        total_duration_seconds = len(audio) / 1000.0  # pydub uses milliseconds

        logger.info(
            "Audio loaded: duration=%.2fs, format=%s",
            total_duration_seconds,
            audio_format,
        )

        # Calculate chunk boundaries
        chunk_boundaries = calculate_chunks(
            total_duration_seconds=total_duration_seconds,
            chunk_size_seconds=chunk_size_seconds,
            chunk_overlap_seconds=chunk_overlap_seconds,
        )

        audio_chunks: list[AudioChunk] = []

        for index, (start, end) in enumerate(chunk_boundaries):
            # Slice the audio (pydub uses milliseconds)
            start_ms = int(start * 1000)
            end_ms = int(min(end, total_duration_seconds) * 1000)
            chunk_segment = audio[start_ms:end_ms]

            # Export chunk to temp file
            chunk_filename = f"chunk_{index:04d}.mp3"
            chunk_local_path = os.path.join(tmp_dir, chunk_filename)
            chunk_segment.export(chunk_local_path, format="mp3")

            # Upload to S3
            s3_chunk_key = (
                f"processed/{user_id}/{submission_id}/chunks/{chunk_filename}"
            )
            _upload_chunk(s3_client, s3_bucket, s3_chunk_key, chunk_local_path)

            # Create AudioChunk metadata
            chunk = AudioChunk(
                chunk_index=index,
                s3_chunk_key=s3_chunk_key,
                timestamp_start_seconds=start,
                timestamp_end_seconds=min(end, total_duration_seconds),
                submission_id=submission_id,
                user_id=user_id,
            )
            audio_chunks.append(chunk)

            logger.info(
                "Chunk %d: %.2fs-%.2fs uploaded to s3://%s/%s",
                index, start, end, s3_bucket, s3_chunk_key,
            )

    return audio_chunks


def handler(event, context):
    """AWS Lambda handler entry point for audio chunking.

    Downloads the audio from S3, splits it into time-based chunks using pydub,
    uploads each chunk back to S3, and returns chunk metadata.

    Expects event with: s3_bucket, s3_file_key, user_id, submission_id, config.
    Config should contain chunk_size_seconds and chunk_overlap_seconds.
    """
    config = event.get("config", {})
    chunk_size_seconds = int(config.get("chunk_size_seconds", 30))
    chunk_overlap_seconds = int(config.get("chunk_overlap_seconds", 5))

    s3_bucket = event["s3_bucket"]
    s3_file_key = event["s3_file_key"]
    submission_id = event["submission_id"]
    user_id = event["user_id"]

    chunks = split_and_upload_chunks(
        s3_bucket=s3_bucket,
        s3_audio_key=s3_file_key,
        submission_id=submission_id,
        user_id=user_id,
        chunk_size_seconds=chunk_size_seconds,
        chunk_overlap_seconds=chunk_overlap_seconds,
    )

    return {
        "chunks": [chunk.model_dump() for chunk in chunks],
        "chunk_count": len(chunks),
        "s3_bucket": s3_bucket,
    }
