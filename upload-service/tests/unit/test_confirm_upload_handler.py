"""Unit tests for the confirm upload handler.

Tests cover:
- Happy path: S3 event → submission lookup → SQS message published
- SQS failure after 3 retries → status updated to Failed + SNS notification

Requirements: 5.1, 5.2, 5.3, 5.4
"""

import os
from unittest.mock import MagicMock, patch

import pytest

# Set environment variables before importing the handler module
# so that service constructors can read them.
os.environ.setdefault("DYNAMODB_TABLE_NAME", "test-submissions")
os.environ.setdefault("SQS_QUEUE_URL", "https://sqs.us-east-1.amazonaws.com/123456789012/test-queue")
os.environ.setdefault("SNS_TOPIC_ARN", "arn:aws:sns:us-east-1:123456789012:test-errors")


from src.handlers.confirm_upload import handler  # noqa: E402
from src.models.submission import (  # noqa: E402
    ErrorNotification,
    ErrorType,
    ProcessingStatus,
    SubmissionRecord,
)
from src.models.sqs_message import SqsMessageBody  # noqa: E402


def _build_s3_event(bucket: str, key: str) -> dict:
    """Build a valid S3 PutObject event for testing."""
    return {
        "Records": [{
            "s3": {
                "bucket": {"name": bucket},
                "object": {"key": key},
            }
        }]
    }


def _make_submission(
    submission_id: str = "sub-001",
    user_id: str = "user-abc",
    s3_file_key: str = "uploads/user-abc/sub-001/presentation.mp3",
    original_file_name: str = "presentation.mp3",
    presentation_title: str = "My Talk",
) -> SubmissionRecord:
    """Create a sample SubmissionRecord for testing."""
    return SubmissionRecord(
        submission_id=submission_id,
        user_id=user_id,
        original_file_name=original_file_name,
        presentation_title=presentation_title,
        s3_file_key=s3_file_key,
        content_type="audio/mpeg",
        file_size_bytes=1024000,
        upload_date="2024-06-15T10:30:00Z",
        processing_status=ProcessingStatus.PENDING,
    )


