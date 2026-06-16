"""Unit tests for the DLQMonitor service.

Tests DLQ threshold checking, SNS alert publishing when the threshold
is exceeded, and proper handling of failures.

Requirements: 11.4
"""

import json
import logging

import boto3
import pytest
from moto import mock_aws

from services.dlq_monitor import DLQMonitor


@pytest.fixture
def aws_resources():
    """Create mocked SQS DLQ and SNS topic for testing."""
    with mock_aws():
        sqs = boto3.client("sqs", region_name="us-east-1")
        sns = boto3.client("sns", region_name="us-east-1")

        # Create DLQ
        dlq_response = sqs.create_queue(QueueName="test-dlq")
        dlq_url = dlq_response["QueueUrl"]

        # Create SNS topic
        topic_response = sns.create_topic(Name="test-alerts")
        topic_arn = topic_response["TopicArn"]

        # Create a sink queue subscribed to SNS to capture alerts
        sink_response = sqs.create_queue(QueueName="test-alert-sink")
        sink_url = sink_response["QueueUrl"]
        sink_attrs = sqs.get_queue_attributes(
            QueueUrl=sink_url, AttributeNames=["QueueArn"]
        )
        sink_arn = sink_attrs["Attributes"]["QueueArn"]

        sns.subscribe(
            TopicArn=topic_arn,
            Protocol="sqs",
            Endpoint=sink_arn,
        )

        yield {
            "sqs_client": sqs,
            "sns_client": sns,
            "dlq_url": dlq_url,
            "topic_arn": topic_arn,
            "sink_url": sink_url,
        }


class TestDLQMonitorCheckThreshold:
    """Tests for DLQMonitor.check_threshold() method."""

    def test_no_alert_when_below_threshold(self, aws_resources):
        """check_threshold() returns False when message count is below threshold."""
        monitor = DLQMonitor(
            dlq_url=aws_resources["dlq_url"],
            sns_topic_arn=aws_resources["topic_arn"],
            threshold=10,
            sqs_client=aws_resources["sqs_client"],
            sns_client=aws_resources["sns_client"],
        )

        result = monitor.check_threshold()

        assert result is False

    def test_no_alert_when_at_threshold(self, aws_resources):
        """check_threshold() returns False when message count equals threshold."""
        sqs = aws_resources["sqs_client"]
        dlq_url = aws_resources["dlq_url"]

        # Send exactly threshold number of messages
        for i in range(5):
            sqs.send_message(QueueUrl=dlq_url, MessageBody=f"msg-{i}")

        monitor = DLQMonitor(
            dlq_url=dlq_url,
            sns_topic_arn=aws_resources["topic_arn"],
            threshold=5,
            sqs_client=sqs,
            sns_client=aws_resources["sns_client"],
        )

        result = monitor.check_threshold()

        assert result is False

    def test_alert_when_above_threshold(self, aws_resources):
        """check_threshold() returns True and publishes alert when count exceeds threshold."""
        sqs = aws_resources["sqs_client"]
        dlq_url = aws_resources["dlq_url"]

        # Send messages exceeding the threshold
        for i in range(6):
            sqs.send_message(QueueUrl=dlq_url, MessageBody=f"msg-{i}")

        monitor = DLQMonitor(
            dlq_url=dlq_url,
            sns_topic_arn=aws_resources["topic_arn"],
            threshold=5,
            sqs_client=sqs,
            sns_client=aws_resources["sns_client"],
        )

        result = monitor.check_threshold()

        assert result is True

    def test_alert_message_contains_required_fields(self, aws_resources):
        """Published alert contains queue_url, current_message_count, threshold, and timestamp."""
        sqs = aws_resources["sqs_client"]
        dlq_url = aws_resources["dlq_url"]

        # Send messages exceeding the threshold
        for i in range(11):
            sqs.send_message(QueueUrl=dlq_url, MessageBody=f"msg-{i}")

        monitor = DLQMonitor(
            dlq_url=dlq_url,
            sns_topic_arn=aws_resources["topic_arn"],
            threshold=10,
            sqs_client=sqs,
            sns_client=aws_resources["sns_client"],
        )

        monitor.check_threshold()

        # Read alert from the sink queue
        response = sqs.receive_message(
            QueueUrl=aws_resources["sink_url"],
            MaxNumberOfMessages=1,
            WaitTimeSeconds=0,
        )
        messages = response.get("Messages", [])
        assert len(messages) == 1

        envelope = json.loads(messages[0]["Body"])
        alert = json.loads(envelope["Message"])

        assert alert["queue_url"] == dlq_url
        assert alert["current_message_count"] == 11
        assert alert["threshold"] == 10
        assert "timestamp" in alert
        assert "T" in alert["timestamp"]  # ISO 8601 format
        assert alert["alert_type"] == "DLQ_THRESHOLD_EXCEEDED"

    def test_default_threshold_is_10(self, aws_resources):
        """DLQMonitor defaults to a threshold of 10."""
        monitor = DLQMonitor(
            dlq_url=aws_resources["dlq_url"],
            sns_topic_arn=aws_resources["topic_arn"],
            sqs_client=aws_resources["sqs_client"],
            sns_client=aws_resources["sns_client"],
        )

        assert monitor._threshold == 10


