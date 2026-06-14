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

from models.error_notification import WorkflowErrorNotification

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

    Extracts failure context from Step Functions Catch output.
    The event arrives as {"execution_input": <full state>, "error_info": <error details>}.
    We extract submission_id from the parsed message in the execution input.
    """
    import os

    execution_input = event.get("execution_input", event)
    error_info = event.get("error_info", {})

    # Try to extract submission_id from parsed_message in the execution state
    parsed_message = execution_input.get("parsed_message", {}).get("value", {}).get("message", {})
    submission_id = parsed_message.get("submission_id", "unknown")

    # Extract error details
    error_type = error_info.get("Error", error_info.get("error", "Unknown"))
    error_message = error_info.get("Cause", error_info.get("cause", "Unknown error"))

    env_name = os.environ.get("ENV_NAME", "dev")
    resource_prefix = f"prescoach-{env_name}-kiro"

    # Use environment-based defaults for infrastructure references
    dynamodb_table_name = f"{resource_prefix}-submissions"
    sns_topic_arn = os.environ.get("SNS_TOPIC_ARN", f"arn:aws:sns:us-east-1:{os.environ.get('AWS_ACCOUNT_ID', '514917275675')}:prescoach-{env_name}-preparation-errors")
    dlq_input_url = os.environ.get("DLQ_INPUT_URL", "")
    dlq_handoff_url = os.environ.get("DLQ_HANDOFF_URL", "")

    return handle_failure(
        submission_id=submission_id,
        step_name="StepFunctions",
        error_type=error_type,
        error_message=error_message[:500] if len(error_message) > 500 else error_message,
        retry_count_exhausted=3,
        original_message=str(parsed_message),
        failure_source="input",
        dynamodb_table_name=dynamodb_table_name,
        sns_topic_arn=sns_topic_arn,
        dlq_input_url=dlq_input_url,
        dlq_handoff_url=dlq_handoff_url,
    )
