"""Lambda handler for transcribing audio files using Amazon Transcribe."""

import json
import logging
import os
import time
from typing import Any

import boto3

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Maximum time to wait for a transcription job to complete (5 minutes)
MAX_WAIT_SECONDS = 300
POLL_INTERVAL_SECONDS = 5


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda handler entry point for audio transcription.

    Starts an Amazon Transcribe job, polls for completion, and returns
    the S3 key where the transcript is stored.

    Args:
        event: Dict containing submission_id, s3_bucket, s3_file_key, config.
        context: Lambda context object.

    Returns:
        Dict with "transcript_s3_key" pointing to the transcript output.

    Raises:
        RuntimeError: If the transcription job fails or times out.
    """
    submission_id = event["submission_id"]
    s3_bucket = event["s3_bucket"]
    s3_file_key = event["s3_file_key"]

    job_name = f"prescoach-{submission_id}"
    output_key = f"transcripts/{submission_id}/transcript.txt"
    media_uri = f"s3://{s3_bucket}/{s3_file_key}"

    logger.info(
        "Starting transcription job=%s for submission_id=%s, input=%s",
        job_name,
        submission_id,
        media_uri,
    )

    transcribe_client = boto3.client("transcribe")

    # Start the transcription job
    transcribe_client.start_transcription_job(
        TranscriptionJobName=job_name,
        Media={"MediaFileUri": media_uri},
        OutputBucketName=s3_bucket,
        OutputKey=output_key,
        IdentifyLanguage=True,
    )

    # Poll for job completion
    elapsed = 0
    while elapsed < MAX_WAIT_SECONDS:
        time.sleep(POLL_INTERVAL_SECONDS)
        elapsed += POLL_INTERVAL_SECONDS

        response = transcribe_client.get_transcription_job(
            TranscriptionJobName=job_name
        )
        status = response["TranscriptionJob"]["TranscriptionJobStatus"]

        logger.info(
            "Transcription job=%s status=%s (elapsed=%ds)",
            job_name,
            status,
            elapsed,
        )

        if status == "COMPLETED":
            logger.info(
                "Transcription completed for submission_id=%s, output_key=%s",
                submission_id,
                output_key,
            )
            return {"transcript_s3_key": output_key}

        if status == "FAILED":
            failure_reason = response["TranscriptionJob"].get(
                "FailureReason", "Unknown failure"
            )
            logger.error(
                "Transcription job=%s failed: %s", job_name, failure_reason
            )
            raise RuntimeError(
                f"Transcription job failed: {failure_reason}"
            )

    # Timeout
    raise RuntimeError(
        f"Transcription job {job_name} did not complete within {MAX_WAIT_SECONDS}s"
    )
