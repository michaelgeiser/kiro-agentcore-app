# Feature: upload-and-storage, Property 7: Error response format consistency
"""
Property-based tests for the error response builder.

**Validates: Requirements 6.2**

For any error scenario (any HTTP status code, error code string, message string,
and correlation ID), build_error_response should produce a response body containing
exactly the fields error.code, error.message, and error.correlation_id with values
matching the inputs. The response should include CORS headers with the correct
Access-Control-Allow-Origin.
"""

import json

from hypothesis import given, settings
from hypothesis import strategies as st

from src.utils.error_response import build_error_response


@settings(max_examples=100)
@given(
    status_code=st.integers(min_value=400, max_value=599),
    code=st.text(min_size=1),
    message=st.text(min_size=1),
    correlation_id=st.text(min_size=1),
)
def test_error_response_contains_exact_error_fields(
    status_code: int, code: str, message: str, correlation_id: str
) -> None:
    """The response body contains exactly error.code, error.message, and error.correlation_id
    with values matching the inputs."""
    response = build_error_response(status_code, code, message, correlation_id)

    body = json.loads(response["body"])

    # Body must contain exactly one top-level key: "error"
    assert set(body.keys()) == {"error"}, f"Expected only 'error' key, got {set(body.keys())}"

    # Error object must contain exactly code, message, correlation_id
    error_obj = body["error"]
    assert set(error_obj.keys()) == {"code", "message", "correlation_id"}, (
        f"Expected exactly code/message/correlation_id, got {set(error_obj.keys())}"
    )

    # Values must match inputs
    assert error_obj["code"] == code
    assert error_obj["message"] == message
    assert error_obj["correlation_id"] == correlation_id


@settings(max_examples=100)
@given(
    status_code=st.integers(min_value=400, max_value=599),
    code=st.text(min_size=1),
    message=st.text(min_size=1),
    correlation_id=st.text(min_size=1),
)
def test_error_response_has_correct_status_code(
    status_code: int, code: str, message: str, correlation_id: str
) -> None:
    """The response statusCode matches the provided status code."""
    response = build_error_response(status_code, code, message, correlation_id)

    assert response["statusCode"] == status_code


@settings(max_examples=100)
@given(
    status_code=st.integers(min_value=400, max_value=599),
    code=st.text(min_size=1),
    message=st.text(min_size=1),
    correlation_id=st.text(min_size=1),
)
def test_error_response_includes_cors_headers(
    status_code: int, code: str, message: str, correlation_id: str
) -> None:
    """The response includes CORS headers with the correct Access-Control-Allow-Origin."""
    response = build_error_response(status_code, code, message, correlation_id)

    headers = response["headers"]
    assert "Access-Control-Allow-Origin" in headers
    assert headers["Access-Control-Allow-Origin"] == "https://kiro.geiserai.com"
