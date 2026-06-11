"""Unit tests for the handle_failure handler.

Tests cover:
- DynamoDB status update to Failed
- SNS notification construction and publish (best-effort)
- DLQ routing to correct queue based on failure_source
- SNS publish failure does not propagate
"""

import json
from unittest.mock import MagicMock, patch

import boto3
import pytest
from moto import mock_aws

from src.handlers.handle_failure import handle_failure, handler


@pytest.fixture
def aws_setup():
    """Set up mocked AWS resources for testing."""
    with mock_aws():
        # Create DynamoDB table
        dynamodb = boto3.client("dynamodb", region_name="us-east-1")
        dynamodb.create_table(
            TableName="submissions",
            KeySchema=[{"AttributeName": "submission_id", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "submission_id", "AttributeType": "S"}
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        # Insert a test submission
        dynamodb.put_item(
            TableName="submissions",
            Item={
                "submission_id": {"S": "sub-123"},
                "processing_status": {"S": "Processing"},
            },
        )

        # Create SNS topic
        sns = boto3.client("sns", region_name="us-east-1")
        topic_response = sns.create_topic(Name="error-notifications")
        topic_arn = topic_response["TopicArn"]

        # Create SQS queues (standard for input DLQ, FIFO for handoff DLQ)
        sqs = boto3.client("sqs", region_name="us-east-1")
        input_dlq = sqs.create_queue(QueueName="dlq-input")
        handoff_dlq = sqs.create_queue(
            QueueName="dlq-handoff.fifo",
            Attributes={"FifoQueue": "true", "ContentBasedDeduplication": "false"},
        )

        yield {
            "dynamodb_table_name": "submissions",
            "sns_topic_arn": topic_arn,
            "dlq_input_url": input_dlq["QueueUrl"],
            "dlq_handoff_url": handoff_dlq["QueueUrl"],
        }


class TestHandleFailureInputDLQ:
    """Tests for routing failures to the Input DLQ."""

    def test_updates_dynamodb_status_to_failed(self, aws_setup):
        """DynamoDB processing_status is updated to Failed."""
        result = handle_failure(
            submission_id="sub-123",
            step_name="ValidateFileFormat",
            error_type="ValidationError",
            error_message="Unsupported file format: .exe",
            retry_count_exhausted=3,
            original_message='{"submission_id": "sub-123"}',
            failure_source="input",
            dynamodb_table_name=aws_setup["dynamodb_table_name"],
            sns_topic_arn=aws_setup["sns_topic_arn"],
            dlq_input_url=aws_setup["dlq_input_url"],
            dlq_handoff_url=aws_setup["dlq_handoff_url"],
        )

        assert result["dynamodb_updated"] is True

        # Verify DynamoDB was actually updated
        dynamodb = boto3.client("dynamodb", region_name="us-east-1")
        item = dynamodb.get_item(
            TableName="submissions",
            Key={"submission_id": {"S": "sub-123"}},
        )
        assert item["Item"]["processing_status"]["S"] == "Failed"

    def test_publishes_sns_notification(self, aws_setup):
        """SNS error notification is published successfully."""
        result = handle_failure(
            submission_id="sub-123",
            step_name="CreateEmbeddings",
            error_type="BedrockThrottleError",
            error_message="Rate limit exceeded",
            retry_count_exhausted=3,
            original_message='{"submission_id": "sub-123"}',
            failure_source="input",
            dynamodb_table_name=aws_setup["dynamodb_table_name"],
            sns_topic_arn=aws_setup["sns_topic_arn"],
            dlq_input_url=aws_setup["dlq_input_url"],
            dlq_handoff_url=aws_setup["dlq_handoff_url"],
        )

        assert result["sns_published"] is True

    def test_routes_to_input_dlq(self, aws_setup):
        """Original message is routed to Input DLQ when failure_source is 'input'."""
        original_msg = '{"submission_id": "sub-123", "user_id": "user-456"}'

        result = handle_failure(
            submission_id="sub-123",
            step_name="StoreVectors",
            error_type="VectorStoreError",
            error_message="Connection timeout",
            retry_count_exhausted=3,
            original_message=original_msg,
            failure_source="input",
            dynamodb_table_name=aws_setup["dynamodb_table_name"],
            sns_topic_arn=aws_setup["sns_topic_arn"],
            dlq_input_url=aws_setup["dlq_input_url"],
            dlq_handoff_url=aws_setup["dlq_handoff_url"],
        )

        assert result["dlq_routed"] is True
        assert result["dlq_used"] == "input"

        # Verify message was sent to input DLQ
        sqs = boto3.client("sqs", region_name="us-east-1")
        messages = sqs.receive_message(
            QueueUrl=aws_setup["dlq_input_url"], MaxNumberOfMessages=1
        )
        assert len(messages["Messages"]) == 1
        assert messages["Messages"][0]["Body"] == original_msg


class TestHandleFailureHandoffDLQ:
    """Tests for routing failures to the Handoff DLQ."""

    def test_routes_to_handoff_dlq(self, aws_setup):
        """Original message is routed to Handoff DLQ when failure_source is 'handoff'."""
        original_msg = '{"submission_id": "sub-123"}'

        result = handle_failure(
            submission_id="sub-123",
            step_name="PublishHandoff",
            error_type="SQSPublishError",
            error_message="Queue not available",
            retry_count_exhausted=3,
            original_message=original_msg,
            failure_source="handoff",
            dynamodb_table_name=aws_setup["dynamodb_table_name"],
            sns_topic_arn=aws_setup["sns_topic_arn"],
            dlq_input_url=aws_setup["dlq_input_url"],
            dlq_handoff_url=aws_setup["dlq_handoff_url"],
        )

        assert result["dlq_routed"] is True
        assert result["dlq_used"] == "handoff"

        # Verify message was sent to handoff DLQ (FIFO)
        sqs = boto3.client("sqs", region_name="us-east-1")
        messages = sqs.receive_message(
            QueueUrl=aws_setup["dlq_handoff_url"], MaxNumberOfMessages=1
        )
        assert len(messages["Messages"]) == 1
        assert messages["Messages"][0]["Body"] == original_msg


class TestSNSBestEffort:
    """Tests for SNS best-effort publish behavior."""

    def test_sns_failure_does_not_propagate(self, aws_setup):
        """SNS publish failure is caught and logged, not propagated."""
        # Use an invalid topic ARN to trigger an SNS failure
        result = handle_failure(
            submission_id="sub-123",
            step_name="ExtractAudio",
            error_type="MediaConvertError",
            error_message="Job failed",
            retry_count_exhausted=3,
            original_message='{"submission_id": "sub-123"}',
            failure_source="input",
            dynamodb_table_name=aws_setup["dynamodb_table_name"],
            sns_topic_arn="arn:aws:sns:us-east-1:000000000000:nonexistent-topic",
            dlq_input_url=aws_setup["dlq_input_url"],
            dlq_handoff_url=aws_setup["dlq_handoff_url"],
        )

        # Handler should complete without raising
        assert result["dynamodb_updated"] is True
        assert result["sns_published"] is False
        assert result["dlq_routed"] is True

    @patch("src.handlers.handle_failure.boto3.client")
    def test_sns_exception_logged_and_swallowed(self, mock_boto_client):
        """SNS exception is logged but does not affect DLQ routing."""
        # Set up mock clients
        mock_dynamodb = MagicMock()
        mock_sns = MagicMock()
        mock_sqs = MagicMock()

        def client_factory(service, **kwargs):
            if service == "dynamodb":
                return mock_dynamodb
            elif service == "sns":
                return mock_sns
            elif service == "sqs":
                return mock_sqs
            return MagicMock()

        mock_boto_client.side_effect = client_factory
        mock_sns.publish.side_effect = Exception("SNS is down")

        result = handle_failure(
            submission_id="sub-123",
            step_name="CreateEmbeddings",
            error_type="ServiceError",
            error_message="Something went wrong",
            retry_count_exhausted=2,
            original_message='{"submission_id": "sub-123"}',
            failure_source="input",
            dynamodb_table_name="submissions",
            sns_topic_arn="arn:aws:sns:us-east-1:123456789:topic",
            dlq_input_url="https://sqs.us-east-1.amazonaws.com/123/dlq-input",
            dlq_handoff_url="https://sqs.us-east-1.amazonaws.com/123/dlq-handoff.fifo",
        )

        assert result["dynamodb_updated"] is True
        assert result["sns_published"] is False
        assert result["dlq_routed"] is True
        mock_sqs.send_message.assert_called_once()


class TestLambdaHandler:
    """Tests for the Lambda handler entry point."""

    def test_handler_extracts_event_fields(self, aws_setup):
        """Lambda handler correctly extracts fields from the event."""
        event = {
            "submission_id": "sub-123",
            "step_name": "ValidateFileFormat",
            "error_type": "ValidationError",
            "error_message": "Invalid format",
            "retry_count_exhausted": 0,
            "original_message": '{"submission_id": "sub-123"}',
            "failure_source": "input",
            "dynamodb_table_name": aws_setup["dynamodb_table_name"],
            "sns_topic_arn": aws_setup["sns_topic_arn"],
            "dlq_input_url": aws_setup["dlq_input_url"],
            "dlq_handoff_url": aws_setup["dlq_handoff_url"],
        }

        result = handler(event, None)

        assert result["dynamodb_updated"] is True
        assert result["sns_published"] is True
        assert result["dlq_routed"] is True
        assert result["dlq_used"] == "input"
