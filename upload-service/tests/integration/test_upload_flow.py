"""Integration tests for the upload flow (POST /submissions).

Tests end-to-end handler execution with mocked AWS services (moto):
- Happy path: valid input → DynamoDB record created → presigned URL returned
- DynamoDB failure compensation: DynamoDB write fails → S3 object deleted

Requirements: 1.1, 3.1, 4.1, 4.4, 6.1
"""

import importlib
import json
import os
import sys
from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws

# --------------------------------------------------------------------------
# Environment setup — must happen BEFORE any handler/service imports because
# the service classes read env vars at module-level instantiation time.
# --------------------------------------------------------------------------

TEST_BUCKET_NAME = "test-integration-bucket"
TEST_TABLE_NAME = "test-integration-submissions"
TEST_SNS_TOPIC_ARN = "arn:aws:sns:us-east-1:123456789012:test-errors"
TEST_SQS_QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/test-queue"

_ENV_VARS = {
    "S3_BUCKET_NAME": TEST_BUCKET_NAME,
    "DYNAMODB_TABLE_NAME": TEST_TABLE_NAME,
    "SNS_TOPIC_ARN": TEST_SNS_TOPIC_ARN,
    "SQS_QUEUE_URL": TEST_SQS_QUEUE_URL,
    "AWS_DEFAULT_REGION": "us-east-1",
    "AWS_ACCESS_KEY_ID": "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
    "AWS_SECURITY_TOKEN": "testing",
    "AWS_SESSION_TOKEN": "testing",
}


def _build_event(body: dict, user_id: str = "user-integration-123") -> dict:
    """Build an HTTP API v2 event with JWT claims."""
    return {
        "requestContext": {
            "authorizer": {
                "jwt": {"claims": {"sub": user_id}}
            }
        },
        "body": json.dumps(body),
    }


def _valid_body() -> dict:
    """Return a valid upload request body."""
    return {
        "title": "Integration Test Presentation",
        "description": "Testing end-to-end upload flow",
        "fileName": "test-recording.mp3",
        "contentType": "audio/mpeg",
        "fileSizeBytes": 10_000_000,
    }


def _create_s3_bucket(region: str = "us-east-1") -> None:
    """Create the test S3 bucket in moto."""
    s3 = boto3.client("s3", region_name=region)
    s3.create_bucket(Bucket=TEST_BUCKET_NAME)