class TestDLQMonitorErrorHandling:
    """Tests for error handling in DLQMonitor."""

    def test_sqs_failure_returns_false(self):
        """check_threshold() returns False when SQS call fails."""
        with mock_aws():
            sns = boto3.client("sns", region_name="us-east-1")
            sqs = boto3.client("sqs", region_name="us-east-1")

            # Use a non-existent queue URL
            monitor = DLQMonitor(
                dlq_url="https://sqs.us-east-1.amazonaws.com/123456789012/nonexistent",
                sns_topic_arn="arn:aws:sns:us-east-1:123456789012:test",
                sqs_client=sqs,
                sns_client=sns,
            )

            result = monitor.check_threshold()

            assert result is False

    def test_sqs_failure_is_logged(self, caplog):
        """check_threshold() logs the error when SQS call fails."""
        with mock_aws():
            sns = boto3.client("sns", region_name="us-east-1")
            sqs = boto3.client("sqs", region_name="us-east-1")

            monitor = DLQMonitor(
                dlq_url="https://sqs.us-east-1.amazonaws.com/123456789012/nonexistent",
                sns_topic_arn="arn:aws:sns:us-east-1:123456789012:test",
                sqs_client=sqs,
                sns_client=sns,
            )

            with caplog.at_level(logging.ERROR):
                monitor.check_threshold()

            assert "Failed to check DLQ threshold" in caplog.text

    def test_sns_publish_failure_does_not_propagate(self, aws_resources):
        """When SNS publish fails, the error is caught and logged, not propagated."""
        sqs = aws_resources["sqs_client"]
        dlq_url = aws_resources["dlq_url"]

        # Send messages exceeding the threshold
        for i in range(11):
            sqs.send_message(QueueUrl=dlq_url, MessageBody=f"msg-{i}")

        # Use a broken SNS client (non-existent topic)
        with mock_aws():
            broken_sns = boto3.client("sns", region_name="us-east-1")

        monitor = DLQMonitor(
            dlq_url=dlq_url,
            sns_topic_arn="arn:aws:sns:us-east-1:123456789012:nonexistent",
            threshold=10,
            sqs_client=sqs,
            sns_client=broken_sns,
        )

        # Should not raise
        result = monitor.check_threshold()
        # The SQS check succeeded, found messages above threshold,
        # but SNS publish failed - still returns False from outer exception
        # Actually the _publish_alert catches internally, so check_threshold returns True
        # because the threshold was exceeded even if alert failed
        assert result is True


class TestDLQMonitorConstruction:
    """Tests for DLQMonitor construction."""

    def test_accepts_custom_clients(self):
        """DLQMonitor accepts custom SQS and SNS clients."""
        with mock_aws():
            sqs = boto3.client("sqs", region_name="us-east-1")
            sns = boto3.client("sns", region_name="us-east-1")

            monitor = DLQMonitor(
                dlq_url="https://sqs.us-east-1.amazonaws.com/123456789012/test-dlq",
                sns_topic_arn="arn:aws:sns:us-east-1:123456789012:test-topic",
                threshold=20,
                sqs_client=sqs,
                sns_client=sns,
            )

            assert monitor._dlq_url == "https://sqs.us-east-1.amazonaws.com/123456789012/test-dlq"
            assert monitor._sns_topic_arn == "arn:aws:sns:us-east-1:123456789012:test-topic"
            assert monitor._threshold == 20

    def test_creates_default_clients_if_not_provided(self):
        """DLQMonitor creates default boto3 clients when none provided."""
        with mock_aws():
            monitor = DLQMonitor(
                dlq_url="https://sqs.us-east-1.amazonaws.com/123456789012/test-dlq",
                sns_topic_arn="arn:aws:sns:us-east-1:123456789012:test-topic",
            )

            assert monitor._sqs_client is not None
            assert monitor._sns_client is not None
