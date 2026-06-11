"""Lambda handler for publishing handoff messages to the FIFO SQS Handoff Queue."""

import json
import logging
from typing import Any

import boto3

from src.models.handoff_message import HandoffMessage

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def publish_handoff(
    submission_id: str,
    user_id: str,
    s3_file_key: str,
    vector_store_location: str,
    chunk_count: int,
    presentation_title: str,
    queue_url: str,
) -> dict:
    """Construct HandoffMessage and publish to FIFO SQS Handoff Queue.

    Args:
        submission_id: The submission ID
        user_id: The user ID
        s3_file_key: S3 key of the processed file
        vector_store_location: Where embeddings are stored
        chunk_count: Number of chunks processed
        presentation_title: Title of the presentation
        queue_url: URL of the FIFO SQS Handoff Queue

    Returns:
        Dict with "message_id" from SQS send response.

    Raises:
        ValueError: If any required field is invalid.
        botocore.exceptions.ClientError: If SQS publish fails.
    """
    # Construct and validate the HandoffMessage via Pydantic
    message = HandoffMessage(
        submission_id=submission_id,
        user_id=user_id,
        s3_file_key=s3_file_key,
        vector_store_location=vector_store_location,
        chunk_count=chunk_count,
        presentation_title=presentation_title,
    )

    message_body = message.model_dump_json()

    logger.info(
        "Publishing handoff message for submission_id=%s to queue=%s",
        submission_id,
        queue_url,
    )

    sqs_client = boto3.client("sqs")
    response = sqs_client.send_message(
        QueueUrl=queue_url,
        MessageBody=message_body,
        MessageGroupId=submission_id,
        MessageDeduplicationId=f"{submission_id}-handoff",
    )

    message_id = response["MessageId"]
    logger.info(
        "Successfully published handoff message: message_id=%s", message_id
    )

    return {"message_id": message_id}


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda handler entry point.

    Extracts processing results from event and publishes handoff message.
    Event should contain all fields needed to construct HandoffMessage plus queue_url.

    Args:
        event: Dict containing submission_id, user_id, s3_file_key,
               vector_store_location, chunk_count, presentation_title,
               and queue_url.
        context: Lambda context object.

    Returns:
        Dict with "message_id" from SQS send response.
    """
    return publish_handoff(
        submission_id=event["submission_id"],
        user_id=event["user_id"],
        s3_file_key=event["s3_file_key"],
        vector_store_location=event["vector_store_location"],
        chunk_count=event["chunk_count"],
        presentation_title=event["presentation_title"],
        queue_url=event["queue_url"],
    )
