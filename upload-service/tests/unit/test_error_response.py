"""Unit tests for the error response builder."""

import json

from src.utils.error_response import build_error_response


def test_build_error_response_returns_correct_status_code():
    result = build_error_response(400, "INVALID_FILE_TYPE", "File type not supported", "corr-123")
    assert result["statusCode"] == 400


def test_build_error_response_includes_cors_headers():
    result = build_error_response(500, "INTERNAL_ERROR", "Something went wrong", "corr-456")
    assert result["headers"]["Access-Control-Allow-Origin"] == "https://kiro.geiserai.com"
    assert result["headers"]["Access-Control-Allow-Methods"] == "GET, POST, OPTIONS"
    assert result["headers"]["Access-Control-Allow-Headers"] == "Content-Type, Authorization"
    assert result["headers"]["Access-Control-Max-Age"] == "86400"


def test_build_error_response_includes_content_type_header():
    result = build_error_response(413, "FILE_TOO_LARGE", "File exceeds 500 MB", "corr-789")
    assert result["headers"]["Content-Type"] == "application/json"


def test_build_error_response_body_is_json_string():
    result = build_error_response(400, "MISSING_FIELD", "Title is required", "corr-abc")
    body = json.loads(result["body"])
    assert body["error"]["code"] == "MISSING_FIELD"
    assert body["error"]["message"] == "Title is required"
    assert body["error"]["correlation_id"] == "corr-abc"


def test_build_error_response_body_contains_only_error_fields():
    result = build_error_response(500, "S3_FAILURE", "Upload failed", "corr-def")
    body = json.loads(result["body"])
    assert set(body.keys()) == {"error"}
    assert set(body["error"].keys()) == {"code", "message", "correlation_id"}
