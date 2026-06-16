"""Error Notifier service for publishing error notifications to SNS.

Publishes structured ErrorNotification messages to an SNS topic on a
best-effort basis. SNS publish failures are caught and logged — they
are never propagated to the caller.
"""

import logging
from datetime import datetime, timezone

from models.data_models import ErrorNotification

logger = logging.getLogger(__name__)


class ErrorNotifier:
    """Publishes error notifications to SNS (best-effort).

    Args:
        topic_arn: The ARN of the SNS topic to publish notifications to.
        sns_client: Optional boto3 SNS client. If not provided, a default
            client will be created via boto3.client("sns").
    """

    def __init__(self, topic_arn: str, sns_client=None):
        self._topic_arn = topic_arn
        if sns_client is not None:
            self._sns_client = sns_client
        else:
            import boto3
            self._sns_client = boto3.client("sns")

    def notify(
        self,
        submission_id: str,
        component_name: str,
        error_type: str,
        error_message: str,
        retry_count_exhausted: int,
    ) -> None:
        """Publish an error notification to SNS.

        Constructs an ErrorNotification with all required fields (including
        an auto-generated ISO 8601 timestamp) and publishes it as JSON to
        the configured SNS topic.

        All SNS publish failures are caught and logged — never propagated.

        Args:
            submission_id: The submission that encountered the error.
            component_name: The component/agent that failed.
            error_type: Classification of the error.
            error_message: Human-readable error description.
            retry_count_exhausted: Number of retries attempted before failure.
        """
        try:
            notification = ErrorNotification(
                submission_id=submission_id,
                component_name=component_name,
                error_type=error_type,
                error_message=error_message,
                retry_count_exhausted=retry_count_exhausted,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )

            message_body = notification.model_dump_json()

            self._sns_client.publish(
                TopicArn=self._topic_arn,
                Message=message_body,
                Subject=f"Error: {component_name} - {error_type}",
            )

            logger.info(
                "Published error notification for submission %s: %s - %s",
                submission_id,
                component_name,
                error_type,
            )
        except Exception:
            logger.exception(
                "Failed to publish error notification to SNS for submission %s "
                "(best-effort, not propagating)",
                submission_id,
            )
