"""POST /submissions handler — validates metadata, generates presigned S3 URL, creates DynamoDB record."""

import json
import logging
from datetime import datetime, timezone
from typing import Any

from models.submission import (
    ErrorNotification,
    ErrorType,
    ProcessingStatus,
    SubmissionRecord,
)
from services.dynamo_service import DynamoService
from services.s3_service import S3Service
from services.sns_service import SnsService
from shared_types import CORS_HEADERS
from utils.error_response import build_error_response
from utils.file_key_generator import generate_file_key
from utils.id_generator import generate_correlation_id, generate_submission_id
from validation.file_validator import FileValidationInput, validate_file
from validation.metadata_validator import MetadataInput, validate_metadata

logger = logging.getLogger(__name__)

# Service instances (reused across warm invocations)
s3_service = S3Service()
dynamo_service = DynamoService()
sns_service = SnsService()


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Handle POST /submissions requests (HTTP API payload format 2.0).

    Validates metadata, generates a presigned S3 PUT URL, and creates a
    DynamoDB submission record. Returns submissionId and presignedUrl to the client.

    Extracts user_id from event["requestContext"]["authorizer"]["jwt"]["claims"]["sub"].
    """
    correlation_id = generate_correlation_id()

    # Extract user_id from JWT claims
    try:
        user_id: str = event["requestContext"]["authorizer"]["jwt"]["claims"]["sub"]
    except (KeyError, TypeError):
        logger.error("Failed to extract user_id from JWT claims", extra={"correlation_id": correlation_id})
        return build_error_response(500, "INTERNAL_ERROR", "Unable to identify user", correlation_id)

    # Parse JSON body
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return build_error_response(400, "MISSING_REQUIRED_FIELD", "Request body must be valid JSON", correlation_id)

    # Extract fields from camelCase request body
    title = body.get("title")
    description = body.get("description")
    file_name = body.get("fileName")
    content_type = body.get("contentType")
    file_size_bytes = body.get("fileSizeBytes")

    # Validate metadata (map camelCase → snake_case field names)
    metadata_input = MetadataInput(
        presentation_title=title,
        description=description,
        original_file_name=file_name,
    )
    metadata_result = validate_metadata(metadata_input)
    if not metadata_result.valid:
        error_fields = ", ".join(e.field for e in metadata_result.errors)
        return build_error_response(
            400,
            "MISSING_REQUIRED_FIELD",
            f"Validation failed for: {error_fields}",
            correlation_id,
        )

    # Validate file (map camelCase → snake_case field names)
    if content_type is None or file_size_bytes is None:
        return build_error_response(
            400,
            "MISSING_REQUIRED_FIELD",
            "contentType and fileSizeBytes are required",
            correlation_id,
        )

    file_input = FileValidationInput(
        file_name=file_name,
        content_type=content_type,
        file_size_bytes=int(file_size_bytes),
    )
    file_result = validate_file(file_input)
    if not file_result.valid:
        # Determine error code based on error message
        error_code = "INVALID_FILE_TYPE"
        status_code = 400
        if "size" in (file_result.error or "").lower():
            error_code = "FILE_TOO_LARGE"
            status_code = 413
        return build_error_response(status_code, error_code, file_result.error or "File validation failed", correlation_id)

    # Generate identifiers
    submission_id = generate_submission_id()
    file_key = generate_file_key(user_id, submission_id, file_name)
    upload_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Generate presigned URL
    try:
        presigned_url = s3_service.generate_presigned_upload_url(file_key, content_type)
    except Exception as e:
        logger.error(
            "Presigned URL generation failed for file_key=%s: %s",
            file_key,
            str(e),
            extra={"correlation_id": correlation_id},
        )
        notification = ErrorNotification(
            submission_id=submission_id,
            error_type=ErrorType.S3_WRITE_FAILURE,
            error_message=f"Failed to generate presigned upload URL: {str(e)}",
            timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            service_component="upload_handler",
        )
        sns_service.publish_error_notification(notification)
        return build_error_response(500, "INTERNAL_ERROR", "Failed to generate upload URL", correlation_id)

    # Create submission record
    record = SubmissionRecord(
        submission_id=submission_id,
        user_id=user_id,
        original_file_name=file_name,
        presentation_title=title,
        description=description,
        s3_file_key=file_key,
        content_type=content_type,
        file_size_bytes=int(file_size_bytes),
        upload_date=upload_date,
        processing_status=ProcessingStatus.PENDING,
    )

    # Persist to DynamoDB
    try:
        dynamo_service.create_submission(record)
    except Exception as e:
        logger.error(
            "DynamoDB write failed for submission_id=%s: %s",
            submission_id,
            str(e),
            extra={"correlation_id": correlation_id},
        )
        # Compensation: attempt S3 delete (presigned URL was generated but record failed)
        try:
            s3_service.delete_object(file_key)
        except Exception as s3_err:
            # S3 compensation also failed — publish SNS notification with orphaned key
            logger.error(
                "S3 compensation delete failed for key=%s: %s",
                file_key,
                str(s3_err),
                extra={"correlation_id": correlation_id},
            )
            notification = ErrorNotification(
                submission_id=submission_id,
                error_type=ErrorType.S3_COMPENSATION_FAILURE,
                error_message=f"Failed to delete orphaned S3 object: {str(s3_err)}",
                timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                service_component="upload_handler",
                orphaned_s3_key=file_key,
            )
            sns_service.publish_error_notification(notification)

        # Publish DynamoDB failure notification
        notification = ErrorNotification(
            submission_id=submission_id,
            error_type=ErrorType.DYNAMO_WRITE_FAILURE,
            error_message=str(e),
            timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            service_component="upload_handler",
        )
        sns_service.publish_error_notification(notification)

        return build_error_response(500, "INTERNAL_ERROR", "Failed to create submission record", correlation_id)

    # Success response
    response_body = {
        "submissionId": submission_id,
        "presignedUrl": presigned_url,
        "status": "Pending",
    }

    return {
        "statusCode": 201,
        "headers": {**CORS_HEADERS, "Content-Type": "application/json"},
        "body": json.dumps(response_body),
    }