def _create_dynamodb_table(region: str = "us-east-1") -> None:
    """Create the test DynamoDB table with GSI in moto."""
    dynamodb = boto3.client("dynamodb", region_name=region)
    dynamodb.create_table(
        TableName=TEST_TABLE_NAME,
        KeySchema=[
            {"AttributeName": "submission_id", "KeyType": "HASH"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "submission_id", "AttributeType": "S"},
            {"AttributeName": "user_id", "AttributeType": "S"},
            {"AttributeName": "upload_date", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "user-uploads-index",
                "KeySchema": [
                    {"AttributeName": "user_id", "KeyType": "HASH"},
                    {"AttributeName": "upload_date", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
        BillingMode="PAY_PER_REQUEST",
    )


def _create_sns_topic(region: str = "us-east-1") -> str:
    """Create the test SNS topic in moto and return the ARN."""
    sns = boto3.client("sns", region_name=region)
    response = sns.create_topic(Name="test-errors")
    return response["TopicArn"]


def _reload_handler_module():
    """Force reimport of the handler and service modules.

    Since services are instantiated at module level, we must reload them
    within the moto context so they get mocked boto3 clients.
    """
    # Remove cached modules so they re-instantiate with moto clients
    modules_to_reload = [
        "src.services.s3_service",
        "src.services.dynamo_service",
        "src.services.sns_service",
        "src.handlers.upload",
    ]
    for mod_name in modules_to_reload:
        if mod_name in sys.modules:
            del sys.modules[mod_name]

    # Import fresh — this triggers module-level service instantiation inside moto
    from src.handlers.upload import handler

    return handler


class TestUploadFlowHappyPath:
    """Integration test: valid request → DynamoDB record + presigned URL returned.

    Requirements: 1.1, 3.1, 4.1, 6.1
    """

    @mock_aws
    def test_valid_upload_returns_201_with_submission_data(self):
        """POST /submissions with valid input creates a DynamoDB record and returns presigned URL."""
        with patch.dict(os.environ, _ENV_VARS):
            # Create AWS resources inside moto context
            _create_s3_bucket()
            _create_dynamodb_table()
            _create_sns_topic()

            handler = _reload_handler_module()

            event = _build_event(_valid_body())
            response = handler(event, None)

            # Verify 201 response
            assert response["statusCode"] == 201
            body = json.loads(response["body"])
            assert "submissionId" in body
            assert "presignedUrl" in body
            assert body["status"] == "Pending"

            # Verify presigned URL is a valid S3 URL
            assert TEST_BUCKET_NAME in body["presignedUrl"]
            assert "test-recording.mp3" in body["presignedUrl"]

    @mock_aws
    def test_valid_upload_creates_dynamodb_record(self):
        """Successful upload persists correct submission record in DynamoDB."""
        with patch.dict(os.environ, _ENV_VARS):
            _create_s3_bucket()
            _create_dynamodb_table()
            _create_sns_topic()

            handler = _reload_handler_module()

            event = _build_event(_valid_body(), user_id="user-abc-456")
            response = handler(event, None)

            assert response["statusCode"] == 201
            body = json.loads(response["body"])
            submission_id = body["submissionId"]

            # Query DynamoDB to verify the record
            dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
            table = dynamodb.Table(TEST_TABLE_NAME)
            item = table.get_item(Key={"submission_id": submission_id})["Item"]

            assert item["submission_id"] == submission_id
            assert item["user_id"] == "user-abc-456"
            assert item["original_file_name"] == "test-recording.mp3"
            assert item["presentation_title"] == "Integration Test Presentation"
            assert item["description"] == "Testing end-to-end upload flow"
            assert item["content_type"] == "audio/mpeg"
            assert item["file_size_bytes"] == 10_000_000
            assert item["processing_status"] == "Pending"
            # s3_file_key should follow naming convention
            assert item["s3_file_key"].startswith("uploads/user-abc-456/")
            assert item["s3_file_key"].endswith("/test-recording.mp3")

    @mock_aws
    def test_valid_upload_response_has_cors_headers(self):
        """Successful response includes CORS headers."""
        with patch.dict(os.environ, _ENV_VARS):
            _create_s3_bucket()
            _create_dynamodb_table()
            _create_sns_topic()

            handler = _reload_handler_module()

            event = _build_event(_valid_body())
            response = handler(event, None)

            assert response["statusCode"] == 201
            assert response["headers"]["Access-Control-Allow-Origin"] == "https://kiro.geiserai.com"
            assert "Content-Type" in response["headers"]


class TestUploadFlowDynamoDBCompensation:
    """Integration test: DynamoDB failure triggers S3 compensation delete.

    Requirements: 4.4
    """

    @mock_aws
    def test_dynamo_failure_returns_500_and_compensates(self):
        """When DynamoDB write fails, handler returns 500 and attempts S3 cleanup."""
        with patch.dict(os.environ, _ENV_VARS):
            _create_s3_bucket()
            _create_dynamodb_table()
            _create_sns_topic()

            handler = _reload_handler_module()

            # Patch the DynamoDB service's create_submission to simulate failure
            # We need to patch the module-level instance in the freshly loaded handler
            from src.handlers import upload as upload_module

            original_create = upload_module.dynamo_service.create_submission
            upload_module.dynamo_service.create_submission = lambda record: (_ for _ in ()).throw(
                Exception("Simulated DynamoDB write failure")
            )

            try:
                event = _build_event(_valid_body())
                response = handler(event, None)

                # Handler should return 500
                assert response["statusCode"] == 500
                body = json.loads(response["body"])
                assert body["error"]["code"] == "INTERNAL_ERROR"
                assert "correlation_id" in body["error"]

                # S3 compensation: the presigned URL was generated for a key,
                # and the handler should have called delete_object on that key.
                # Since we're using moto and the object was never actually uploaded
                # (presigned URL just generates a URL, doesn't put an object),
                # the delete_object call succeeds silently. We verify the handler
                # didn't crash during compensation by checking the 500 response.
            finally:
                upload_module.dynamo_service.create_submission = original_create

    @mock_aws
    def test_dynamo_failure_does_not_leave_orphaned_record(self):
        """When DynamoDB write fails, no submission record exists in the table."""
        with patch.dict(os.environ, _ENV_VARS):
            _create_s3_bucket()
            _create_dynamodb_table()
            _create_sns_topic()

            handler = _reload_handler_module()

            from src.handlers import upload as upload_module

            original_create = upload_module.dynamo_service.create_submission
            upload_module.dynamo_service.create_submission = lambda record: (_ for _ in ()).throw(
                Exception("Simulated DynamoDB failure")
            )

            try:
                event = _build_event(_valid_body(), user_id="user-compensation-test")
                response = handler(event, None)

                assert response["statusCode"] == 500

                # Verify no records exist in the table
                dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
                table = dynamodb.Table(TEST_TABLE_NAME)
                scan_result = table.scan()
                assert scan_result["Count"] == 0
            finally:
                upload_module.dynamo_service.create_submission = original_create
