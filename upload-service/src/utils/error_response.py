"""Standardized error response builder for AWS Lambda HTTP API v2."""

import json
from typing import Any

from shared_types import CORS_HEADERS


def build_error_response(
    status_code: int, code: str, message: str, correlation_id: str
) -> dict[str, Any]:
    """
    Build a standardized HTTP API v2 error response.

    Returns a dict with statusCode, headers (including CORS), and a JSON body
    containing error.code, error.message, and error.correlation_id.

    Args:
        status_code: HTTP status code (e.g. 400, 413, 500).
        code: Machine-readable error code (e.g. "INVALID_FILE_TYPE").
        message: Human-readable error message.
        correlation_id: Unique identifier for troubleshooting.

    Returns:
        A dict formatted as an AWS Lambda HTTP API v2 response.
    """
    body = {
        "error": {
            "code": code,
            "message": message,
            "correlation_id": correlation_id,
        }
    }

    return {
        "statusCode": status_code,
        "headers": {**CORS_HEADERS, "Content-Type": "application/json"},
        "body": json.dumps(body),
    }