class TestConfirmUploadHandlerHappyPath:
    """Test happy path: S3 event → SQS message published (Req 5.1, 5.2)."""

    @patch("src.handlers.confirm_upload.sns_service")
    @patch("src.handlers.confirm_upload.sqs_service")
    @patch("src.handlers.confirm_upload.dynamo_service")
    def test_s3_event_publishes_sqs_message(
        self, mock_dynamo, mock_sqs, mock_sns
    ):
        """A valid S3 event triggers an SQS message publish."""
        submission = _make_submission()
        mock_dynamo.get_submissions_by_user.return_value = [submission]

        event = _build_s3_event(
            bucket="test-uploads",
            key="uploads/user-abc/sub-001/presentation.mp3",
        )

        handler(event, None)

        # Verify DynamoDB was queried for the user's submissions
        mock_dynamo.get_submissions_by_user.assert_called_once_with("user-abc")

        # Verify SQS message was published with correct data
        mock_sqs.publish_message.assert_called_once()
        call_args = mock_sqs.publish_message.call_args
        message: SqsMessageBody = call_args[0][0] if call_args[0] else call_args[1]["message"]
        assert message.submission_id == "sub-001"
        assert message.user_id == "user-abc"
        assert message.s3_file_key == "uploads/user-abc/sub-001/presentation.mp3"
        assert message.original_file_name == "presentation.mp3"
        assert message.presentation_title == "My Talk"

        # Verify max_retries=3 is passed
        assert call_args[1].get("max_retries") == 3 or (
            len(call_args[0]) > 1 and call_args[0][1] == 3
        ) or call_args.kwargs.get("max_retries") == 3

    @patch("src.handlers.confirm_upload.sns_service")
    @patch("src.handlers.confirm_upload.sqs_service")
    @patch("src.handlers.confirm_upload.dynamo_service")
    def test_sqs_message_contains_required_fields(
        self, mock_dynamo, mock_sqs, mock_sns
    ):
        """SQS message body contains submission_id, user_id, s3_file_key,
        original_file_name, and presentation_title (Req 5.2)."""
        submission = _make_submission(
            submission_id="uuid-123",
            user_id="user-xyz",
            s3_file_key="uploads/user-xyz/uuid-123/talk.mp4",
            original_file_name="talk.mp4",
            presentation_title="Quarterly Review",
        )
        mock_dynamo.get_submissions_by_user.return_value = [submission]

        event = _build_s3_event(
            bucket="test-uploads",
            key="uploads/user-xyz/uuid-123/talk.mp4",
        )

        handler(event, None)

        call_args = mock_sqs.publish_message.call_args
        message = call_args[0][0] if call_args[0] else call_args[1]["message"]
        assert message.submission_id == "uuid-123"
        assert message.user_id == "user-xyz"
        assert message.s3_file_key == "uploads/user-xyz/uuid-123/talk.mp4"
        assert message.original_file_name == "talk.mp4"
        assert message.presentation_title == "Quarterly Review"

    @patch("src.handlers.confirm_upload.sns_service")
    @patch("src.handlers.confirm_upload.sqs_service")
    @patch("src.handlers.confirm_upload.dynamo_service")
    def test_url_encoded_key_is_decoded(self, mock_dynamo, mock_sqs, mock_sns):
        """S3 keys with URL-encoded characters are decoded correctly."""
        submission = _make_submission(
            submission_id="sub-002",
            user_id="user-abc",
            s3_file_key="uploads/user-abc/sub-002/my file.mp3",
            original_file_name="my file.mp3",
        )
        mock_dynamo.get_submissions_by_user.return_value = [submission]

        event = _build_s3_event(
            bucket="test-uploads",
            key="uploads/user-abc/sub-002/my+file.mp3",
        )

        handler(event, None)

        mock_dynamo.get_submissions_by_user.assert_called_once_with("user-abc")
        mock_sqs.publish_message.assert_called_once()

    @patch("src.handlers.confirm_upload.sns_service")
    @patch("src.handlers.confirm_upload.sqs_service")
    @patch("src.handlers.confirm_upload.dynamo_service")
    def test_no_error_notification_on_success(
        self, mock_dynamo, mock_sqs, mock_sns
    ):
        """On successful SQS publish, no SNS notification is sent."""
        submission = _make_submission()
        mock_dynamo.get_submissions_by_user.return_value = [submission]

        event = _build_s3_event(
            bucket="test-uploads",
            key="uploads/user-abc/sub-001/presentation.mp3",
        )

        handler(event, None)

        mock_sns.publish_error_notification.assert_not_called()


class TestConfirmUploadHandlerSqsFailure:
    """Test SQS failure after retries → Failed status + SNS (Req 5.3, 5.4)."""

    @patch("src.handlers.confirm_upload.sns_service")
    @patch("src.handlers.confirm_upload.sqs_service")
    @patch("src.handlers.confirm_upload.dynamo_service")
    def test_sqs_failure_updates_status_to_failed(
        self, mock_dynamo, mock_sqs, mock_sns
    ):
        """When SQS publish fails after retries, status is updated to Failed."""
        submission = _make_submission()
        mock_dynamo.get_submissions_by_user.return_value = [submission]
        mock_sqs.publish_message.side_effect = Exception("SQS unavailable")

        event = _build_s3_event(
            bucket="test-uploads",
            key="uploads/user-abc/sub-001/presentation.mp3",
        )

        handler(event, None)

        mock_dynamo.update_status.assert_called_once_with("sub-001", "Failed")

    @patch("src.handlers.confirm_upload.sns_service")
    @patch("src.handlers.confirm_upload.sqs_service")
    @patch("src.handlers.confirm_upload.dynamo_service")
    def test_sqs_failure_publishes_sns_error_notification(
        self, mock_dynamo, mock_sqs, mock_sns
    ):
        """When SQS publish fails after retries, an SNS error notification is sent."""
        submission = _make_submission()
        mock_dynamo.get_submissions_by_user.return_value = [submission]
        mock_sqs.publish_message.side_effect = Exception("SQS unavailable")

        event = _build_s3_event(
            bucket="test-uploads",
            key="uploads/user-abc/sub-001/presentation.mp3",
        )

        handler(event, None)

        mock_sns.publish_error_notification.assert_called_once()
        notification: ErrorNotification = (
            mock_sns.publish_error_notification.call_args[0][0]
        )
        assert notification.submission_id == "sub-001"
        assert notification.error_type == ErrorType.SQS_PUBLISH_FAILURE
        assert "SQS unavailable" in notification.error_message
        assert notification.service_component == "confirm_upload_handler"
        # Timestamp should be present and non-empty
        assert notification.timestamp

    @patch("src.handlers.confirm_upload.sns_service")
    @patch("src.handlers.confirm_upload.sqs_service")
    @patch("src.handlers.confirm_upload.dynamo_service")
    def test_sqs_failure_notification_has_iso_timestamp(
        self, mock_dynamo, mock_sqs, mock_sns
    ):
        """SNS notification timestamp should be ISO 8601 format."""
        submission = _make_submission()
        mock_dynamo.get_submissions_by_user.return_value = [submission]
        mock_sqs.publish_message.side_effect = Exception("timeout")

        event = _build_s3_event(
            bucket="test-uploads",
            key="uploads/user-abc/sub-001/presentation.mp3",
        )

        handler(event, None)

        notification = mock_sns.publish_error_notification.call_args[0][0]
        # ISO 8601 format check: YYYY-MM-DDTHH:MM:SSZ
        assert "T" in notification.timestamp
        assert notification.timestamp.endswith("Z")


