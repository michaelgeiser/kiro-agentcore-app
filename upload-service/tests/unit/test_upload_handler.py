"""Unit tests for POST /submissions upload handler.

Tests cover:
- Happy path: valid metadata → presigned URL + DynamoDB record → 201 response with CORS headers
- Invalid file type → 400 response with INVALID_FILE_TYPE code
- File too large → 413 response with FILE_TOO_LARGE code
- Missing title → 400 response with MISSING_REQUIRED_FIELD code
- DynamoDB failure → SNS notification → 500 response
- Presigned URL generation failure → 500 response

Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 3.5, 4.4, 4.5, 6.1, 6.2
"""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

# Set environment variables before importing handler (services read them at import time)
os.environ.setdefault("S3_BUCKET_NAME", "test-bucket")
os.environ.setdefault("DYNAMODB_TABLE_NAME", "test-table")
os.environ.setdefault("SQS_QUEUE_URL", "https://sqs.us-east-1.amazonaws.com/123456789/test-queue")
os.environ.setdefault("SNS_TOPIC_ARN", "arn:aws:sns:us-east-1:123456789:test-topic")

from src.types import CORS_HEADERS


def _build_event(body: dict, user_id: str = "user-123") -> dict:
    """Build a valid HTTP API v2 event with JWT claims for testing."""
    return {
        "requestContext": {
            "authorizer": {
                "jwt": {"claims": {"sub": user_id}}
            }
        },
        "body": json.dumps(body),
    }


def _valid_body() -> dict:
    """Return a valid request body for upload."""
    return {
        "title": "Quarterly Business Review",
        "description": "Q4 presentation recording",
        "fileName": "presentation.mp3",
        "contentType": "audio/mpeg",
        "fileSizeBytes": 15728640,
    }


class TestUploadHandlerHappyPath:
    """Tests for successful upload flow (Requirement 6.1)."""

    @patch("src.handlers.upload.sns_service")
    @patch("src.handlers.upload.dynamo_service")
    @patch("src.handlers.upload.s3_service")
    def test_valid_metadata_returns_201_with_presigned_url(
        self, mock_s3, mock_dynamo, mock_sns
    ):
        """Valid metadata returns 201 with submissionId, presignedUrl, and status."""
        mock_s3.generate_presigned_upload_url.return_value = "https://s3.amazonaws.com/test-bucket/uploads/user-123/abc/presentation.mp3?signature=xyz"

        from src.handlers.upload import handler

        event = _build_event(_valid_body())
        response = handler(event, None)

        assert response["statusCode"] == 201
        body = json.loads(response["body"])
        assert "submissionId" in body
        assert "presignedUrl" in body
        assert body["status"] == "Pending"
        assert body["presignedUrl"] == "https://s3.amazonaws.com/test-bucket/uploads/user-123/abc/presentation.mp3?signature=xyz"

    @patch("src.handlers.upload.sns_service")
    @patch("src.handlers.upload.dynamo_service")
    @patch("src.handlers.upload.s3_service")
    def test_response_includes_cors_headers(self, mock_s3, mock_dynamo, mock_sns):
        """Successful response includes all required CORS headers."""
        mock_s3.generate_presigned_upload_url.return_value = "https://s3.example.com/presigned"

        from src.handlers.upload import handler

        event = _build_event(_valid_body())
        response = handler(event, None)

        assert response["statusCode"] == 201
        for key, value in CORS_HEADERS.items():
            assert response["headers"][key] == value
        assert response["headers"]["Content-Type"] == "application/json"

    @patch("src.handlers.upload.sns_service")
    @patch("src.handlers.upload.dynamo_service")
    @patch("src.handlers.upload.s3_service")
    def test_dynamo_service_called_with_submission_record(
        self, mock_s3, mock_dynamo, mock_sns
    ):
        """DynamoDB service is called to persist the submission record."""
        mock_s3.generate_presigned_upload_url.return_value = "https://s3.example.com/presigned"

        from src.handlers.upload import handler

        event = _build_event(_valid_body())
        handler(event, None)

        mock_dynamo.create_submission.assert_called_once()
        record = mock_dynamo.create_submission.call_args[0][0]
        assert record.user_id == "user-123"
        assert record.presentation_title == "Quarterly Business Review"
        assert record.original_file_name == "presentation.mp3"
        assert record.content_type == "audio/mpeg"
        assert record.file_size_bytes == 15728640
        assert record.processing_status.value == "Pending"

    @patch("src.handlers.upload.sns_service")
    @patch("src.handlers.upload.dynamo_service")
    @patch("src.handlers.upload.s3_service")
    def test_s3_presigned_url_called_with_correct_params(
        self, mock_s3, mock_dynamo, mock_sns
    ):
        """S3 service is called to generate presigned URL with correct file key and content type."""
        mock_s3.generate_presigned_upload_url.return_value = "https://s3.example.com/presigned"

        from src.handlers.upload import handler

        event = _build_event(_valid_body())
        handler(event, None)

        mock_s3.generate_presigned_upload_url.assert_called_once()
        call_args = mock_s3.generate_presigned_upload_url.call_args
        file_key = call_args[0][0]
        content_type = call_args[0][1]
        # File key follows naming convention: uploads/{user_id}/{submission_id}/{filename}
        assert file_key.startswith("uploads/user-123/")
        assert file_key.endswith("/presentation.mp3")
        assert content_type == "audio/mpeg"


