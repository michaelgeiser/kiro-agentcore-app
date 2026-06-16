# Feature: agentic-evaluation, Property 10: FIFO ordering preserved
"""Property-based tests for FIFO ordering guarantee.

For any sequence of messages sent to the FIFO queue, the messages are received
and processed in the exact same order they were sent.

Validates: Requirements 8.2
"""

import json
import uuid

import boto3
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.strategies import composite
from moto import mock_aws

from services.sqs_consumer import SQSConsumer


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


@composite
def message_sequence(draw):
    """Generate a random sequence of messages with sequential IDs.

    Each message is a dict with a unique sequential 'sequence_id' field
    (to verify ordering) plus random additional content fields.
    """
    n = draw(st.integers(min_value=2, max_value=15))
    messages = []
    for i in range(n):
        msg = {
            "sequence_id": i,
            "submission_id": draw(st.text(
                alphabet=st.characters(whitelist_categories=("L", "N")),
                min_size=1,
                max_size=20,
            )),
            "payload": draw(st.text(min_size=0, max_size=50)),
        }
        messages.append(msg)
    return messages


# ---------------------------------------------------------------------------
# Fixtures / Helpers
# ---------------------------------------------------------------------------


def _create_fifo_queue(sqs_client, queue_name: str) -> str:
    """Create a FIFO queue and return its URL."""
    response = sqs_client.create_queue(
        QueueName=queue_name,
        Attributes={
            "FifoQueue": "true",
            "ContentBasedDeduplication": "false",
            "VisibilityTimeout": "300",
        },
    )
    return response["QueueUrl"]


def _send_messages(sqs_client, queue_url: str, messages: list[dict]) -> None:
    """Send messages to the FIFO queue in order, using the same MessageGroupId."""
    group_id = "test-group"
    for msg in messages:
        sqs_client.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps(msg),
            MessageGroupId=group_id,
            MessageDeduplicationId=str(uuid.uuid4()),
        )


# ---------------------------------------------------------------------------
# Property 10: FIFO ordering preserved
# ---------------------------------------------------------------------------


@pytest.mark.property
@settings(max_examples=50, deadline=10000)
@given(messages=message_sequence())
def test_fifo_ordering_preserved(messages: list[dict]) -> None:
    """For any sequence of N messages sent to a FIFO queue using the same
    MessageGroupId, receiving them one at a time via SQSConsumer.receive_message()
    SHALL return them in the exact same order they were sent.

    The Session Supervisor processes messages in the order received from the
    FIFO queue (message processed at position i was received at position i).

    **Validates: Requirements 8.2**
    """
    with mock_aws():
        # Set up mocked SQS FIFO queue
        sqs_client = boto3.client("sqs", region_name="us-east-1")
        queue_url = _create_fifo_queue(sqs_client, "test-handoff-queue.fifo")
        dlq_url = _create_fifo_queue(sqs_client, "test-dlq.fifo")

        # Send all messages to the FIFO queue in order
        _send_messages(sqs_client, queue_url, messages)

        # Create consumer (uses the same client so it talks to moto)
        consumer = SQSConsumer(
            queue_url=queue_url,
            dlq_url=dlq_url,
            sqs_client=sqs_client,
        )

        # Receive messages one at a time and verify ordering
        received_ids = []
        for _ in range(len(messages)):
            result = consumer.receive_message()
            assert result is not None, "Expected a message but got None"
            received_ids.append(result["sequence_id"])
            # Acknowledge to unblock next message in the group
            consumer.acknowledge(result["_receipt_handle"])

        # Assert: messages received in exact same order as sent
        expected_ids = [msg["sequence_id"] for msg in messages]
        assert received_ids == expected_ids, (
            f"FIFO ordering violated: sent {expected_ids}, "
            f"received {received_ids}"
        )
