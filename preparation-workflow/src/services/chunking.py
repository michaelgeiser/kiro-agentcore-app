"""Audio chunking service for dividing audio into overlapping segments."""

from src.models.audio_chunk import AudioChunk


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

    Calculates chunk boundaries based on the configured chunking strategy,
    constructs S3 keys for each chunk, and creates AudioChunk model instances.

    Args:
        s3_bucket: S3 bucket where audio is stored.
        s3_audio_key: S3 key of the source audio file.
        submission_id: Unique identifier for the submission.
        user_id: Unique identifier for the user.
        chunk_size_seconds: Duration of each chunk in seconds.
        chunk_overlap_seconds: Overlap between consecutive chunks in seconds.
        total_duration_seconds: Total duration of the audio in seconds.

    Returns:
        List of AudioChunk objects in order, with S3 keys following the pattern:
        processed/{user_id}/{submission_id}/chunks/chunk_{index:04d}.mp3
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
