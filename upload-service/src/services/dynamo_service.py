"""DynamoDB service for submission record persistence and retrieval."""

import os
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key

from src.models.submission import SubmissionRecord


class DynamoService:
    """Service for interacting with DynamoDB submission records."""

    def __init__(self) -> None:
        self._resource = boto3.resource("dynamodb")
        self._table_name = os.environ["DYNAMODB_TABLE_NAME"]
        self._table = self._resource.Table(self._table_name)

    def create_submission(self, record: SubmissionRecord) -> None:
        """Create a new submission record in DynamoDB.

        Args:
            record: The SubmissionRecord to persist.
        """
        item: dict[str, Any] = record.model_dump()
        # Remove None values to avoid storing empty attributes
        item = {k: v for k, v in item.items() if v is not None}
        self._table.put_item(Item=item)

    def get_submissions_by_user(self, user_id: str) -> list[SubmissionRecord]:
        """Query submissions by user_id, sorted by upload_date descending.

        Uses the GSI 'user-uploads-index' with ScanIndexForward=False
        for descending sort order (most recent first).

        Args:
            user_id: The authenticated user's identifier.

        Returns:
            List of SubmissionRecord instances sorted by upload_date descending.
        """
        response = self._table.query(
            IndexName="user-uploads-index",
            KeyConditionExpression=Key("user_id").eq(user_id),
            ScanIndexForward=False,
        )
        items: list[dict[str, Any]] = response.get("Items", [])
        return [SubmissionRecord(**item) for item in items]

    def update_status(
        self, submission_id: str, status: str, **additional_fields: str | None
    ) -> None:
        """Update submission processing status and optional additional fields.

        Args:
            submission_id: The partition key of the submission to update.
            status: The new processing status value.
            **additional_fields: Optional additional fields to update
                (e.g., completion_date, report_link).
        """
        update_expression = "SET processing_status = :status"
        expression_values: dict[str, Any] = {":status": status}

        for field_name, field_value in additional_fields.items():
            update_expression += f", {field_name} = :{field_name}"
            expression_values[f":{field_name}"] = field_value

        self._table.update_item(
            Key={"submission_id": submission_id},
            UpdateExpression=update_expression,
            ExpressionAttributeValues=expression_values,
        )
