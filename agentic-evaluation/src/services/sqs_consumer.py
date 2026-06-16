"""SQS FIFO queue consumer for the Agentic Evaluation module.

Handles message consumption with long-polling, acknowledgment (deletion),
and dead-letter queue routing for failed messages.
"""

import json
import logging
import uuid
from typing import Any

import boto3

logger = logging.getLogger(__name__)


class SQSConsumer:
    """Consumes messages from the SQS FIFO handoff queue.

    Provides long-polling message reception, message acknowledgment via
    deletion, and DLQ routing for messages that fail validation or processing.

    Args:
        queue_url: The URL of the SQS FIFO queue to consume from.
        dlq_url: The URL of the dead-letter queue for failed messages.
        sqs_client: Optional pre-configured boto3 SQS client. If not provided,
            a default client will be created.
    """

    def __init__(
        self,
        queue_url: str,
        dlq_url: str,
        sqs_client: Any | None = None,
    ) -> None:
        self._queue_url = queue_url
        self._dlq_url = dlq_url
        self._client = sqs_client or boto3.client("sqs")

    @property
    def queue_url(self) -> str:
        """The URL of the source FIFO queue."""
        return self._queue_url

    @property
    def dlq_url(self) -> str:
        """The URL of the dead-letter queue."""
        return self._dlq_url

    def receive_message(self) -> dict[str, Any] | None:
        """Long-poll for the next message from the FIFO queue.

        Uses WaitTimeSeconds=20 for efficient long-polling. Returns at most
        one message per call to maintain FIFO ordering guarantees.

        FIFO Ordering Guarantee:
            MaxNumberOfMessages=1 ensures sequential consumption. Within a
            MessageGroupId, SQS FIFO delivers messages in the order they were
            sent. By receiving only one message at a time and processing it
            before polling again, we guarantee that messages are handled in
            strict FIFO order. The queue's visibility timeout (configured at
            the infrastructure level, default 5 minutes) ensures that if
            processing takes longer than expected without acknowledgment, the
            message becomes visible again for redelivery rather than being
            lost.

        Returns:
            A dictionary containing the parsed message body with an additional
            '_receipt_handle' key for later acknowledgment, or None if no
            message was available within the polling window.
        """
        logger.debug(
            "Polling for messages from queue: %s", self._queue_url
        )

        try:
            response = self._client.receive_message(
                QueueUrl=self._queue_url,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=20,
                AttributeNames=["All"],
                MessageAttributeNames=["All"],
            )
        except Exception:
            logger.exception("Failed to receive message from SQS queue")
            raise

        messages = response.get("Messages", [])
        if not messages:
            logger.debug("No messages received during polling window")
            return None

        message = messages[0]
        receipt_handle = message["ReceiptHandle"]
        body_raw = message.get("Body", "")

        # Extract FIFO-specific attributes for logging/traceability
        attributes = message.get("Attributes", {})
        message_group_id = attributes.get("MessageGroupId")
        sequence_number = attributes.get("SequenceNumber")

        logger.info(
            "Received message from FIFO queue "
            "(MessageGroupId=%s, SequenceNumber=%s)",
            message_group_id,
            sequence_number,
        )

        try:
            parsed_body = json.loads(body_raw)
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(
                "Failed to parse message body as JSON: %s", e
            )
            # Return raw body wrapped in a dict so caller can handle
            # the validation failure and route to DLQ
            parsed_body = {"_raw_body": body_raw, "_parse_error": str(e)}

        # Attach receipt handle and FIFO metadata for downstream use
        parsed_body["_receipt_handle"] = receipt_handle
        if message_group_id:
            parsed_body["_message_group_id"] = message_group_id
        if sequence_number:
            parsed_body["_sequence_number"] = sequence_number

        return parsed_body

    def acknowledge(self, receipt_handle: str) -> None:
        """Delete a message from the queue after successful processing initiation.

        In the FIFO ordering contract, acknowledgment (deletion) signals that
        the consumer has taken responsibility for this message. For FIFO queues,
        once a message in a MessageGroupId is in-flight (received but not yet
        deleted or visibility-timed-out), no other messages in the same group
        are delivered. Deleting the message unblocks delivery of subsequent
        messages in the group.

        Args:
            receipt_handle: The receipt handle of the message to delete,
                obtained from the '_receipt_handle' field of receive_message().

        Raises:
            Exception: If the SQS delete operation fails.
        """
        logger.info("Acknowledging message (deleting from queue)")

        try:
            self._client.delete_message(
                QueueUrl=self._queue_url,
                ReceiptHandle=receipt_handle,
            )
        except Exception:
            logger.exception(
                "Failed to acknowledge (delete) message from SQS queue"
            )
            raise

        logger.debug("Message acknowledged successfully")

    def send_to_dlq(self, message_body: str, error_reason: str) -> None:
        """Route a failed message to the dead-letter queue.

        Sends the original message body to the DLQ with error metadata
        attached as message attributes. Uses a deduplication ID based on
        a UUID to ensure uniqueness in the FIFO DLQ.

        Args:
            message_body: The original message body (as a string) to route.
            error_reason: A description of why the message failed processing.

        Raises:
            Exception: If the SQS send operation fails.
        """
        logger.warning(
            "Routing message to DLQ. Reason: %s", error_reason
        )

        try:
            self._client.send_message(
                QueueUrl=self._dlq_url,
                MessageBody=message_body,
                MessageGroupId="dlq-failed-messages",
                MessageDeduplicationId=str(uuid.uuid4()),
                MessageAttributes={
                    "ErrorReason": {
                        "DataType": "String",
                        "StringValue": error_reason,
                    },
                },
            )
        except Exception:
            logger.exception("Failed to send message to DLQ")
            raise

        logger.info("Message routed to DLQ successfully")
