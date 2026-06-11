"""SNS service for publishing error notifications."""

import logging
import os

import boto3

from src.models.submission import ErrorNotification

logger = logging.getLogger(__name__)


class SnsService:
    """Service for publishing error notifications to SNS (best-effort)."""

    def __init__(self) -> None:
        self._client = boto3.client("sns")
        self._topic_arn = os.environ["SNS_TOPIC_ARN"]

    def publish_error_notification(self, notification: ErrorNotification) -> None:
        """Publish an error notification to the SNS topic.

        This is best-effort: all exceptions are caught and logged
        but never re-raised, so the caller is never impacted by
        notification failures.

        Args:
            notification: The error notification to publish.
        """
        try:
            self._client.publish(
                TopicArn=self._topic_arn,
                Message=notification.model_dump_json(),
                Subject=f"Error: {notification.error_type.value}",
            )
        except Exception:
            logger.exception(
                "Failed to publish error notification to SNS "
                "(submission_id=%s, error_type=%s)",
                notification.submission_id,
                notification.error_type.value,
            )
