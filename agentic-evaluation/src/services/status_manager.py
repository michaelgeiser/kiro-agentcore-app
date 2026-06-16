"""Status Manager for submission processing status in DynamoDB.

Manages DynamoDB status transitions with consistent error handling.
Updates the processing status of submissions throughout the evaluation
session lifecycle (Evaluating → Report_Generating → Completed / Failed).
"""

import logging
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

from models.data_models import ProcessingStatus

logger = logging.getLogger(__name__)


class StatusManager:
    """Manages submission processing status in DynamoDB.

    The StatusManager updates a DynamoDB table with the processing status
    of a submission. It enforces business rules:
    - When status is Failed, failure_reason MUST be non-empty.
    - When status is Completed, report_path should be included.

    Args:
        table_name: Name of the DynamoDB submissions table.
        dynamodb_resource: Optional boto3 DynamoDB resource. If not provided,
            a default resource is created using boto3.resource("dynamodb").
    """

    def __init__(
        self,
        table_name: str,
        dynamodb_resource=None,
    ) -> None:
        self._table_name = table_name
        self._dynamodb_resource = dynamodb_resource or boto3.resource("dynamodb")
        self._table = self._dynamodb_resource.Table(self._table_name)

    def update_status(
        self,
        submission_id: str,
        status: ProcessingStatus,
        report_path: str | None = None,
        failure_reason: str | None = None,
    ) -> None:
        """Update the processing status of a submission in DynamoDB.

        Args:
            submission_id: Unique identifier for the submission.
            status: The new processing status to set.
            report_path: S3 path to the coaching report (used when status is Completed).
            failure_reason: Reason for failure (required when status is Failed).

        Raises:
            ValueError: If status is Failed but failure_reason is empty or None.
            ClientError: If the DynamoDB update operation fails.
        """
        if status == ProcessingStatus.FAILED:
            if not failure_reason:
                raise ValueError(
                    "failure_reason must be non-empty when status is Failed"
                )

        # Build the update expression and attribute values
        update_parts = ["SET processing_status = :status, updated_at = :updated_at"]
        expression_values: dict = {
            ":status": status.value,
            ":updated_at": datetime.now(timezone.utc).isoformat(),
        }

        if report_path is not None:
            update_parts.append("report_path = :report_path")
            expression_values[":report_path"] = report_path

        if failure_reason is not None:
            update_parts.append("failure_reason = :failure_reason")
            expression_values[":failure_reason"] = failure_reason

        # Join additional attributes with commas after the SET keyword
        # The first part already has "SET processing_status = :status, updated_at = :updated_at"
        # Additional parts need to be appended with commas
        if len(update_parts) > 1:
            update_expression = update_parts[0] + ", " + ", ".join(update_parts[1:])
        else:
            update_expression = update_parts[0]

        try:
            self._table.update_item(
                Key={"submission_id": submission_id},
                UpdateExpression=update_expression,
                ExpressionAttributeValues=expression_values,
            )
            logger.info(
                "Updated status for submission %s to %s",
                submission_id,
                status.value,
            )
        except ClientError as e:
            logger.error(
                "Failed to update status for submission %s to %s: %s",
                submission_id,
                status.value,
                e.response["Error"]["Message"],
            )
            raise
