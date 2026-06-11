"""Lambda handler for workflow failure processing.

Handles all failure scenarios in the Preparation Workflow:
1. Updates DynamoDB Processing_Status to Failed
2. Constructs WorkflowErrorNotification and publishes to SNS (best-effort)
3. Routes the original message to the appropriate DLQ (Input or Handoff)

SNS publish failures are caught and logged but never propagated,
ensuring DLQ routing always succeeds regardless of notification issues.
"""

import json
import logging
from datetime import datetime, timezone

import boto3

from src.models.error_notification import WorkflowErrorNotification

logger = logging.getLogger(__name__)


def handle_failure(
    submission_id: str,
    step_name: str,
    error_type: str,
    error_message: str,
    retry_count_exhausted: int,
    original_message: str,
    failure_source: str,
    dynamodb_table_name: str,
    sns_topic_arn: str,
    dlq_input_url: str,
    dlq_handoff_url: str,
) -> dict:
    """Handle workflow failures: update status, notify, route to DLQ.

    Steps:
    1. Update DynamoDB processing_status to "Failed"
    2. Construct WorkflowErrorNotification and publish to SNS (best-effort)
    3. Route original message to appropriate DLQ based on failure_source

    Args:
        submission_id: The submission that failed.
        step_name: The workflow step where failure occurred.
        error_type: Classification of the error (e.g., "ValidationError").
        error_message: Human-readable error description.
        retry_count_exhausted: Number of retries attempted before failure.
        original_message: The original SQS message body to route to DLQ.
        failure_source: "input" or "handoff" — determines which DLQ to use.
        dynamodb_table_name: Name of the DynamoDB submissions table.
        sns_topic_arn: ARN of the SNS error notification topic.
        dlq_input_url: URL of the Input DLQ.
        dlq_handoff_url: URL of the Handoff DLQ.

    Returns:
        Dict with:
        - "dynamodb_updated": bool
        - "sns_published": bool (False if SNS publish fails, no exception raised)
        - "dlq_routed": bool
        - "dlq_used": "input" or "handoff"
    """
    result = {
        "dynamodb_updated": False,
        "sns_published": False,
        "dlq_routed": False,
        "dlq_used": failure_source,
    }

    # Step 1: Update DynamoDB processing_status to "Failed"
    dynamodb = boto3.client("dynamodb")
    dynamodb.update_item(
        TableName=dynamodb_table_name,
        Key={"submission_id": {"S": submission_id}},
        UpdateExpression="SET processing_status = :status",
        ExpressionAttributeValues={":status": {"S": "Failed"}},
    )
    result["dynamodb_updated"] = True

    # Step 2: Construct WorkflowErrorNotification and publish to SNS (best-effort)
    timestamp = datetime.now(timezone.utc).isoformat()
    dlq_name = "DLQ_Input" if failure_source == "input" else "DLQ_Handoff"

    notification = WorkflowErrorNotification(
        submission_id=submission_id,
        step_name=step_name,
        error_type=error_type,
        error_message=error_message,
        retry_count_exhausted=retry_count_exhausted,
        timestamp=timestamp,
        queue_name=dlq_name,
    )

    try:
        sns = boto3.client("sns")
        sns.publish(
            TopicArn=sns_topic_arn,
            Message=notification.model_dump_json(),
            Subject=f"Workflow Failure: {step_name} - {submission_id}",
        )
        result["sns_published"] = True
    except Exception as e:
        logger.error(
            "Failed to publish SNS error notification for submission %s: %s",
            submission_id,
            str(e),
        )
        # Best-effort: do NOT propagate SNS failures

    # Step 3: Route original message to appropriate DLQ
    sqs = boto3.client("sqs")
    dlq_url = dlq_input_url if failure_source == "input" else dlq_handoff_url

    send_kwargs = {
        "QueueUrl": dlq_url,
        "MessageBody": original_message,
    }

    # FIFO queues (handoff DLQ) require MessageGroupId and deduplication
    if failure_source == "handoff":
        send_kwargs["MessageGroupId"] = submission_id
        send_kwargs["MessageDeduplicationId"] = (
            f"{submission_id}-{step_name}-{timestamp}"
        )

    sqs.send_message(**send_kwargs)
    result["dlq_routed"] = True

    return result


def handler(event, context):
    """Lambda handler entry point.

    Extracts failure context from Step Functions error output.

    Args:
        event: Dict containing failure context:
            - submission_id: The submission that failed
            - step_name: The step where failure occurred
            - error_type: Classification of the error
            - error_message: Human-readable error description
            - retry_count_exhausted: Number of retries attempted
            - original_message: Original SQS message body
            - failure_source: "input" or "handoff"
            - dynamodb_table_name: DynamoDB table name
            - sns_topic_arn: SNS topic ARN
            - dlq_input_url: Input DLQ URL
            - dlq_handoff_url: Handoff DLQ URL
        context: Lambda context (unused).

    Returns:
        Result dict from handle_failure.
    """
    return handle_failure(
        submission_id=event["submission_id"],
        step_name=event["step_name"],
        error_type=event["error_type"],
        error_message=event["error_message"],
        retry_count_exhausted=event["retry_count_exhausted"],
        original_message=event["original_message"],
        failure_source=event["failure_source"],
        dynamodb_table_name=event["dynamodb_table_name"],
        sns_topic_arn=event["sns_topic_arn"],
        dlq_input_url=event["dlq_input_url"],
        dlq_handoff_url=event["dlq_handoff_url"],
    )
