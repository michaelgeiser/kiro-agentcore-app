"""Lambda handler for publishing handoff messages to the FIFO SQS Handoff Queue."""

import json
import logging
import os
from typing import Any

import boto3

from models.handoff_message import HandoffMessage

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

    # Immediately trigger the evaluation task launcher so the message
    # is processed without waiting for CloudWatch alarm transitions.
    _trigger_eval_task_launcher()

    return {"message_id": message_id}


def _trigger_eval_task_launcher() -> None:
    """Invoke the eval-task-launcher Lambda asynchronously (fire-and-forget).

    This ensures an ECS Fargate Spot task is running to consume the
    handoff message immediately, without relying on CloudWatch alarm
    state transitions which can have delays.
    """
    launcher_fn_name = os.environ.get("EVAL_TASK_LAUNCHER_FN", "")
    if not launcher_fn_name:
        logger.debug("EVAL_TASK_LAUNCHER_FN not set — skipping direct trigger")
        return

    try:
        lambda_client = boto3.client("lambda")
        lambda_client.invoke(
            FunctionName=launcher_fn_name,
            InvocationType="Event",  # Async, fire-and-forget
            Payload=b'{"source": "publish_handoff"}',
        )
        logger.info(
            "Triggered eval task launcher: %s", launcher_fn_name
        )
    except Exception as exc:
        # Best-effort — don't fail the handoff publish if this fails
        logger.warning(
            "Failed to trigger eval task launcher (non-fatal): %s", exc
        )


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda handler entry point.

    Extracts processing results from event and publishes handoff message.
    Queue URL is read from HANDOFF_QUEUE_URL environment variable.

    Args:
        event: Dict containing submission_id, user_id, s3_file_key,
               store_result (with vector_store_location), chunks (with chunk_count),
               presentation_title, and config.
        context: Lambda context object.

    Returns:
        Dict with "message_id" from SQS send response.
    """
    queue_url = event.get("queue_url") or os.environ.get("HANDOFF_QUEUE_URL", "")

    # Handle nested store_result and chunks from Step Functions
    store_result = event.get("store_result", {})
    chunks = event.get("chunks", {})

    return publish_handoff(
        submission_id=event["submission_id"],
        user_id=event["user_id"],
        s3_file_key=event["s3_file_key"],
        vector_store_location=store_result.get("vector_store_location", ""),
        chunk_count=chunks.get("chunk_count", 0),
        presentation_title=event["presentation_title"],
        queue_url=queue_url,
    )
