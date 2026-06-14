"""Unit tests for the parse_message Lambda handler."""

import json

import pytest

from handlers.parse_message import handler, parse_message


class TestParseMessage:
    """Tests for the parse_message function."""

    def _valid_message_body(self) -> str:
        return json.dumps(
            {
                "submission_id": "sub-123",
                "user_id": "user-456",
                "s3_bucket": "my-bucket",
                "s3_file_key": "uploads/file.mp3",
                "original_file_name": "presentation.mp3",
                "presentation_title": "My Presentation",
            }
        )

    def test_valid_message_returns_valid_true(self):
        result = parse_message(self._valid_message_body())
        assert result["valid"] is True
        assert result["message"]["submission_id"] == "sub-123"
        assert result["message"]["user_id"] == "user-456"
        assert result["message"]["s3_bucket"] == "my-bucket"
        assert result["message"]["s3_file_key"] == "uploads/file.mp3"
        assert result["message"]["original_file_name"] == "presentation.mp3"
        assert result["message"]["presentation_title"] == "My Presentation"

    def test_empty_string_returns_error(self):
        result = parse_message("")
        assert result["valid"] is False
        assert "Empty message body" in result["error"]

    def test_malformed_json_returns_error(self):
        result = parse_message("{not valid json}")
        assert result["valid"] is False
        assert "Malformed JSON" in result["error"]

    def test_missing_required_field_returns_error(self):
        body = json.dumps(
            {
                "submission_id": "sub-123",
                "user_id": "user-456",
                # Missing s3_bucket, s3_file_key, original_file_name, presentation_title
            }
        )
        result = parse_message(body)
        assert result["valid"] is False
        assert "Validation error" in result["error"]

    def test_empty_field_value_returns_error(self):
        body = json.dumps(
            {
                "submission_id": "",
                "user_id": "user-456",
                "s3_bucket": "my-bucket",
                "s3_file_key": "uploads/file.mp3",
                "original_file_name": "presentation.mp3",
                "presentation_title": "My Presentation",
            }
        )
        result = parse_message(body)
        assert result["valid"] is False
        assert "Validation error" in result["error"]

    def test_none_input_returns_error(self):
        result = parse_message(None)
        assert result["valid"] is False
        assert result["error"] is not None

    def test_numeric_input_returns_error(self):
        result = parse_message("12345")
        assert result["valid"] is False
        assert "Validation error" in result["error"]

    def test_json_array_returns_error(self):
        result = parse_message("[1, 2, 3]")
        assert result["valid"] is False
        assert "Validation error" in result["error"]


class TestHandler:
    """Tests for the Lambda handler wrapper."""

    def test_handler_extracts_message_body_from_event(self):
        event = {
            "message_body": json.dumps(
                {
                    "submission_id": "sub-123",
                    "user_id": "user-456",
                    "s3_bucket": "my-bucket",
                    "s3_file_key": "uploads/file.mp3",
                    "original_file_name": "presentation.mp3",
                    "presentation_title": "My Presentation",
                }
            )
        }
        result = handler(event, None)
        assert result["valid"] is True

    def test_handler_with_empty_event(self):
        result = handler({}, None)
        assert result["valid"] is False

    def test_handler_with_missing_message_body_key(self):
        result = handler({"other_key": "value"}, None)
        assert result["valid"] is False
