"""Unit tests for the GET /submissions handler."""

import json
import os
from unittest.mock import patch, MagicMock

import pytest

from src.models.submission import ProcessingStatus, SubmissionRecord


def _build_event(user_id: str = "user-123") -> dict:
    """Build a minimal HTTP API v2 event with JWT authorizer claims."""
    return {
        "requestContext": {
            "authorizer": {
                "jwt": {"claims": {"sub": user_id}}
            }
        }
    }


def _make_submission(
    submission_id: str,
    user_id: str = "user-123",
    upload_date: str = "2024-06-15T10:30:00Z",
    title: str = "Test Presentation",
    status: ProcessingStatus = ProcessingStatus.PENDING,
    description: str | None = None,
    completion_date: str | None = None,
    report_link: str | None = None,
) -> SubmissionRecord:
    """Create a SubmissionRecord for testing."""
    return SubmissionRecord(
        submission_id=submission_id,
        user_id=user_id,
        original_file_name="presentation.mp3",
        presentation_title=title,
        description=description,
        s3_file_key=f"uploads/{user_id}/{submission_id}/presentation.mp3",
        content_type="audio/mpeg",
        file_size_bytes=1024000,
        upload_date=upload_date,
        processing_status=status,
        completion_date=completion_date,
        report_link=report_link,
    )


@pytest.fixture(autouse=True)
def set_env():
    """Set required environment variables before importing the handler."""
    with patch.dict(os.environ, {"DYNAMODB_TABLE_NAME": "test-submissions"}):
        yield


class TestGetSubmissionsHappyPath:
    """Test happy path: returns submissions sorted by upload_date descending with CORS headers."""

    def test_returns_200_with_submissions(self, set_env):
        """Handler returns 200 with submissions array when records exist."""
        records = [
            _make_submission("sub-1", upload_date="2024-06-15T12:00:00Z", title="Recent"),
            _make_submission("sub-2", upload_date="2024-06-15T10:00:00Z", title="Older"),
        ]

        with patch("src.handlers.get_submissions.dynamo_service") as mock_dynamo:
            mock_dynamo.get_submissions_by_user.return_value = records

            from src.handlers.get_submissions import handler

            response = handler(_build_event(), None)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert len(body["submissions"]) == 2

    def test_submissions_have_correct_camelcase_fields(self, set_env):
        """Response maps DynamoDB fields to camelCase frontend field names."""
        record = _make_submission(
            "sub-abc",
            title="My Talk",
            description="A great talk",
            upload_date="2024-06-15T10:30:00Z",
            status=ProcessingStatus.COMPLETED,
            completion_date="2024-06-15T11:00:00Z",
            report_link="https://reports.example.com/sub-abc",
        )

        with patch("src.handlers.get_submissions.dynamo_service") as mock_dynamo:
            mock_dynamo.get_submissions_by_user.return_value = [record]

            from src.handlers.get_submissions import handler

            response = handler(_build_event(), None)

        body = json.loads(response["body"])
        submission = body["submissions"][0]

        assert submission["id"] == "sub-abc"
        assert submission["title"] == "My Talk"
        assert submission["fileName"] == "presentation.mp3"
        assert submission["description"] == "A great talk"
        assert submission["dateUploaded"] == "2024-06-15T10:30:00Z"
        assert submission["status"] == "Completed"
        assert submission["dateCompleted"] == "2024-06-15T11:00:00Z"
        assert submission["reportUrl"] == "https://reports.example.com/sub-abc"

    def test_response_includes_cors_headers(self, set_env):
        """Response must include CORS headers for the allowed origin."""
        with patch("src.handlers.get_submissions.dynamo_service") as mock_dynamo:
            mock_dynamo.get_submissions_by_user.return_value = [
                _make_submission("sub-1")
            ]

            from src.handlers.get_submissions import handler

            response = handler(_build_event(), None)

        headers = response["headers"]
        assert headers["Access-Control-Allow-Origin"] == "https://kiro.geiserai.com"
        assert "GET" in headers["Access-Control-Allow-Methods"]
        assert "POST" in headers["Access-Control-Allow-Methods"]
        assert headers["Content-Type"] == "application/json"

    def test_submissions_sorted_descending_by_upload_date(self, set_env):
        """Handler returns submissions in descending upload_date order (most recent first)."""
        # DynamoService already sorts via GSI ScanIndexForward=False,
        # so the handler should preserve the order returned by the service.
        records = [
            _make_submission("sub-3", upload_date="2024-06-16T08:00:00Z"),
            _make_submission("sub-1", upload_date="2024-06-15T12:00:00Z"),
            _make_submission("sub-2", upload_date="2024-06-14T09:00:00Z"),
        ]

        with patch("src.handlers.get_submissions.dynamo_service") as mock_dynamo:
            mock_dynamo.get_submissions_by_user.return_value = records

            from src.handlers.get_submissions import handler

            response = handler(_build_event(), None)

        body = json.loads(response["body"])
        dates = [s["dateUploaded"] for s in body["submissions"]]
        assert dates == [
            "2024-06-16T08:00:00Z",
            "2024-06-15T12:00:00Z",
            "2024-06-14T09:00:00Z",
        ]

    def test_extracts_user_id_from_jwt_claims(self, set_env):
        """Handler queries DynamoDB with the user_id from JWT claims."""
        with patch("src.handlers.get_submissions.dynamo_service") as mock_dynamo:
            mock_dynamo.get_submissions_by_user.return_value = []

            from src.handlers.get_submissions import handler

            handler(_build_event(user_id="cognito-user-xyz"), None)

        mock_dynamo.get_submissions_by_user.assert_called_once_with("cognito-user-xyz")


