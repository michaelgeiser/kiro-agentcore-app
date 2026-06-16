"""Unit tests for the StatusManager service.

Tests all status transitions, failure_reason enforcement,
report_path inclusion, and error handling.

Requirements: 10.1, 10.2, 10.3, 10.4, 10.5
"""

import boto3
import pytest
from moto import mock_aws

from models.data_models import ProcessingStatus
from services.status_manager import StatusManager


@pytest.fixture
def dynamodb_table():
    """Create a mocked DynamoDB table for testing."""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        table = dynamodb.create_table(
            TableName="test-submissions",
            KeySchema=[{"AttributeName": "submission_id", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "submission_id", "AttributeType": "S"}
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        # Insert a test submission
        table.put_item(
            Item={
                "submission_id": "sub-123",
                "processing_status": "Pending",
                "user_id": "user-abc",
            }
        )
        yield dynamodb


class TestStatusManagerUpdateStatus:
    """Tests for StatusManager.update_status() method."""

    def test_update_status_to_evaluating(self, dynamodb_table):
        """Status can be updated to Evaluating."""
        manager = StatusManager(
            table_name="test-submissions",
            dynamodb_resource=dynamodb_table,
        )
        manager.update_status("sub-123", ProcessingStatus.EVALUATING)

        # Verify the status was updated
        table = dynamodb_table.Table("test-submissions")
        item = table.get_item(Key={"submission_id": "sub-123"})["Item"]
        assert item["processing_status"] == "Evaluating"
        assert "updated_at" in item

    def test_update_status_to_report_generating(self, dynamodb_table):
        """Status can be updated to Report_Generating."""
        manager = StatusManager(
            table_name="test-submissions",
            dynamodb_resource=dynamodb_table,
        )
        manager.update_status("sub-123", ProcessingStatus.REPORT_GENERATING)

        table = dynamodb_table.Table("test-submissions")
        item = table.get_item(Key={"submission_id": "sub-123"})["Item"]
        assert item["processing_status"] == "Report_Generating"

    def test_update_status_to_completed_with_report_path(self, dynamodb_table):
        """Completed status stores the report_path in DynamoDB."""
        manager = StatusManager(
            table_name="test-submissions",
            dynamodb_resource=dynamodb_table,
        )
        report_path = "reports/user-abc/sub-123/coaching_report.pdf"
        manager.update_status(
            "sub-123",
            ProcessingStatus.COMPLETED,
            report_path=report_path,
        )

        table = dynamodb_table.Table("test-submissions")
        item = table.get_item(Key={"submission_id": "sub-123"})["Item"]
        assert item["processing_status"] == "Completed"
        assert item["report_path"] == report_path

    def test_update_status_to_failed_with_reason(self, dynamodb_table):
        """Failed status stores the failure_reason in DynamoDB."""
        manager = StatusManager(
            table_name="test-submissions",
            dynamodb_resource=dynamodb_table,
        )
        manager.update_status(
            "sub-123",
            ProcessingStatus.FAILED,
            failure_reason="Agent timeout after 3 retries",
        )

        table = dynamodb_table.Table("test-submissions")
        item = table.get_item(Key={"submission_id": "sub-123"})["Item"]
        assert item["processing_status"] == "Failed"
        assert item["failure_reason"] == "Agent timeout after 3 retries"

    def test_failed_without_reason_raises_value_error(self, dynamodb_table):
        """Setting Failed status without failure_reason raises ValueError."""
        manager = StatusManager(
            table_name="test-submissions",
            dynamodb_resource=dynamodb_table,
        )
        with pytest.raises(ValueError, match="failure_reason must be non-empty"):
            manager.update_status("sub-123", ProcessingStatus.FAILED)

    def test_failed_with_empty_reason_raises_value_error(self, dynamodb_table):
        """Setting Failed status with empty failure_reason raises ValueError."""
        manager = StatusManager(
            table_name="test-submissions",
            dynamodb_resource=dynamodb_table,
        )
        with pytest.raises(ValueError, match="failure_reason must be non-empty"):
            manager.update_status(
                "sub-123",
                ProcessingStatus.FAILED,
                failure_reason="",
            )

    def test_update_status_sets_updated_at_timestamp(self, dynamodb_table):
        """Every status update sets the updated_at field."""
        manager = StatusManager(
            table_name="test-submissions",
            dynamodb_resource=dynamodb_table,
        )
        manager.update_status("sub-123", ProcessingStatus.EVALUATING)

        table = dynamodb_table.Table("test-submissions")
        item = table.get_item(Key={"submission_id": "sub-123"})["Item"]
        assert "updated_at" in item
        # Verify it looks like an ISO 8601 timestamp
        assert "T" in item["updated_at"]

    def test_completed_without_report_path_allowed(self, dynamodb_table):
        """Completed status without report_path is technically allowed."""
        manager = StatusManager(
            table_name="test-submissions",
            dynamodb_resource=dynamodb_table,
        )
        # While the design says report_path "should" be included,
        # we don't enforce it as a hard requirement
        manager.update_status("sub-123", ProcessingStatus.COMPLETED)

        table = dynamodb_table.Table("test-submissions")
        item = table.get_item(Key={"submission_id": "sub-123"})["Item"]
        assert item["processing_status"] == "Completed"
        assert "report_path" not in item

    def test_update_nonexistent_submission_creates_item(self, dynamodb_table):
        """Updating a non-existent submission creates the item (DynamoDB upsert behavior)."""
        manager = StatusManager(
            table_name="test-submissions",
            dynamodb_resource=dynamodb_table,
        )
        manager.update_status("sub-new", ProcessingStatus.EVALUATING)

        table = dynamodb_table.Table("test-submissions")
        item = table.get_item(Key={"submission_id": "sub-new"})["Item"]
        assert item["processing_status"] == "Evaluating"


class TestStatusManagerConstruction:
    """Tests for StatusManager construction."""

    def test_accepts_custom_dynamodb_resource(self, dynamodb_table):
        """StatusManager accepts a custom DynamoDB resource."""
        manager = StatusManager(
            table_name="test-submissions",
            dynamodb_resource=dynamodb_table,
        )
        assert manager._table_name == "test-submissions"

    def test_default_resource_created_if_not_provided(self):
        """StatusManager creates a default boto3 resource if none provided."""
        # This just verifies construction doesn't fail
        # (the actual DynamoDB call would fail without mocking)
        with mock_aws():
            boto3.resource("dynamodb", region_name="us-east-1").create_table(
                TableName="default-table",
                KeySchema=[{"AttributeName": "submission_id", "KeyType": "HASH"}],
                AttributeDefinitions=[
                    {"AttributeName": "submission_id", "AttributeType": "S"}
                ],
                BillingMode="PAY_PER_REQUEST",
            )
            manager = StatusManager(table_name="default-table")
            # Should be able to update without error
            manager.update_status("sub-1", ProcessingStatus.EVALUATING)
