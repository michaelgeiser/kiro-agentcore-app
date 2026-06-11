"""Unit tests for SNS best-effort notification behavior.

Tests that the SNS service publishes error notifications successfully
and that boto3 exceptions are caught without propagating to callers.

Requirements: 8.3
"""

import os
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from src.models.submission import ErrorNotification, ErrorType
from src.services.sns_service import SnsService


@pytest.fixture
def sample_notification():
    """Create a sample error notification for testing."""
    return ErrorNotification(
        submission_id="sub-abc-123",
        error_type=ErrorType.DYNAMO_WRITE_FAILURE,
        error_message="ConditionalCheckFailedException",
        timestamp="2024-07-01T12:00:00Z",
        service_component="upload-handler",
    )


@pytest.fixture
def sns_service_with_mock_client():
    """Create an SnsService with a mocked boto3 client."""
    topic_arn = "arn:aws:sns:us-east-1:123456789012:test-errors"
    with patch.dict(os.environ, {"SNS_TOPIC_ARN": topic_arn}):
        with patch("src.services.sns_service.boto3.client") as mock_boto_client:
            mock_client = MagicMock()
            mock_boto_client.return_value = mock_client
            service = SnsService()
            yield service, mock_client


class TestSnsServiceSuccessfulPublish:
    """Tests for successful SNS notification publish."""

    def test_publish_calls_sns_with_correct_topic_arn(
        self, sns_service_with_mock_client, sample_notification
    ):
        """publish_error_notification should call SNS publish with the configured topic ARN."""
        service, mock_client = sns_service_with_mock_client

        service.publish_error_notification(sample_notification)

        mock_client.publish.assert_called_once()
        call_kwargs = mock_client.publish.call_args[1]
        assert call_kwargs["TopicArn"] == "arn:aws:sns:us-east-1:123456789012:test-errors"

    def test_publish_sends_json_serialized_message(
        self, sns_service_with_mock_client, sample_notification
    ):
        """The message body should be the JSON serialization of the notification."""
        service, mock_client = sns_service_with_mock_client

        service.publish_error_notification(sample_notification)

        call_kwargs = mock_client.publish.call_args[1]
        message = call_kwargs["Message"]
        assert "sub-abc-123" in message
        assert "DYNAMO_WRITE_FAILURE" in message
        assert "ConditionalCheckFailedException" in message

    def test_publish_sets_subject_with_error_type(
        self, sns_service_with_mock_client, sample_notification
    ):
        """The SNS subject should include the error type."""
        service, mock_client = sns_service_with_mock_client

        service.publish_error_notification(sample_notification)

        call_kwargs = mock_client.publish.call_args[1]
        assert call_kwargs["Subject"] == "Error: DYNAMO_WRITE_FAILURE"

    def test_publish_returns_none_on_success(
        self, sns_service_with_mock_client, sample_notification
    ):
        """publish_error_notification should return None (no return value)."""
        service, mock_client = sns_service_with_mock_client

        result = service.publish_error_notification(sample_notification)

        assert result is None


class TestSnsServiceBestEffortBehavior:
    """Tests that boto3 exceptions are caught and do not propagate."""

    def test_generic_exception_does_not_propagate(
        self, sns_service_with_mock_client, sample_notification
    ):
        """A generic Exception from boto3 publish should be caught silently."""
        service, mock_client = sns_service_with_mock_client
        mock_client.publish.side_effect = Exception("Network timeout")

        # Should NOT raise
        service.publish_error_notification(sample_notification)

    def test_client_error_does_not_propagate(
        self, sns_service_with_mock_client, sample_notification
    ):
        """A boto3 ClientError should be caught and not re-raised."""
        service, mock_client = sns_service_with_mock_client
        mock_client.publish.side_effect = ClientError(
            {"Error": {"Code": "InvalidParameter", "Message": "Invalid topic ARN"}},
            "Publish",
        )

        # Should NOT raise
        service.publish_error_notification(sample_notification)

    def test_authorization_error_does_not_propagate(
        self, sns_service_with_mock_client, sample_notification
    ):
        """An authorization error from SNS should be caught and not re-raised."""
        service, mock_client = sns_service_with_mock_client
        mock_client.publish.side_effect = ClientError(
            {"Error": {"Code": "AuthorizationError", "Message": "Not authorized"}},
            "Publish",
        )

        # Should NOT raise
        service.publish_error_notification(sample_notification)

    def test_endpoint_disabled_error_does_not_propagate(
        self, sns_service_with_mock_client, sample_notification
    ):
        """An EndpointDisabled error from SNS should be caught and not re-raised."""
        service, mock_client = sns_service_with_mock_client
        mock_client.publish.side_effect = ClientError(
            {"Error": {"Code": "EndpointDisabled", "Message": "Endpoint disabled"}},
            "Publish",
        )

        # Should NOT raise
        service.publish_error_notification(sample_notification)

    def test_exception_is_logged(
        self, sns_service_with_mock_client, sample_notification, caplog
    ):
        """When publish fails, the exception should be logged."""
        import logging

        service, mock_client = sns_service_with_mock_client
        mock_client.publish.side_effect = Exception("Connection refused")

        with caplog.at_level(logging.ERROR):
            service.publish_error_notification(sample_notification)

        assert "Failed to publish error notification to SNS" in caplog.text
        assert "sub-abc-123" in caplog.text
