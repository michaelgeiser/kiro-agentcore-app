"""GET /submissions handler for retrieving user submissions."""

import json
import logging
import os
import uuid
from typing import Any

import boto3

from models.submission import SubmissionRecord
from services.dynamo_service import DynamoService
from shared_types import CORS_HEADERS
from utils.error_response import build_error_response

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

dynamo_service = DynamoService()
s3_client = boto3.client("s3")

# S3 bucket where reports are stored (same as uploads bucket)
UPLOADS_BUCKET = os.environ.get("UPLOADS_BUCKET", "")


def _get_report_download_url(record: SubmissionRecord) -> str | None:
    """Generate a presigned S3 download URL for the coaching report.

    Checks report_path (written by agentic-evaluation) first, then
    report_link (legacy field) as fallback.

    Returns None if no report path is available.
    """
    report_key = record.report_path or record.report_link
    if not report_key:
        return None

    try:
        url = s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": UPLOADS_BUCKET, "Key": report_key},
            ExpiresIn=3600,  # 1 hour
        )
        return url
    except Exception as exc:
        logger.warning(
            "Failed to generate presigned URL for report_path=%s: %s",
            report_key,
            exc,
        )
        return None


def _map_record_to_response(record: SubmissionRecord) -> dict:
    """Map a SubmissionRecord to a frontend-compatible camelCase dict.

    Converts internal field names to the Frontend SPA's expected data model.
    Generates a presigned S3 URL for the report download if available.
    """
    return {
        "id": record.submission_id,
        "title": record.presentation_title,
        "fileName": record.original_file_name,
        "description": record.description,
        "dateUploaded": record.upload_date,
        "status": record.processing_status.value,
        "dateCompleted": record.completion_date,
        "reportUrl": _get_report_download_url(record),
    }


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Handle GET /submissions requests (HTTP API payload format 2.0).

    Queries DynamoDB for all submissions belonging to the authenticated user.
    Returns submissions sorted by upload_date descending (most recent first).

    Args:
        event: API Gateway v2 event with JWT authorizer claims.
        context: Lambda context (unused).

    Returns:
        HTTP API v2 response with submissions array or error.
    """
    correlation_id = str(uuid.uuid4())

    # Extract user_id from JWT claims
    user_id = event["requestContext"]["authorizer"]["jwt"]["claims"]["sub"]

    try:
        records = dynamo_service.get_submissions_by_user(user_id)
    except Exception as e:
        logger.error(
            "DynamoDB query failed for user %s: %s",
            user_id,
            str(e),
            extra={"correlation_id": correlation_id},
        )
        return build_error_response(
            status_code=500,
            code="DYNAMO_QUERY_FAILURE",
            message="Failed to retrieve submissions. Please try again later.",
            correlation_id=correlation_id,
        )

    submissions = [_map_record_to_response(record) for record in records]

    return {
        "statusCode": 200,
        "headers": {**CORS_HEADERS, "Content-Type": "application/json"},
        "body": json.dumps({"submissions": submissions}),
    }
