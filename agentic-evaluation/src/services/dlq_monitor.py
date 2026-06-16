"""DLQ Monitor service for threshold-based alert notifications.

Periodically polls the Dead Letter Queue to check the approximate message
count. When the count exceeds a configurable threshold, publishes an alert
notification to an SNS topic.
"""

import json
import logging
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class DLQMonitor:
    """Monitors a Dead Letter Queue and publishes SNS alerts when the
    message count exceeds a configurable threshold.

    Args:
        dlq_url: The URL of the SQS Dead Letter Queue to monitor.
        threshold: The message count threshold that triggers an alert (default 10).
        sns_topic_arn: The ARN of the SNS topic to publish alerts to.
        sqs_client: Optional boto3 SQS client. If not provided, a default
            client will be created via boto3.client("sqs").
        sns_client: Optional boto3 SNS client. If not provided, a default
            client will be created via boto3.client("sns").
    """

    def __init__(
        self,
        dlq_url: str,
        sns_topic_arn: str,
        threshold: int = 10,
        sqs_client=None,
        sns_client=None,
    ):
        self._dlq_url = dlq_url
        self._sns_topic_arn = sns_topic_arn
        self._threshold = threshold

        if sqs_client is not None:
            self._sqs_client = sqs_client
        else:
            import boto3
            self._sqs_client = boto3.client("sqs")

        if sns_client is not None:
            self._sns_client = sns_client
        else:
            import boto3
            self._sns_client = boto3.client("sns")

    def check_threshold(self) -> bool:
        """Check the DLQ message count and publish an SNS alert if it exceeds the threshold.

        Retrieves the ApproximateNumberOfMessages attribute from the DLQ.
        If the count exceeds the configured threshold, publishes a structured
        alert message to the SNS topic.

        Returns:
            True if the threshold was exceeded and an alert was published,
            False otherwise.
        """
        try:
            response = self._sqs_client.get_queue_attributes(
                QueueUrl=self._dlq_url,
                AttributeNames=["ApproximateNumberOfMessages"],
            )

            attributes = response.get("Attributes", {})
            message_count = int(attributes.get("ApproximateNumberOfMessages", "0"))

            logger.debug(
                "DLQ %s has %d messages (threshold: %d)",
                self._dlq_url,
                message_count,
                self._threshold,
            )

            if message_count > self._threshold:
                self._publish_alert(message_count)
                return True

            return False

        except Exception:
            logger.exception(
                "Failed to check DLQ threshold for queue %s",
                self._dlq_url,
            )
            return False

    def _publish_alert(self, current_count: int) -> None:
        """Publish a threshold alert notification to SNS.

        Args:
            current_count: The current approximate message count in the DLQ.
        """
        timestamp = datetime.now(timezone.utc).isoformat()

        alert_message = {
            "alert_type": "DLQ_THRESHOLD_EXCEEDED",
            "queue_url": self._dlq_url,
            "current_message_count": current_count,
            "threshold": self._threshold,
            "timestamp": timestamp,
        }

        try:
            self._sns_client.publish(
                TopicArn=self._sns_topic_arn,
                Message=json.dumps(alert_message),
                Subject=f"DLQ Threshold Alert: {current_count} messages (threshold: {self._threshold})",
            )

            logger.info(
                "Published DLQ threshold alert: queue=%s, count=%d, threshold=%d",
                self._dlq_url,
                current_count,
                self._threshold,
            )
        except Exception:
            logger.exception(
                "Failed to publish DLQ threshold alert to SNS (best-effort, not propagating)"
            )

    def start_monitoring(self, interval_seconds: int = 60) -> None:
        """Periodically check the DLQ threshold in a blocking loop.

        This method runs indefinitely, calling check_threshold() at the
        specified interval. Intended for standalone monitoring use.

        Args:
            interval_seconds: Time in seconds between threshold checks (default 60).
        """
        logger.info(
            "Starting DLQ monitoring: queue=%s, threshold=%d, interval=%ds",
            self._dlq_url,
            self._threshold,
            interval_seconds,
        )

        while True:
            self.check_threshold()
            time.sleep(interval_seconds)
