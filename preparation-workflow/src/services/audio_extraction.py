"""Audio extraction service using AWS Elemental MediaConvert.

Submits MediaConvert jobs to extract audio from video files and polls
for completion. Constructs output S3 keys using the pattern:
    processed/{user_id}/{submission_id}/audio.{format}

Requirements: 3.1, 3.2, 3.3
"""

import logging
import time
from typing import Any

import boto3

logger = logging.getLogger(__name__)

# MediaConvert job polling configuration
DEFAULT_POLL_INTERVAL_SECONDS = 30
MAX_POLL_ATTEMPTS = 60  # 30 minutes max at 30s intervals


def construct_output_key(
    user_id: str, submission_id: str, output_format: str = "mp3"
) -> str:
    """Construct the S3 output key for extracted audio.

    Args:
        user_id: The user identifier.
        submission_id: The submission identifier.
        output_format: The audio output format (default: mp3).

    Returns:
        The S3 key in the pattern: processed/{user_id}/{submission_id}/audio.{format}
    """
    return f"processed/{user_id}/{submission_id}/audio.{output_format}"


def _create_mediaconvert_client(endpoint: str) -> Any:
    """Create a MediaConvert client using the provided endpoint.

    Args:
        endpoint: The MediaConvert account-specific endpoint URL.

    Returns:
        A boto3 MediaConvert client configured with the endpoint.
    """
    return boto3.client("mediaconvert", endpoint_url=endpoint)


def _build_job_settings(
    s3_bucket: str,
    s3_input_key: str,
    output_s3_key: str,
    output_format: str,
) -> dict:
    """Build the MediaConvert job settings for audio extraction.

    Args:
        s3_bucket: The S3 bucket name.
        s3_input_key: The S3 key of the input video file.
        output_s3_key: The S3 key for the output audio file.
        output_format: The desired output audio format.

    Returns:
        A dictionary of MediaConvert job settings.
    """
    # Determine the output container and codec based on format
    container_map = {
        "mp3": "RAW",
        "wav": "WAV",
        "m4a": "MP4",
        "aac": "RAW",
    }
    codec_map = {
        "mp3": "MP3",
        "wav": "WAV",
        "m4a": "AAC",
        "aac": "AAC",
    }

    container = container_map.get(output_format, "RAW")
    codec = codec_map.get(output_format, "MP3")

    # Build the output S3 destination (MediaConvert appends file extension)
    # We specify the full path without extension as the destination
    output_destination = f"s3://{s3_bucket}/{output_s3_key.rsplit('.', 1)[0]}"

    settings: dict = {
        "Inputs": [
            {
                "FileInput": f"s3://{s3_bucket}/{s3_input_key}",
                "AudioSelectors": {
                    "Audio Selector 1": {
                        "DefaultSelection": "DEFAULT",
                    }
                },
            }
        ],
        "OutputGroups": [
            {
                "Name": "Audio Extraction",
                "OutputGroupSettings": {
                    "Type": "FILE_GROUP_SETTINGS",
                    "FileGroupSettings": {
                        "Destination": output_destination,
                    },
                },
                "Outputs": [
                    {
                        "AudioDescriptions": [
                            {
                                "AudioSourceName": "Audio Selector 1",
                                "CodecSettings": {
                                    "Codec": codec,
                                    f"{codec}Settings": {},
                                },
                            }
                        ],
                        "ContainerSettings": {
                            "Container": container,
                        },
                        # No VideoDescription means audio-only output
                    }
                ],
            }
        ],
    }

    return settings


def _submit_mediaconvert_job(
    client: Any,
    settings: dict,
    role_arn: str,
) -> str:
    """Submit a MediaConvert job and return the job ID.

    Args:
        client: The boto3 MediaConvert client.
        settings: The MediaConvert job settings.
        role_arn: The IAM role ARN for MediaConvert to assume.

    Returns:
        The MediaConvert job ID.

    Raises:
        RuntimeError: If the job submission fails.
    """
    try:
        response = client.create_job(
            Role=role_arn,
            Settings=settings,
        )
        job_id = response["Job"]["Id"]
        logger.info("MediaConvert job submitted: %s", job_id)
        return job_id
    except Exception as e:
        logger.error("Failed to submit MediaConvert job: %s", str(e))
        raise RuntimeError(f"MediaConvert job submission failed: {str(e)}") from e


