"""Unit tests for the publish_handoff Lambda handler."""

import json
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from handlers.publish_handoff import handler, publish_handoff


class TestPublishHandoff:
    """Tests for the publish_handoff function."""

    @patch("handlers.publish_handoff.boto3.client")
    def test_successful_publish_returns_message_id(self, mock_boto_client):
        mock_sqs = MagicMock()
        mock_sqs.send_message.return_value = {"MessageId": "msg-abc-123"}
        mock_boto_client.return_value = mock_sqs

        result = publish_handoff(
            submission_id="sub-001",
            user_id="user-002",
            s3_file_key="uploads/audio.mp3",
            vector_store_location="s3://vectors/sub-001/",
            chunk_count=5,
            presentation_title="My Talk",
            queue_url="https://sqs.us-east-1.amazonaws.com/123456789/handoff.fifo",
        )

        assert result == {"message_id": "msg-abc-123"}

    @patch("handlers.publish_handoff.boto3.client")
    def test_send_message_uses_correct_queue_url(self, mock_boto_client):
        mock_sqs = MagicMock()
        mock_sqs.send_message.return_value = {"MessageId": "msg-123"}
        mock_boto_client.return_value = mock_sqs

        queue_url = "https://sqs.us-east-1.amazonaws.com/123456789/handoff.fifo"
        publish_handoff(
            submission_id="sub-001",
            user_id="user-002",
            s3_file_key="uploads/audio.mp3",
            vector_store_location="s3://vectors/sub-001/",
            chunk_count=3,
            presentation_title="Talk Title",
            queue_url=queue_url,
        )

        call_kwargs = mock_sqs.send_message.call_args[1]
        assert call_kwargs["QueueUrl"] == queue_url

    @patch("handlers.publish_handoff.boto3.client")
    def test_message_group_id_is_submission_id(self, mock_boto_client):
        mock_sqs = MagicMock()
        mock_sqs.send_message.return_value = {"MessageId": "msg-123"}
        mock_boto_client.return_value = mock_sqs

        publish_handoff(
            submission_id="sub-xyz",
            user_id="user-002",
            s3_file_key="uploads/audio.mp3",
            vector_store_location="s3://vectors/sub-xyz/",
            chunk_count=2,
            presentation_title="Presentation",
            queue_url="https://sqs.example.com/queue.fifo",
        )

        call_kwargs = mock_sqs.send_message.call_args[1]
        assert call_kwargs["MessageGroupId"] == "sub-xyz"

    @patch("handlers.publish_handoff.boto3.client")
    def test_message_deduplication_id_format(self, mock_boto_client):
        mock_sqs = MagicMock()
        mock_sqs.send_message.return_value = {"MessageId": "msg-123"}
        mock_boto_client.return_value = mock_sqs

        publish_handoff(
            submission_id="sub-456",
            user_id="user-002",
            s3_file_key="uploads/audio.mp3",
            vector_store_location="s3://vectors/sub-456/",
            chunk_count=1,
            presentation_title="Title",
            queue_url="https://sqs.example.com/queue.fifo",
        )

        call_kwargs = mock_sqs.send_message.call_args[1]
        assert call_kwargs["MessageDeduplicationId"] == "sub-456-handoff"

    @patch("handlers.publish_handoff.boto3.client")
    def test_message_body_is_valid_handoff_json(self, mock_boto_client):
        mock_sqs = MagicMock()
        mock_sqs.send_message.return_value = {"MessageId": "msg-123"}
        mock_boto_client.return_value = mock_sqs

        publish_handoff(
            submission_id="sub-001",
            user_id="user-002",
            s3_file_key="uploads/audio.mp3",
            vector_store_location="s3://vectors/sub-001/",
            chunk_count=5,
            presentation_title="My Talk",
            queue_url="https://sqs.example.com/queue.fifo",
        )

        call_kwargs = mock_sqs.send_message.call_args[1]
        body = json.loads(call_kwargs["MessageBody"])
        assert body["submission_id"] == "sub-001"
        assert body["user_id"] == "user-002"
        assert body["s3_file_key"] == "uploads/audio.mp3"
        assert body["vector_store_location"] == "s3://vectors/sub-001/"
        assert body["chunk_count"] == 5
        assert body["presentation_title"] == "My Talk"

    def test_invalid_chunk_count_raises_validation_error(self):
        with pytest.raises(ValidationError):
            publish_handoff(
                submission_id="sub-001",
                user_id="user-002",
                s3_file_key="uploads/audio.mp3",
                vector_store_location="s3://vectors/sub-001/",
                chunk_count=0,
                presentation_title="My Talk",
                queue_url="https://sqs.example.com/queue.fifo",
            )

    def test_empty_submission_id_raises_validation_error(self):
        with pytest.raises(ValidationError):
            publish_handoff(
                submission_id="",
                user_id="user-002",
                s3_file_key="uploads/audio.mp3",
                vector_store_location="s3://vectors/sub-001/",
                chunk_count=3,
                presentation_title="My Talk",
                queue_url="https://sqs.example.com/queue.fifo",
            )

    @patch("handlers.publish_handoff.boto3.client")
    def test_sqs_failure_propagates_as_client_error(self, mock_boto_client):
        """SQS send_message failure propagates to the caller."""
        from botocore.exceptions import ClientError

        mock_sqs = MagicMock()
        mock_sqs.send_message.side_effect = ClientError(
            error_response={"Error": {"Code": "AWS.SimpleQueueService.NonExistentQueue", "Message": "The specified queue does not exist."}},
            operation_name="SendMessage",
        )
        mock_boto_client.return_value = mock_sqs

        with pytest.raises(ClientError) as exc_info:
            publish_handoff(
                submission_id="sub-fail",
                user_id="user-002",
                s3_file_key="uploads/audio.mp3",
                vector_store_location="s3://vectors/sub-fail/",
                chunk_count=3,
                presentation_title="My Talk",
                queue_url="https://sqs.us-east-1.amazonaws.com/123456789/handoff.fifo",
            )

        assert exc_info.value.response["Error"]["Code"] == "AWS.SimpleQueueService.NonExistentQueue"


class TestHandler:
    """Tests for the Lambda handler wrapper."""

    @patch("handlers.publish_handoff.boto3.client")
    def test_handler_extracts_fields_from_event(self, mock_boto_client):
        mock_sqs = MagicMock()
        mock_sqs.send_message.return_value = {"MessageId": "msg-handler-123"}
        mock_boto_client.return_value = mock_sqs

        event = {
            "submission_id": "sub-handler",
            "user_id": "user-handler",
            "s3_file_key": "uploads/handler.mp3",
            "store_result": {"vector_store_location": "s3://vectors/handler/"},
            "chunks": {"chunk_count": 4},
            "presentation_title": "Handler Talk",
            "queue_url": "https://sqs.example.com/queue.fifo",
        }

        result = handler(event, None)
        assert result == {"message_id": "msg-handler-123"}

    def test_handler_with_missing_field_raises_key_error(self):
        event = {
            "submission_id": "sub-001",
            # Missing other required fields
        }
        with pytest.raises(KeyError):
            handler(event, None)
