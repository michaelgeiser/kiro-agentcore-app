"""SQS service for publishing processing messages with retry logic."""

import os
import time

import boto3

from src.models.sqs_message import SqsMessageBody


class SqsService:
    """Service for publishing messages to the SQS processing queue."""

    def __init__(self) -> None:
        self._client = boto3.client("sqs")
        self._queue_url = os.environ["SQS_QUEUE_URL"]

    def publish_message(self, message: SqsMessageBody, max_retries: int = 3) -> None:
        """Publish a processing message to the queue.

        Retries up to max_retries times with exponential backoff on failure.
        Base delay is 0.1s with a multiplier of 2 (100ms, 200ms, 400ms).

        Args:
            message: The SQS message body to publish.
            max_retries: Maximum number of retry attempts (default: 3).

        Raises:
            Exception: Re-raises the last exception after all retries are exhausted.
        """
        base_delay = 0.1
        multiplier = 2
        last_exception: Exception | None = None

        for attempt in range(max_retries):
            try:
                self._client.send_message(
                    QueueUrl=self._queue_url,
                    MessageBody=message.model_dump_json(),
                )
                return
            except Exception as e:
                last_exception = e
                if attempt < max_retries - 1:
                    delay = base_delay * (multiplier ** attempt)
                    time.sleep(delay)

        raise last_exception  # type: ignore[misc]
