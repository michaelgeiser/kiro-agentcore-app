"""Unit tests for the SQS Consumer service.

Tests message reception with long-polling, acknowledgment (deletion),
DLQ routing with error metadata, empty queue handling, and JSON parse
failure behavior.

Requirements: 8.1, 8.3
"""

import json

import boto3
import pytest
from moto import mock_aws

from services.sqs_consumer import SQSConsumer


@pytest.fixture
def sqs_queues():
    """Create mocked SQS FIFO queues for testing."""
    with mock_aws():
        sqs = boto3.client("sqs", region_name="us-east-1")

        # Create the main FIFO queue
        main_queue = sqs.create_queue(
            QueueName="test-handoff.fifo",
            Attributes={
                "FifoQueue": "true",
                "ContentBasedDeduplication": "true",
            },
        )
        main_queue_url = main_queue["QueueUrl"]

        # Create the DLQ (also FIFO)
        dlq = sqs.create_queue(
            QueueName="test-handoff-dlq.fifo",
            Attributes={
                "FifoQueue": "true",
                "ContentBasedDeduplication": "false",
            },
        )
        dlq_url = dlq["QueueUrl"]

        yield {
            "client": sqs,
            "main_queue_url": main_queue_url,
            "dlq_url": dlq_url,
        }


class TestSQSConsumerReceiveMessage:
    """Tests for SQSConsumer.receive_message() method."""

    def test_receive_valid_json_message(self, sqs_queues):
        """Receiving a message parses JSON body and attaches receipt handle."""
        client = sqs_queues["client"]
        queue_url = sqs_queues["main_queue_url"]
        dlq_url = sqs_queues["dlq_url"]

        # Send a test message
        message_body = json.dumps({
            "submission_id": "sub-001",
            "user_id": "user-abc",
            "s3_file_key": "uploads/file.pptx",
            "vector_store_location": "vs-bucket/embeddings",
            "chunk_count": 5,
            "presentation_title": "My Presentation",
        })
        client.send_message(
            QueueUrl=queue_url,
            MessageBody=message_body,
            MessageGroupId="test-group",
        )

        consumer = SQSConsumer(
            queue_url=queue_url,
            dlq_url=dlq_url,
            sqs_client=client,
        )
        result = consumer.receive_message()

        assert result is not None
        assert result["submission_id"] == "sub-001"
        assert result["user_id"] == "user-abc"
        assert result["chunk_count"] == 5
        assert "_receipt_handle" in result
        assert len(result["_receipt_handle"]) > 0

    def test_no_messages_returns_none(self, sqs_queues):
        """Empty queue returns None when no messages available."""
        client = sqs_queues["client"]
        queue_url = sqs_queues["main_queue_url"]
        dlq_url = sqs_queues["dlq_url"]

        consumer = SQSConsumer(
            queue_url=queue_url,
            dlq_url=dlq_url,
            sqs_client=client,
        )
        # Override to short-poll to avoid waiting 20 seconds
        # We directly call with a short WaitTimeSeconds by monkey-patching
        # But moto returns immediately anyway when queue is empty
        result = consumer.receive_message()

        assert result is None

    def test_json_parse_failure_returns_parse_error(self, sqs_queues):
        """Non-JSON message body returns dict with _parse_error key."""
        client = sqs_queues["client"]
        queue_url = sqs_queues["main_queue_url"]
        dlq_url = sqs_queues["dlq_url"]

        # Send an invalid JSON message
        client.send_message(
            QueueUrl=queue_url,
            MessageBody="this is not valid json {{{",
            MessageGroupId="test-group",
        )

        consumer = SQSConsumer(
            queue_url=queue_url,
            dlq_url=dlq_url,
            sqs_client=client,
        )
        result = consumer.receive_message()

        assert result is not None
        assert "_parse_error" in result
        assert "_raw_body" in result
        assert result["_raw_body"] == "this is not valid json {{{"
        assert "_receipt_handle" in result

    def test_receive_attaches_fifo_metadata(self, sqs_queues):
        """Received message includes FIFO metadata (MessageGroupId)."""
        client = sqs_queues["client"]
        queue_url = sqs_queues["main_queue_url"]
        dlq_url = sqs_queues["dlq_url"]

        client.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps({"key": "value"}),
            MessageGroupId="fifo-group-42",
        )

        consumer = SQSConsumer(
            queue_url=queue_url,
            dlq_url=dlq_url,
            sqs_client=client,
        )
        result = consumer.receive_message()

        assert result is not None
        assert result["_message_group_id"] == "fifo-group-42"