class TestUploadHandlerInvalidFileType:
    """Tests for invalid file type rejection (Requirements 1.3, 1.4)."""

    @patch("src.handlers.upload.sns_service")
    @patch("src.handlers.upload.dynamo_service")
    @patch("src.handlers.upload.s3_service")
    def test_invalid_content_type_returns_400(self, mock_s3, mock_dynamo, mock_sns):
        """Unsupported file type returns 400 with INVALID_FILE_TYPE error code."""
        from src.handlers.upload import handler

        body = _valid_body()
        body["contentType"] = "application/pdf"
        event = _build_event(body)
        response = handler(event, None)

        assert response["statusCode"] == 400
        response_body = json.loads(response["body"])
        assert response_body["error"]["code"] == "INVALID_FILE_TYPE"
        assert "correlation_id" in response_body["error"]

    @patch("src.handlers.upload.sns_service")
    @patch("src.handlers.upload.dynamo_service")
    @patch("src.handlers.upload.s3_service")
    def test_invalid_file_type_does_not_call_s3(self, mock_s3, mock_dynamo, mock_sns):
        """Invalid file type should not attempt presigned URL generation."""
        from src.handlers.upload import handler

        body = _valid_body()
        body["contentType"] = "text/plain"
        event = _build_event(body)
        handler(event, None)

        mock_s3.generate_presigned_upload_url.assert_not_called()
        mock_dynamo.create_submission.assert_not_called()


class TestUploadHandlerFileTooLarge:
    """Tests for file size limit enforcement (Requirement 1.5)."""

    @patch("src.handlers.upload.sns_service")
    @patch("src.handlers.upload.dynamo_service")
    @patch("src.handlers.upload.s3_service")
    def test_file_exceeding_500mb_returns_413(self, mock_s3, mock_dynamo, mock_sns):
        """File exceeding 500 MB returns 413 with FILE_TOO_LARGE error code."""
        from src.handlers.upload import handler

        body = _valid_body()
        body["fileSizeBytes"] = 500 * 1024 * 1024 + 1  # 500 MB + 1 byte
        event = _build_event(body)
        response = handler(event, None)

        assert response["statusCode"] == 413
        response_body = json.loads(response["body"])
        assert response_body["error"]["code"] == "FILE_TOO_LARGE"
        assert "correlation_id" in response_body["error"]

    @patch("src.handlers.upload.sns_service")
    @patch("src.handlers.upload.dynamo_service")
    @patch("src.handlers.upload.s3_service")
    def test_file_exactly_500mb_is_accepted(self, mock_s3, mock_dynamo, mock_sns):
        """File at exactly 500 MB boundary should be accepted."""
        mock_s3.generate_presigned_upload_url.return_value = "https://s3.example.com/presigned"

        from src.handlers.upload import handler

        body = _valid_body()
        body["fileSizeBytes"] = 500 * 1024 * 1024  # Exactly 500 MB
        event = _build_event(body)
        response = handler(event, None)

        assert response["statusCode"] == 201


