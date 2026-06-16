"""Unit tests for the ErrorNotifier service.

Tests notification publishing to SNS, best-effort isolation (SNS failures
are caught and not propagated), and notification format correctness.

Requirements: 11.3
"""

import json
import logging

import boto3
import pytest
from moto import mock_aws

from services.error_notifier import ErrorNotifier


@pytest.fixture
def sns_topic():
    """Create a mocked SNS topic for testing."""
    with mock_aws():
        sns = boto3.client("sns", region_name="us-east-1")
        response = sns.create_topic(Name="test-error-notifications")
        topic_arn = response["TopicArn"]

        # Subscribe an SQS queue to capture messages
        sqs = boto3.client("sqs", region_name="us-east-1")
        queue = sqs.create_queue(QueueName="test-notification-sink")
        queue_url = queue["QueueUrl"]
        queue_attrs = sqs.get_queue_attributes(
            QueueUrl=queue_url, AttributeNames=["QueueArn"]
        )
        queue_arn = queue_attrs["Attributes"]["QueueArn"]

        sns.subscribe(
            TopicArn=topic_arn,
            Protocol="sqs",
            Endpoint=queue_arn,
        )

        yield {
            "sns_client": sns,
            "sqs_client": sqs,
            "topic_arn": topic_arn,
            "queue_url": queue_url,
        }


class TestErrorNotifierNotify:
    """Tests for ErrorNotifier.notify() method."""

    def test_notify_publishes_to_sns(self, sns_topic):
        """notify() publishes a message to the configured SNS topic."""
        notifier = ErrorNotifier(
            topic_arn=sns_topic["topic_arn"],
            sns_client=sns_topic["sns_client"],
        )

        notifier.notify(
            submission_id="sub-001",
            component_name="delivery-evaluator",
            error_type="AgentTimeout",
            error_message="Agent timed out after 30s",
            retry_count_exhausted=3,
        )

        # Read the message from the subscribed SQS queue
        response = sns_topic["sqs_client"].receive_message(
            QueueUrl=sns_topic["queue_url"],
            MaxNumberOfMessages=1,
            WaitTimeSeconds=0,
        )
        messages = response.get("Messages", [])
        assert len(messages) == 1

        # SNS wraps the message in an envelope
        envelope = json.loads(messages[0]["Body"])
        notification = json.loads(envelope["Message"])

        assert notification["submission_id"] == "sub-001"
        assert notification["component_name"] == "delivery-evaluator"
        assert notification["error_type"] == "AgentTimeout"
        assert notification["error_message"] == "Agent timed out after 30s"
        assert notification["retry_count_exhausted"] == 3

    def test_notify_includes_iso8601_timestamp(self, sns_topic):
        """Notification includes a valid ISO 8601 timestamp."""
        notifier = ErrorNotifier(
            topic_arn=sns_topic["topic_arn"],
            sns_client=sns_topic["sns_client"],
        )

        notifier.notify(
            submission_id="sub-002",
            component_name="structure-evaluator",
            error_type="LLMError",
            error_message="Model invocation failed",
            retry_count_exhausted=2,
        )

        response = sns_topic["sqs_client"].receive_message(
            QueueUrl=sns_topic["queue_url"],
            MaxNumberOfMessages=1,
            WaitTimeSeconds=0,
        )
        envelope = json.loads(response["Messages"][0]["Body"])
        notification = json.loads(envelope["Message"])

        assert "timestamp" in notification
        # Verify it contains 'T' separator typical of ISO 8601
        assert "T" in notification["timestamp"]

    def test_notify_has_all_required_fields(self, sns_topic):
        """Notification JSON contains all required fields per ErrorNotification model."""
        notifier = ErrorNotifier(
            topic_arn=sns_topic["topic_arn"],
            sns_client=sns_topic["sns_client"],
        )

        notifier.notify(
            submission_id="sub-003",
            component_name="pacing-evaluator",
            error_type="ValidationError",
            error_message="Invalid input schema",
            retry_count_exhausted=0,
        )

        response = sns_topic["sqs_client"].receive_message(
            QueueUrl=sns_topic["queue_url"],
            MaxNumberOfMessages=1,
            WaitTimeSeconds=0,
        )
        envelope = json.loads(response["Messages"][0]["Body"])
        notification = json.loads(envelope["Message"])

        required_fields = {
            "submission_id",
            "component_name",
            "error_type",
            "error_message",
            "retry_count_exhausted",
            "timestamp",
        }
        assert required_fields.issubset(set(notification.keys()))


class TestErrorNotifierBestEffortIsolation:
    """Tests for best-effort isolation — SNS failures are caught, not propagated."""

    def test_sns_failure_does_not_propagate(self):
        """When SNS publish fails, the error is caught and not raised."""
        with mock_aws():
            sns = boto3.client("sns", region_name="us-east-1")

            # Use a non-existent topic ARN — publish will fail
            notifier = ErrorNotifier(
                topic_arn="arn:aws:sns:us-east-1:123456789012:nonexistent-topic",
                sns_client=sns,
            )

            # This should NOT raise an exception
            notifier.notify(
                submission_id="sub-fail",
                component_name="test-component",
                error_type="TestError",
                error_message="This should not propagate",
                retry_count_exhausted=1,
            )

    def test_sns_failure_is_logged(self, caplog):
        """When SNS publish fails, the failure is logged."""
        with mock_aws():
            sns = boto3.client("sns", region_name="us-east-1")

            notifier = ErrorNotifier(
                topic_arn="arn:aws:sns:us-east-1:123456789012:nonexistent-topic",
                sns_client=sns,
            )

            with caplog.at_level(logging.ERROR, logger="src.services.error_notifier"):
                notifier.notify(
                    submission_id="sub-log-test",
                    component_name="logging-component",
                    error_type="SNSFailure",
                    error_message="Test logging on failure",
                    retry_count_exhausted=2,
                )

            assert "Failed to publish error notification" in caplog.text
            assert "sub-log-test" in caplog.text


class TestErrorNotifierConstruction:
    """Tests for ErrorNotifier construction."""

    def test_accepts_custom_sns_client(self):
        """ErrorNotifier accepts a custom SNS client."""
        with mock_aws():
            sns = boto3.client("sns", region_name="us-east-1")
            notifier = ErrorNotifier(
                topic_arn="arn:aws:sns:us-east-1:123456789012:test-topic",
                sns_client=sns,
            )
            assert notifier._topic_arn == "arn:aws:sns:us-east-1:123456789012:test-topic"

    def test_creates_default_client_if_not_provided(self):
        """ErrorNotifier creates a default boto3 SNS client when none provided."""
        with mock_aws():
            notifier = ErrorNotifier(
                topic_arn="arn:aws:sns:us-east-1:123456789012:test-topic",
            )
            assert notifier._sns_client is not None