class TestSQSConsumerAcknowledge:
    """Tests for SQSConsumer.acknowledge() method."""

    def test_acknowledge_deletes_message(self, sqs_queues):
        """Acknowledging a message removes it from the queue."""
        client = sqs_queues["client"]
        queue_url = sqs_queues["main_queue_url"]
        dlq_url = sqs_queues["dlq_url"]

        # Send a message
        client.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps({"data": "test"}),
            MessageGroupId="group-1",
        )

        consumer = SQSConsumer(
            queue_url=queue_url,
            dlq_url=dlq_url,
            sqs_client=client,
        )

        # Receive the message
        result = consumer.receive_message()
        assert result is not None
        receipt_handle = result["_receipt_handle"]

        # Acknowledge it
        consumer.acknowledge(receipt_handle)

        # Verify the queue is now empty
        response = client.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=0,
        )
        assert response.get("Messages", []) == []

    def test_acknowledge_invalid_receipt_handle_raises(self, sqs_queues):
        """Acknowledging with invalid receipt handle raises an exception."""
        client = sqs_queues["client"]
        queue_url = sqs_queues["main_queue_url"]
        dlq_url = sqs_queues["dlq_url"]

        consumer = SQSConsumer(
            queue_url=queue_url,
            dlq_url=dlq_url,
            sqs_client=client,
        )

        with pytest.raises(Exception):
            consumer.acknowledge("invalid-receipt-handle")


class TestSQSConsumerSendToDLQ:
    """Tests for SQSConsumer.send_to_dlq() method."""

    def test_send_to_dlq_routes_message(self, sqs_queues):
        """Failed messages are routed to the DLQ."""
        client = sqs_queues["client"]
        queue_url = sqs_queues["main_queue_url"]
        dlq_url = sqs_queues["dlq_url"]

        consumer = SQSConsumer(
            queue_url=queue_url,
            dlq_url=dlq_url,
            sqs_client=client,
        )

        original_body = json.dumps({"bad_field": "missing_required"})
        consumer.send_to_dlq(original_body, "Validation failed: missing submission_id")

        # Verify message is in the DLQ
        response = client.receive_message(
            QueueUrl=dlq_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=0,
            MessageAttributeNames=["All"],
        )
        messages = response.get("Messages", [])
        assert len(messages) == 1
        assert messages[0]["Body"] == original_body

    def test_send_to_dlq_includes_error_metadata(self, sqs_queues):
        """DLQ message includes ErrorReason as a message attribute."""
        client = sqs_queues["client"]
        queue_url = sqs_queues["main_queue_url"]
        dlq_url = sqs_queues["dlq_url"]

        consumer = SQSConsumer(
            queue_url=queue_url,
            dlq_url=dlq_url,
            sqs_client=client,
        )

        error_reason = "JSON parse error: Expecting value at line 1"
        consumer.send_to_dlq("corrupted body", error_reason)

        response = client.receive_message(
            QueueUrl=dlq_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=0,
            MessageAttributeNames=["All"],
        )
        messages = response.get("Messages", [])
        assert len(messages) == 1

        msg_attrs = messages[0].get("MessageAttributes", {})
        assert "ErrorReason" in msg_attrs
        assert msg_attrs["ErrorReason"]["StringValue"] == error_reason

    def test_send_to_dlq_uses_fifo_group_id(self, sqs_queues):
        """DLQ message uses the 'dlq-failed-messages' MessageGroupId."""
        client = sqs_queues["client"]
        queue_url = sqs_queues["main_queue_url"]
        dlq_url = sqs_queues["dlq_url"]

        consumer = SQSConsumer(
            queue_url=queue_url,
            dlq_url=dlq_url,
            sqs_client=client,
        )

        consumer.send_to_dlq("body", "some error")

        response = client.receive_message(
            QueueUrl=dlq_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=0,
            AttributeNames=["All"],
        )
        messages = response.get("Messages", [])
        assert len(messages) == 1
        # FIFO queues track MessageGroupId in attributes
        attrs = messages[0].get("Attributes", {})
        assert attrs.get("MessageGroupId") == "dlq-failed-messages"


class TestSQSConsumerProperties:
    """Tests for SQSConsumer property accessors."""

    def test_queue_url_property(self, sqs_queues):
        """queue_url property returns the configured queue URL."""
        consumer = SQSConsumer(
            queue_url=sqs_queues["main_queue_url"],
            dlq_url=sqs_queues["dlq_url"],
            sqs_client=sqs_queues["client"],
        )
        assert consumer.queue_url == sqs_queues["main_queue_url"]

    def test_dlq_url_property(self, sqs_queues):
        """dlq_url property returns the configured DLQ URL."""
        consumer = SQSConsumer(
            queue_url=sqs_queues["main_queue_url"],
            dlq_url=sqs_queues["dlq_url"],
            sqs_client=sqs_queues["client"],
        )
        assert consumer.dlq_url == sqs_queues["dlq_url"]