class TestConfirmUploadHandlerEdgeCases:
    """Test edge cases and error handling."""

    @patch("src.handlers.confirm_upload.sns_service")
    @patch("src.handlers.confirm_upload.sqs_service")
    @patch("src.handlers.confirm_upload.dynamo_service")
    def test_invalid_key_format_skipped(self, mock_dynamo, mock_sqs, mock_sns):
        """S3 keys that don't match uploads/{user}/{sub}/{file} are skipped."""
        event = _build_s3_event(
            bucket="test-uploads",
            key="other/path/file.mp3",
        )

        handler(event, None)

        mock_dynamo.get_submissions_by_user.assert_not_called()
        mock_sqs.publish_message.assert_not_called()

    @patch("src.handlers.confirm_upload.sns_service")
    @patch("src.handlers.confirm_upload.sqs_service")
    @patch("src.handlers.confirm_upload.dynamo_service")
    def test_missing_object_key_skipped(self, mock_dynamo, mock_sqs, mock_sns):
        """Records with empty object key are skipped."""
        event = {
            "Records": [{
                "s3": {
                    "bucket": {"name": "test-uploads"},
                    "object": {"key": ""},
                }
            }]
        }

        handler(event, None)

        mock_dynamo.get_submissions_by_user.assert_not_called()
        mock_sqs.publish_message.assert_not_called()

    @patch("src.handlers.confirm_upload.sns_service")
    @patch("src.handlers.confirm_upload.sqs_service")
    @patch("src.handlers.confirm_upload.dynamo_service")
    def test_submission_not_found_skipped(self, mock_dynamo, mock_sqs, mock_sns):
        """If no matching submission is found in DynamoDB, the record is skipped."""
        mock_dynamo.get_submissions_by_user.return_value = []

        event = _build_s3_event(
            bucket="test-uploads",
            key="uploads/user-abc/sub-999/file.mp3",
        )

        handler(event, None)

        mock_dynamo.get_submissions_by_user.assert_called_once_with("user-abc")
        mock_sqs.publish_message.assert_not_called()

    @patch("src.handlers.confirm_upload.sns_service")
    @patch("src.handlers.confirm_upload.sqs_service")
    @patch("src.handlers.confirm_upload.dynamo_service")
    def test_dynamo_query_failure_skipped(self, mock_dynamo, mock_sqs, mock_sns):
        """If DynamoDB query fails, the record is skipped gracefully."""
        mock_dynamo.get_submissions_by_user.side_effect = Exception("DynamoDB timeout")

        event = _build_s3_event(
            bucket="test-uploads",
            key="uploads/user-abc/sub-001/presentation.mp3",
        )

        handler(event, None)

        mock_sqs.publish_message.assert_not_called()

    @patch("src.handlers.confirm_upload.sns_service")
    @patch("src.handlers.confirm_upload.sqs_service")
    @patch("src.handlers.confirm_upload.dynamo_service")
    def test_empty_records_list_does_nothing(self, mock_dynamo, mock_sqs, mock_sns):
        """An event with no records does nothing."""
        event = {"Records": []}

        handler(event, None)

        mock_dynamo.get_submissions_by_user.assert_not_called()
        mock_sqs.publish_message.assert_not_called()
