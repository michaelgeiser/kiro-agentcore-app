"""S3 event handler — confirms upload and publishes SQS processing message."""

import logging
from datetime import datetime, timezone
from typing import Any
from urllib.parse import unquote_plus

from models.submission import ErrorNotification, ErrorType
from models.sqs_message import SqsMessageBody
from services.dynamo_service import DynamoService
from services.sns_service import SnsService
from services.sqs_service import SqsService

logger = logging.getLogger(__name__)

# Service instances (reused across warm invocations)
dynamo_service = DynamoService()
sqs_service = SqsService()
sns_service = SnsService()


def handler(event: dict[str, Any], context: Any) -> None:
    """Handle S3 PutObject event when client completes file upload.

    Triggered by S3 event notification. Parses the event to extract
    bucket and object key, looks up the submission record, builds an
    SQS message, and publishes it to trigger downstream processing.

    On SQS failure after retries: updates status to Failed and publishes
    an SNS error notification.
    """
    for record in event.get("Records", []):
        s3_info = record.get("s3", {})
        bucket = s3_info.get("bucket", {}).get("name", "")
        object_key = unquote_plus(s3_info.get("object", {}).get("key", ""))

        if not object_key:
            logger.error("S3 event record missing object key")
            continue

        logger.info("Processing S3 event: bucket=%s, key=%s", bucket, object_key)

        # Parse the file key to extract user_id and submission_id
        # Key format: uploads/{user_id}/{submission_id}/{filename}
        parts = object_key.split("/")
        if len(parts) < 4 or parts[0] != "uploads":
            logger.error(
                "Unexpected S3 key format: %s (expected uploads/{user_id}/{submission_id}/{filename})",
                object_key,
            )
            continue

        user_id = parts[1]
        submission_id = parts[2]

        # Look up submission record by querying user's submissions and filtering
        try:
            submissions = dynamo_service.get_submissions_by_user(user_id)
            submission = next(
                (s for s in submissions if s.submission_id == submission_id),
                None,
            )
        except Exception as e:
            logger.error(
                "Failed to query DynamoDB for user_id=%s, submission_id=%s: %s",
                user_id,
                submission_id,
                str(e),
            )
            continue

        if submission is None:
            logger.error(
                "Submission record not found: user_id=%s, submission_id=%s",
                user_id,
                submission_id,
            )
            continue

        # Build SQS message from submission data
        message = SqsMessageBody(
            submission_id=submission.submission_id,
            user_id=submission.user_id,
            s3_bucket=bucket,
            s3_file_key=submission.s3_file_key,
            original_file_name=submission.original_file_name,
            presentation_title=submission.presentation_title,
        )

        # Publish to SQS with retry (3x by default)
        try:
            sqs_service.publish_message(message, max_retries=3)
            logger.info(
                "SQS message published for submission_id=%s",
                submission_id,
            )
        except Exception as e:
            logger.error(
                "SQS publish failed after retries for submission_id=%s: %s",
                submission_id,
                str(e),
            )

            # Update status to Failed
            try:
                dynamo_service.update_status(submission_id, "Failed")
            except Exception as update_err:
                logger.error(
                    "Failed to update status to Failed for submission_id=%s: %s",
                    submission_id,
                    str(update_err),
                )

            # Publish SNS error notification (best-effort)
            notification = ErrorNotification(
                submission_id=submission_id,
                error_type=ErrorType.SQS_PUBLISH_FAILURE,
                error_message=str(e),
                timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                service_component="confirm_upload_handler",
            )
            sns_service.publish_error_notification(notification)