class TestUploadHandlerMissingTitle:
    """Tests for missing required metadata fields (Requirements 1.2, 1.6)."""

    @patch("src.handlers.upload.sns_service")
    @patch("src.handlers.upload.dynamo_service")
    @patch("src.handlers.upload.s3_service")
    def test_missing_title_returns_400(self, mock_s3, mock_dynamo, mock_sns):
        """Missing presentation title returns 400 with MISSING_REQUIRED_FIELD code."""
        from src.handlers.upload import handler

        body = _valid_body()
        del body["title"]
        event = _build_event(body)
        response = handler(event, None)

        assert response["statusCode"] == 400
        response_body = json.loads(response["body"])
        assert response_body["error"]["code"] == "MISSING_REQUIRED_FIELD"
        assert "correlation_id" in response_body["error"]

    @patch("src.handlers.upload.sns_service")
    @patch("src.handlers.upload.dynamo_service")
    @patch("src.handlers.upload.s3_service")
    def test_empty_title_returns_400(self, mock_s3, mock_dynamo, mock_sns):
        """Empty/whitespace-only title returns 400 with MISSING_REQUIRED_FIELD code."""
        from src.handlers.upload import handler

        body = _valid_body()
        body["title"] = "   "
        event = _build_event(body)
        response = handler(event, None)

        assert response["statusCode"] == 400
        response_body = json.loads(response["body"])
        assert response_body["error"]["code"] == "MISSING_REQUIRED_FIELD"

    @patch("src.handlers.upload.sns_service")
    @patch("src.handlers.upload.dynamo_service")
    @patch("src.handlers.upload.s3_service")
    def test_missing_title_does_not_call_services(
        self, mock_s3, mock_dynamo, mock_sns
    ):
        """Missing title should not call downstream services."""
        from src.handlers.upload import handler

        body = _valid_body()
        del body["title"]
        event = _build_event(body)
        handler(event, None)

        mock_s3.generate_presigned_upload_url.assert_not_called()
        mock_dynamo.create_submission.assert_not_called()


class TestUploadHandlerDynamoDBFailure:
    """Tests for DynamoDB write failure handling (Requirements 4.4, 4.5)."""

    @patch("src.handlers.upload.sns_service")
    @patch("src.handlers.upload.dynamo_service")
    @patch("src.handlers.upload.s3_service")
    def test_dynamo_failure_returns_500(self, mock_s3, mock_dynamo, mock_sns):
        """DynamoDB write failure returns 500 Internal Server Error."""
        mock_s3.generate_presigned_upload_url.return_value = "https://s3.example.com/presigned"
        mock_dynamo.create_submission.side_effect = Exception("DynamoDB connection timeout")

        from src.handlers.upload import handler

        event = _build_event(_valid_body())
        response = handler(event, None)

        assert response["statusCode"] == 500
        response_body = json.loads(response["body"])
        assert response_body["error"]["code"] == "INTERNAL_ERROR"
        assert "correlation_id" in response_body["error"]

    @patch("src.handlers.upload.sns_service")
    @patch("src.handlers.upload.dynamo_service")
    @patch("src.handlers.upload.s3_service")
    def test_dynamo_failure_publishes_sns_notification(
        self, mock_s3, mock_dynamo, mock_sns
    ):
        """DynamoDB write failure triggers SNS error notification."""
        mock_s3.generate_presigned_upload_url.return_value = "https://s3.example.com/presigned"
        mock_s3.delete_object.return_value = None
        mock_dynamo.create_submission.side_effect = Exception("DynamoDB write failed")

        from src.handlers.upload import handler

        event = _build_event(_valid_body())
        handler(event, None)

        # SNS notification should be published for the DynamoDB failure
        mock_sns.publish_error_notification.assert_called()
        notification = mock_sns.publish_error_notification.call_args[0][0]
        assert notification.error_type.value == "DYNAMO_WRITE_FAILURE"
        assert "DynamoDB write failed" in notification.error_message

    @patch("src.handlers.upload.sns_service")
    @patch("src.handlers.upload.dynamo_service")
    @patch("src.handlers.upload.s3_service")
    def test_dynamo_failure_attempts_s3_compensation_delete(
        self, mock_s3, mock_dynamo, mock_sns
    ):
        """DynamoDB failure triggers compensating S3 delete attempt."""
        mock_s3.generate_presigned_upload_url.return_value = "https://s3.example.com/presigned"
        mock_dynamo.create_submission.side_effect = Exception("DynamoDB error")

        from src.handlers.upload import handler

        event = _build_event(_valid_body())
        handler(event, None)

        mock_s3.delete_object.assert_called_once()

    @patch("src.handlers.upload.sns_service")
    @patch("src.handlers.upload.dynamo_service")
    @patch("src.handlers.upload.s3_service")
    def test_dynamo_failure_and_s3_compensation_failure_publishes_both_notifications(
        self, mock_s3, mock_dynamo, mock_sns
    ):
        """When both DynamoDB write and S3 compensation fail, two SNS notifications are published."""
        mock_s3.generate_presigned_upload_url.return_value = "https://s3.example.com/presigned"
        mock_dynamo.create_submission.side_effect = Exception("DynamoDB error")
        mock_s3.delete_object.side_effect = Exception("S3 delete failed")

        from src.handlers.upload import handler

        event = _build_event(_valid_body())
        handler(event, None)

        # Two notifications: one for S3 compensation failure, one for DynamoDB failure
        assert mock_sns.publish_error_notification.call_count == 2
        error_types = [
            call[0][0].error_type.value
            for call in mock_sns.publish_error_notification.call_args_list
        ]
        assert "S3_COMPENSATION_FAILURE" in error_types
        assert "DYNAMO_WRITE_FAILURE" in error_types