def _poll_job_completion(
    client: Any,
    job_id: str,
    poll_interval: int = DEFAULT_POLL_INTERVAL_SECONDS,
    max_attempts: int = MAX_POLL_ATTEMPTS,
) -> str:
    """Poll a MediaConvert job until completion or failure.

    Args:
        client: The boto3 MediaConvert client.
        job_id: The MediaConvert job ID to poll.
        poll_interval: Seconds between poll attempts.
        max_attempts: Maximum number of polling attempts.

    Returns:
        The final job status: "COMPLETE" or "ERROR".

    Raises:
        TimeoutError: If the job does not complete within max_attempts.
    """
    for attempt in range(max_attempts):
        try:
            response = client.get_job(Id=job_id)
            status = response["Job"]["Status"]

            if status == "COMPLETE":
                logger.info("MediaConvert job %s completed successfully.", job_id)
                return "COMPLETE"
            elif status == "ERROR":
                error_message = response["Job"].get("ErrorMessage", "Unknown error")
                logger.error(
                    "MediaConvert job %s failed: %s", job_id, error_message
                )
                return "ERROR"
            elif status in ("SUBMITTED", "PROGRESSING"):
                logger.debug(
                    "MediaConvert job %s status: %s (attempt %d/%d)",
                    job_id,
                    status,
                    attempt + 1,
                    max_attempts,
                )
                time.sleep(poll_interval)
            else:
                logger.warning(
                    "MediaConvert job %s unexpected status: %s", job_id, status
                )
                time.sleep(poll_interval)
        except Exception as e:
            logger.warning(
                "Error polling MediaConvert job %s (attempt %d/%d): %s",
                job_id,
                attempt + 1,
                max_attempts,
                str(e),
            )
            time.sleep(poll_interval)

    raise TimeoutError(
        f"MediaConvert job {job_id} did not complete within "
        f"{max_attempts * poll_interval} seconds."
    )


def extract_audio(
    s3_bucket: str,
    s3_input_key: str,
    user_id: str,
    submission_id: str,
    output_format: str = "mp3",
    mediaconvert_role_arn: str = "",
    mediaconvert_endpoint: str = "",
) -> dict:
    """Submit a MediaConvert job to extract audio from a video file.

    Constructs the output S3 key, submits a MediaConvert job to extract
    audio from the input video, and polls for job completion.

    Args:
        s3_bucket: The S3 bucket containing the input video.
        s3_input_key: The S3 key of the input video file.
        user_id: The user identifier.
        submission_id: The submission identifier.
        output_format: The desired audio output format (default: mp3).
        mediaconvert_role_arn: The IAM role ARN for MediaConvert.
        mediaconvert_endpoint: The MediaConvert account-specific endpoint.

    Returns:
        A dict with:
            - "status": "COMPLETE" | "ERROR"
            - "output_s3_key": the constructed output path
            - "job_id": MediaConvert job ID
    """
    output_s3_key = construct_output_key(user_id, submission_id, output_format)

    logger.info(
        "Starting audio extraction: bucket=%s, input=%s, output=%s",
        s3_bucket,
        s3_input_key,
        output_s3_key,
    )

    # Create the MediaConvert client
    client = _create_mediaconvert_client(mediaconvert_endpoint)

    # Build job settings
    settings = _build_job_settings(
        s3_bucket=s3_bucket,
        s3_input_key=s3_input_key,
        output_s3_key=output_s3_key,
        output_format=output_format,
    )

    # Submit the job
    job_id = _submit_mediaconvert_job(
        client=client,
        settings=settings,
        role_arn=mediaconvert_role_arn,
    )

    # Poll for completion
    try:
        status = _poll_job_completion(client=client, job_id=job_id)
    except TimeoutError:
        logger.error("Audio extraction timed out for job %s", job_id)
        status = "ERROR"

    return {
        "status": status,
        "output_s3_key": output_s3_key,
        "job_id": job_id,
    }
