"""Transcript loader for converting S3-stored Amazon Transcribe output to TranscriptData.

Loads the Amazon Transcribe JSON output from S3 and parses it into the
TranscriptData dataclass used by the synthesis pass and transcript metrics
extraction.

Amazon Transcribe JSON output format (relevant fields):
{
    "results": {
        "items": [
            {
                "type": "pronunciation",
                "alternatives": [{"content": "word", "confidence": "0.95"}],
                "start_time": "0.0",
                "end_time": "0.5"
            },
            {
                "type": "punctuation",
                "alternatives": [{"content": "."}]
            }
        ]
    }
}
"""

import json
import logging
from typing import Any

from services.transcript_metrics import TranscriptData, WordTiming

logger = logging.getLogger(__name__)


def load_transcript_from_s3(
    s3_client: Any,
    bucket_name: str,
    transcript_s3_key: str,
    close_start_seconds: float = 0.0,
) -> TranscriptData:
    """Load transcript data from S3 and parse into TranscriptData.

    Fetches the Amazon Transcribe JSON output from S3 and extracts
    word-level timings into a TranscriptData instance.

    Args:
        s3_client: Boto3 S3 client.
        bucket_name: S3 bucket name.
        transcript_s3_key: S3 key for the transcript JSON file.
        close_start_seconds: Start of the closing segment in seconds.
            Defaults to 0.0 (will be estimated from transcript duration
            if not explicitly provided).

    Returns:
        TranscriptData with word-level timings. Returns an empty
        TranscriptData (no words) if the transcript cannot be loaded
        or parsed.
    """
    try:
        response = s3_client.get_object(
            Bucket=bucket_name,
            Key=transcript_s3_key,
        )
        content = response["Body"].read().decode("utf-8")
        transcript_json = json.loads(content)
        return _parse_transcribe_output(transcript_json, close_start_seconds)
    except Exception as exc:
        logger.warning(
            "Failed to load transcript from s3://%s/%s: %s. "
            "Returning empty TranscriptData.",
            bucket_name,
            transcript_s3_key,
            exc,
        )
        return TranscriptData(words=[], close_start_seconds=0.0)


def _parse_transcribe_output(
    transcript_json: dict,
    close_start_seconds: float,
) -> TranscriptData:
    """Parse Amazon Transcribe JSON output into TranscriptData.

    Extracts pronunciation items (words with timings) and ignores
    punctuation items (which have no timing data).

    Args:
        transcript_json: Parsed JSON from Amazon Transcribe output.
        close_start_seconds: Start of the closing segment in seconds.

    Returns:
        TranscriptData with extracted word timings.
    """
    words: list[WordTiming] = []

    items = transcript_json.get("results", {}).get("items", [])

    for item in items:
        if item.get("type") != "pronunciation":
            continue

        alternatives = item.get("alternatives", [])
        if not alternatives:
            continue

        word_text = alternatives[0].get("content", "")
        if not word_text:
            continue

        # Extract timing — Amazon Transcribe uses string floats
        start_time_str = item.get("start_time")
        end_time_str = item.get("end_time")

        if start_time_str is None or end_time_str is None:
            continue

        try:
            start_seconds = float(start_time_str)
            end_seconds = float(end_time_str)
        except (ValueError, TypeError):
            continue

        # Extract confidence (optional)
        confidence_str = alternatives[0].get("confidence")
        confidence: float | None = None
        if confidence_str is not None:
            try:
                confidence = float(confidence_str)
            except (ValueError, TypeError):
                confidence = None

        words.append(
            WordTiming(
                word=word_text,
                start_seconds=start_seconds,
                end_seconds=end_seconds,
                confidence=confidence,
            )
        )

    # If close_start_seconds is 0.0 and we have words, estimate closing
    # as the last 15% of the audio (a reasonable default)
    if close_start_seconds == 0.0 and words:
        total_duration = words[-1].end_seconds
        close_start_seconds = total_duration * 0.85

    return TranscriptData(words=words, close_start_seconds=close_start_seconds)
