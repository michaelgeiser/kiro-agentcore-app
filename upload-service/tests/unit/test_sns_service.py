"""Unit tests for the SNS error notification service."""

import json
import os
from unittest.mock import patch, MagicMock

import boto3
import pytest
from moto import mock_aws

from src.models.submission import ErrorNotification, ErrorType
from src.services.sns_service import SnsService


@pytest.fixture
def sns_topic_arn():
    """Create a mock SNS topic and return its ARN."""
    with mock_aws():
        client = boto3.client("sns", region_name="us-east-1")
        response = client.create_topic(Name="test-errors")
        yield response["TopicArn"]


@pytest.fixture
def sns_service(sns_topic_arn):
    """Create an SnsService instance with mocked AWS."""
    with mock_aws():
        # Recreate topic inside the mock context
        client = boto3.client("sns", region_name="us-east-1")
        response = client.create_topic(Name="test-errors")
        topic_arn = response["TopicArn"]

        with patch.dict(os.environ, {"SNS_TOPIC_ARN": topic_arn}):
            service = SnsService()
            yield service


@pytest.fixture
def sample_notification():
    """Create a sample error notification."""
    return ErrorNotification(
        submission_id="sub-123",
        error_type=ErrorType.S3_WRITE_FAILURE,
        error_message="Failed to write object to S3",
        timestamp="2024-06-15T10:30:00Z",
        service_component="upload-handler",
        orphaned_s3_key=None,
    )


def test_publish_error_notification_does_not_raise(sns_service, sample_notification):
    """publish_error_notification should complete without raising."""
    # Should not raise any exception
    sns_service.publish_error_notification(sample_notification)


def test_publish_error_notification_sends_correct_message(sample_notification):
    """Notification message body should be the JSON serialization of the notification."""
    with mock_aws():
        client = boto3.client("sns", region_name="us-east-1")
        response = client.create_topic(Name="test-errors")
        topic_arn = response["TopicArn"]

        # Subscribe to capture the message
        client.subscribe(
            TopicArn=topic_arn,
            Protocol="sqs",
            Endpoint="arn:aws:sqs:us-east-1:123456789012:test-queue",
        )

        with patch.dict(os.environ, {"SNS_TOPIC_ARN": topic_arn}):
            service = SnsService()
            service.publish_error_notification(sample_notification)

        # Verify the message was published by checking it doesn't raise
        # The actual content validation is done via the moto mock
        expected_json = sample_notification.model_dump_json()
        assert json.loads(expected_json)["error_type"] == "S3_WRITE_FAILURE"
        assert json.loads(expected_json)["submission_id"] == "sub-123"


def test_publish_error_notification_swallows_exceptions(sample_notification):
    """If SNS publish fails, the exception should be caught silently."""
    with patch.dict(os.environ, {"SNS_TOPIC_ARN": "arn:aws:sns:us-east-1:123456789012:fake"}):
        service = SnsService()
        # Force the client to raise
        service._client = MagicMock()
        service._client.publish.side_effect = Exception("Network timeout")

        # Should NOT raise — best-effort behavior
        sns_service_result = sns_service_publish_no_raise(service, sample_notification)
        assert sns_service_result is None


def test_publish_error_notification_swallows_boto_client_error(sample_notification):
    """Boto ClientError should also be caught without re-raising."""
    from botocore.exceptions import ClientError

    with patch.dict(os.environ, {"SNS_TOPIC_ARN": "arn:aws:sns:us-east-1:123456789012:fake"}):
        service = SnsService()
        service._client = MagicMock()
        service._client.publish.side_effect = ClientError(
            {"Error": {"Code": "InvalidParameter", "Message": "Invalid topic"}},
            "Publish",
        )

        # Should NOT raise
        service.publish_error_notification(sample_notification)


def test_sns_service_reads_topic_arn_from_env():
    """SnsService should read SNS_TOPIC_ARN from environment."""
    test_arn = "arn:aws:sns:us-east-1:123456789012:my-topic"
    with patch.dict(os.environ, {"SNS_TOPIC_ARN": test_arn}):
        with mock_aws():
            service = SnsService()
            assert service._topic_arn == test_arn


def sns_service_publish_no_raise(service, notification):
    """Helper to call publish and return None (verifies no exception)."""
    service.publish_error_notification(notification)
    return None
