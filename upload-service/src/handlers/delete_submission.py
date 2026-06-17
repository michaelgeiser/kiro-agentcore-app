"""DELETE /submissions/{id} handler for hard-deleting a submission and all related resources."""

import json
import logging
import os
from typing import Any

import boto3

from services.dynamo_service import DynamoService
from shared_types import CORS_HEADERS
from utils.error_response import build_error_response

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

dynamo_service = DynamoService()
s3_client = boto3.client("s3")

UPLOADS_BUCKET = os.environ.get("UPLOADS_BUCKET", "")


def _delete_s3_prefix(bucket: str, prefix: str) -> int:
    """Delete all objects under a given S3 prefix.

    Args:
        bucket: S3 bucket name.
        prefix: Key prefix to delete under.

    Returns:
        Number of objects deleted.
    """
    deleted_count = 0
    paginator = s3_client.get_paginator("list_objects_v2")

    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        objects = page.get("Contents", [])
        if not objects:
            continue

        delete_keys = [{"Key": obj["Key"]} for obj in objects]
        s3_client.delete_objects(
            Bucket=bucket,
            Delete={"Objects": delete_keys, "Quiet": True},
        )
        deleted_count += len(delete_keys)

    return deleted_count


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Handle DELETE /submissions/{id} requests.

    Performs a hard delete of:
    1. The DynamoDB submission record
    2. All S3 objects under uploads/{user_id}/{submission_id}/
    3. All S3 objects under processed/{user_id}/{submission_id}/
    4. All S3 objects under evaluations/{submission_id}/
    5. All S3 objects under reports/{user_id}/{submission_id}/

    The user_id from the JWT must match the submission's user_id.
    """
    try:
        # Extract submission_id from path
        path_params = event.get("pathParameters") or {}
        submission_id = path_params.get("id")

        if not submission_id:
            return build_error_response(400, "Missing submission ID in path")

        # Extract authenticated user_id from JWT claims
        request_context = event.get("requestContext", {})
        authorizer = request_context.get("authorizer", {})
        jwt_claims = authorizer.get("jwt", {}).get("claims", {})
        user_id = jwt_claims.get("sub")

        if not user_id:
            return build_error_response(401, "Unable to determine user identity")

        logger.info(
            "Delete request for submission_id=%s by user_id=%s",
            submission_id,
            user_id,
        )

        # Fetch the submission record to verify ownership
        record = dynamo_service.get_submission(submission_id)

        if record is None:
            return build_error_response(404, "Submission not found")

        if record.user_id != user_id:
            return build_error_response(403, "Not authorized to delete this submission")

        # Delete all S3 objects related to this submission
        total_deleted = 0
        prefixes = [
            f"uploads/{user_id}/{submission_id}/",
            f"processed/{user_id}/{submission_id}/",
            f"evaluations/{submission_id}/",
            f"reports/{user_id}/{submission_id}/",
        ]

        for prefix in prefixes:
            count = _delete_s3_prefix(UPLOADS_BUCKET, prefix)
            if count > 0:
                logger.info("Deleted %d objects from s3://%s/%s", count, UPLOADS_BUCKET, prefix)
            total_deleted += count

        # Also try the vector store location if embeddings are in the same bucket
        vector_prefix = f"{submission_id}/embeddings/"
        count = _delete_s3_prefix(UPLOADS_BUCKET, vector_prefix)
        if count > 0:
            logger.info("Deleted %d embedding objects from s3://%s/%s", count, UPLOADS_BUCKET, vector_prefix)
            total_deleted += count

        # Delete the DynamoDB record
        dynamo_service.delete_submission(submission_id)
        logger.info(
            "Deleted submission record for submission_id=%s (total S3 objects: %d)",
            submission_id,
            total_deleted,
        )

        return {
            "statusCode": 200,
            "headers": CORS_HEADERS,
            "body": json.dumps({
                "message": "Submission deleted successfully",
                "deletedS3Objects": total_deleted,
            }),
        }

    except Exception as exc:
        logger.exception("Error deleting submission: %s", exc)
        return build_error_response(500, "Failed to delete submission")