class TestGetSubmissionsNoResults:
    """Test no submissions: returns 200 with empty array."""

    def test_returns_200_with_empty_submissions_array(self, set_env):
        """When no submissions exist, returns 200 with empty array."""
        with patch("src.handlers.get_submissions.dynamo_service") as mock_dynamo:
            mock_dynamo.get_submissions_by_user.return_value = []

            from src.handlers.get_submissions import handler

            response = handler(_build_event(), None)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["submissions"] == []

    def test_empty_response_includes_cors_headers(self, set_env):
        """Even empty responses must include CORS headers."""
        with patch("src.handlers.get_submissions.dynamo_service") as mock_dynamo:
            mock_dynamo.get_submissions_by_user.return_value = []

            from src.handlers.get_submissions import handler

            response = handler(_build_event(), None)

        headers = response["headers"]
        assert headers["Access-Control-Allow-Origin"] == "https://kiro.geiserai.com"


class TestGetSubmissionsDynamoFailure:
    """Test DynamoDB query failure → 500 response."""

    def test_dynamo_failure_returns_500(self, set_env):
        """When DynamoDB query raises, handler returns 500 error response."""
        with patch("src.handlers.get_submissions.dynamo_service") as mock_dynamo:
            mock_dynamo.get_submissions_by_user.side_effect = Exception(
                "ProvisionedThroughputExceededException"
            )

            from src.handlers.get_submissions import handler

            response = handler(_build_event(), None)

        assert response["statusCode"] == 500

    def test_dynamo_failure_response_has_error_format(self, set_env):
        """500 response includes structured error with code and correlation_id."""
        with patch("src.handlers.get_submissions.dynamo_service") as mock_dynamo:
            mock_dynamo.get_submissions_by_user.side_effect = Exception(
                "Service unavailable"
            )

            from src.handlers.get_submissions import handler

            response = handler(_build_event(), None)

        body = json.loads(response["body"])
        assert "error" in body
        assert body["error"]["code"] == "DYNAMO_QUERY_FAILURE"
        assert "correlation_id" in body["error"]
        assert len(body["error"]["correlation_id"]) > 0

    def test_dynamo_failure_response_includes_cors_headers(self, set_env):
        """Error responses must also include CORS headers."""
        with patch("src.handlers.get_submissions.dynamo_service") as mock_dynamo:
            mock_dynamo.get_submissions_by_user.side_effect = RuntimeError("Timeout")

            from src.handlers.get_submissions import handler

            response = handler(_build_event(), None)

        headers = response["headers"]
        assert headers["Access-Control-Allow-Origin"] == "https://kiro.geiserai.com"
        assert headers["Content-Type"] == "application/json"