class TestUploadHandlerPresignedUrlFailure:
    """Tests for presigned URL generation failure (Requirement 3.5)."""

    @patch("src.handlers.upload.sns_service")
    @patch("src.handlers.upload.dynamo_service")
    @patch("src.handlers.upload.s3_service")
    def test_presigned_url_failure_returns_500(self, mock_s3, mock_dynamo, mock_sns):
        """Presigned URL generation failure returns 500 Internal Server Error."""
        mock_s3.generate_presigned_upload_url.side_effect = Exception("S3 client error")

        from src.handlers.upload import handler

        event = _build_event(_valid_body())
        response = handler(event, None)

        assert response["statusCode"] == 500
        response_body = json.loads(response["body"])
        assert response_body["error"]["code"] == "INTERNAL_ERROR"
        assert "correlation_id" in response_body["error"]

    @patch("src.handlers.upload.sns_service")
    @patch("src.handlers.upload.dynamo_service")
    @patch("src.handlers.upload.s3_service")
    def test_presigned_url_failure_publishes_sns_notification(
        self, mock_s3, mock_dynamo, mock_sns
    ):
        """Presigned URL generation failure triggers SNS error notification."""
        mock_s3.generate_presigned_upload_url.side_effect = Exception("S3 client error")

        from src.handlers.upload import handler

        event = _build_event(_valid_body())
        handler(event, None)

        mock_sns.publish_error_notification.assert_called_once()
        notification = mock_sns.publish_error_notification.call_args[0][0]
        assert notification.error_type.value == "S3_WRITE_FAILURE"


class TestUploadHandlerErrorResponseFormat:
    """Tests for consistent error response format (Requirement 6.2)."""

    @patch("src.handlers.upload.sns_service")
    @patch("src.handlers.upload.dynamo_service")
    @patch("src.handlers.upload.s3_service")
    def test_error_response_includes_cors_headers(self, mock_s3, mock_dynamo, mock_sns):
        """Error responses include CORS headers."""
        from src.handlers.upload import handler

        body = _valid_body()
        body["contentType"] = "application/pdf"
        event = _build_event(body)
        response = handler(event, None)

        for key, value in CORS_HEADERS.items():
            assert response["headers"][key] == value

    @patch("src.handlers.upload.sns_service")
    @patch("src.handlers.upload.dynamo_service")
    @patch("src.handlers.upload.s3_service")
    def test_error_response_has_consistent_json_format(
        self, mock_s3, mock_dynamo, mock_sns
    ):
        """Error responses contain error.code, error.message, and error.correlation_id."""
        from src.handlers.upload import handler

        body = _valid_body()
        body["contentType"] = "application/pdf"
        event = _build_event(body)
        response = handler(event, None)

        response_body = json.loads(response["body"])
        assert "error" in response_body
        error = response_body["error"]
        assert "code" in error
        assert "message" in error
        assert "correlation_id" in error
