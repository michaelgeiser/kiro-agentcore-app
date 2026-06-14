"""Integration tests for end-to-end Preparation Workflow handler chains.

Tests the handler chain working together with mocked AWS services via moto.
These are NOT tests of Step Functions orchestration itself — they test the
sequence of handler invocations that the workflow would execute.

Requirements validated: 1.1, 1.3, 2.1, 2.2, 2.3, 2.4, 3.1, 4.1, 6.1, 6.2, 7.1, 7.5, 8.5
"""

import json

import boto3
import pytest
from moto import mock_aws

from handlers.handle_failure import handle_failure
from handlers.parse_message import parse_message
from handlers.publish_handoff import publish_handoff
from handlers.validate_format import handler as validate_format_handler
from models.audio_chunk import AudioChunk
from models.embedding_result import EmbeddingResult
from services.chunking import chunk_audio
from services.vector_store import store_vectors


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def aws_environment():
    """Set up mocked AWS environment for integration tests.

    Creates:
    - DynamoDB table with a test submission (status=Pending)
    - SSM parameters under /prescoach/dev/preparation-workflow/
    - SQS queues (input, handoff FIFO, DLQ input, DLQ handoff)
    - SNS topic
    - S3 bucket with a test audio file
    """
    with mock_aws():
        region = "us-east-1"

        # DynamoDB table with test submission
        dynamodb = boto3.client("dynamodb", region_name=region)
        dynamodb.create_table(
            TableName="submissions",
            KeySchema=[{"AttributeName": "submission_id", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "submission_id", "AttributeType": "S"}
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        dynamodb.put_item(
            TableName="submissions",
            Item={
                "submission_id": {"S": "sub-001"},
                "user_id": {"S": "user-001"},
                "processing_status": {"S": "Pending"},
            },
        )

        # SSM parameters
        ssm = boto3.client("ssm", region_name=region)
        params = {
            "embedding-model-id": "amazon.titan-embed-image-v1",
            "chunk-size-seconds": "30",
            "chunk-overlap-seconds": "5",
            "max-retry-attempts": "3",
            "video-processing-enabled": "false",
            "vector-store-endpoint": "test-vectors-bucket",
            "vector-store-type": "s3",
            "batch-size": "5",
            "batch-processing-enabled": "false",
        }
        for name, value in params.items():
            ssm.put_parameter(
                Name=f"/prescoach/dev/preparation-workflow/{name}",
                Value=value,
                Type="String",
            )

        # SQS queues
        sqs = boto3.client("sqs", region_name=region)
        input_queue = sqs.create_queue(QueueName="preparation-input")
        handoff_queue = sqs.create_queue(
            QueueName="handoff-queue.fifo",
            Attributes={
                "FifoQueue": "true",
                "ContentBasedDeduplication": "false",
            },
        )
        dlq_input = sqs.create_queue(QueueName="dlq-input")
        dlq_handoff = sqs.create_queue(
            QueueName="dlq-handoff.fifo",
            Attributes={
                "FifoQueue": "true",
                "ContentBasedDeduplication": "false",
            },
        )

        # SNS topic
        sns = boto3.client("sns", region_name=region)
        topic = sns.create_topic(Name="error-notifications")

        # S3 bucket with test file
        s3 = boto3.client("s3", region_name=region)
        s3.create_bucket(Bucket="uploads-bucket")
        s3.put_object(
            Bucket="uploads-bucket",
            Key="uploads/user-001/sub-001/presentation.mp3",
            Body=b"fake-audio-content",
        )
        # Create vector store bucket
        s3.create_bucket(Bucket="test-vectors-bucket")

        yield {
            "region": region,
            "dynamodb_table_name": "submissions",
            "input_queue_url": input_queue["QueueUrl"],
            "handoff_queue_url": handoff_queue["QueueUrl"],
            "dlq_input_url": dlq_input["QueueUrl"],
            "dlq_handoff_url": dlq_handoff["QueueUrl"],
            "sns_topic_arn": topic["TopicArn"],
            "s3_bucket": "uploads-bucket",
            "vector_store_bucket": "test-vectors-bucket",
        }


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _build_sqs_message(
    submission_id="sub-001",
    user_id="user-001",
    s3_bucket="uploads-bucket",
    s3_file_key="uploads/user-001/sub-001/presentation.mp3",
    original_file_name="presentation.mp3",
    presentation_title="My Presentation",
):
    """Build a valid SQS message body matching InputMessage schema."""
    return json.dumps(
        {
            "submission_id": submission_id,
            "user_id": user_id,
            "s3_bucket": s3_bucket,
            "s3_file_key": s3_file_key,
            "original_file_name": original_file_name,
            "presentation_title": presentation_title,
        }
    )


def _update_status_processing(dynamodb_table_name, submission_id, region="us-east-1"):
    """Simulate the UpdateStatusProcessing state."""
    dynamodb = boto3.client("dynamodb", region_name=region)
    dynamodb.update_item(
        TableName=dynamodb_table_name,
        Key={"submission_id": {"S": submission_id}},
        UpdateExpression="SET processing_status = :status",
        ExpressionAttributeValues={":status": {"S": "Processing"}},
    )


def _update_status_completed(dynamodb_table_name, submission_id, region="us-east-1"):
    """Simulate the UpdateStatusCompleted state."""
    dynamodb = boto3.client("dynamodb", region_name=region)
    dynamodb.update_item(
        TableName=dynamodb_table_name,
        Key={"submission_id": {"S": submission_id}},
        UpdateExpression="SET processing_status = :status",
        ExpressionAttributeValues={":status": {"S": "Completed"}},
    )


def _get_submission_status(dynamodb_table_name, submission_id, region="us-east-1"):
    """Get the current processing status from DynamoDB."""
    dynamodb = boto3.client("dynamodb", region_name=region)
    item = dynamodb.get_item(
        TableName=dynamodb_table_name,
        Key={"submission_id": {"S": submission_id}},
    )
    return item["Item"]["processing_status"]["S"]


# ---------------------------------------------------------------------------
# Test: Successful Audio Processing Flow
# ---------------------------------------------------------------------------


class TestSuccessfulAudioProcessingFlow:
    """End-to-end test of the audio processing happy path.

    Validates: Requirements 1.1, 1.3, 2.1, 4.1, 7.1, 8.5
    Flow: SQS → parse → validate → chunk → embed → store → handoff → Completed
    """

    def test_successful_audio_processing_flow(self, aws_environment):
        """Full audio processing chain produces Completed status and handoff message."""
        env = aws_environment

        # Step 1: Parse message
        message_body = _build_sqs_message()
        parse_result = parse_message(message_body)
        assert parse_result["valid"] is True
        msg = parse_result["message"]

        # Step 2: Update status to Processing
        _update_status_processing(env["dynamodb_table_name"], msg["submission_id"])
        assert (
            _get_submission_status(env["dynamodb_table_name"], msg["submission_id"])
            == "Processing"
        )

        # Step 3: Validate format (audio file, video disabled)
        validate_result = validate_format_handler(
            {
                "original_file_name": msg["original_file_name"],
                "video_processing_enabled": False,
            },
            None,
        )
        assert validate_result["valid"] is True
        assert validate_result["decision"] == "embed"
        assert validate_result["file_type"] == "audio"

        # Step 4: Chunk audio (simulate with known duration)
        audio_chunks = chunk_audio(
            s3_bucket=env["s3_bucket"],
            s3_audio_key=msg["s3_file_key"],
            submission_id=msg["submission_id"],
            user_id=msg["user_id"],
            chunk_size_seconds=30,
            chunk_overlap_seconds=5,
            total_duration_seconds=60.0,
        )
        assert len(audio_chunks) > 0

        # Step 5: Create embeddings (simulated — build results directly)
        embedding_results = []
        for chunk in audio_chunks:
            result = EmbeddingResult(
                submission_id=chunk.submission_id,
                user_id=chunk.user_id,
                chunk_index=chunk.chunk_index,
                chunk_timestamp_start=chunk.timestamp_start_seconds,
                chunk_timestamp_end=chunk.timestamp_end_seconds,
                embedding_vector=[0.1, 0.2, 0.3] * 128,  # 384-dim vector
                embedding_model_version="amazon.titan-embed-image-v1",
            )
            embedding_results.append(result)

        # Step 6: Store vectors
        store_result = store_vectors(
            embedding_results=embedding_results,
            vector_store_endpoint=env["vector_store_bucket"],
            vector_store_type="s3",
        )
        assert store_result["stored_count"] == len(embedding_results)
        assert "s3://" in store_result["vector_store_location"]

        # Step 7: Publish handoff
        handoff_result = publish_handoff(
            submission_id=msg["submission_id"],
            user_id=msg["user_id"],
            s3_file_key=msg["s3_file_key"],
            vector_store_location=store_result["vector_store_location"],
            chunk_count=len(audio_chunks),
            presentation_title=msg["presentation_title"],
            queue_url=env["handoff_queue_url"],
        )
        assert "message_id" in handoff_result

        # Step 8: Update status to Completed
        _update_status_completed(env["dynamodb_table_name"], msg["submission_id"])

        # Final verification: DynamoDB status is Completed
        final_status = _get_submission_status(
            env["dynamodb_table_name"], msg["submission_id"]
        )
        assert final_status == "Completed"

        # Verify handoff message is on the queue
        sqs = boto3.client("sqs", region_name=env["region"])
        messages = sqs.receive_message(
            QueueUrl=env["handoff_queue_url"],
            MaxNumberOfMessages=1,
        )
        assert len(messages["Messages"]) == 1
        handoff_body = json.loads(messages["Messages"][0]["Body"])
        assert handoff_body["submission_id"] == "sub-001"
        assert handoff_body["chunk_count"] == len(audio_chunks)


# ---------------------------------------------------------------------------
# Test: Invalid Format Rejection
# ---------------------------------------------------------------------------


class TestInvalidFormatRejection:
    """Test that invalid file formats are rejected and routed to DLQ.

    Validates: Requirements 2.1, 2.2, 6.1, 6.2
    """

    def test_invalid_format_rejection(self, aws_environment):
        """An .exe file is rejected, DynamoDB updated to Failed, message routed to DLQ."""
        env = aws_environment

        # Step 1: Parse message with .exe file
        message_body = _build_sqs_message(
            original_file_name="malware.exe",
            s3_file_key="uploads/user-001/sub-001/malware.exe",
        )
        parse_result = parse_message(message_body)
        assert parse_result["valid"] is True
        msg = parse_result["message"]

        # Step 2: Update status to Processing
        _update_status_processing(env["dynamodb_table_name"], msg["submission_id"])

        # Step 3: Validate format — should fail
        validate_result = validate_format_handler(
            {
                "original_file_name": msg["original_file_name"],
                "video_processing_enabled": False,
            },
            None,
        )
        assert validate_result["valid"] is False
        assert validate_result["decision"] == "fail"

        # Step 4: Handle failure — updates DynamoDB, publishes SNS, routes to DLQ
        failure_result = handle_failure(
            submission_id=msg["submission_id"],
            step_name="ValidateFileFormat",
            error_type="ValidationError",
            error_message=validate_result["reason"],
            retry_count_exhausted=0,
            original_message=message_body,
            failure_source="input",
            dynamodb_table_name=env["dynamodb_table_name"],
            sns_topic_arn=env["sns_topic_arn"],
            dlq_input_url=env["dlq_input_url"],
            dlq_handoff_url=env["dlq_handoff_url"],
        )

        assert failure_result["dynamodb_updated"] is True
        assert failure_result["sns_published"] is True
        assert failure_result["dlq_routed"] is True
        assert failure_result["dlq_used"] == "input"

        # Verify DynamoDB status is Failed
        status = _get_submission_status(
            env["dynamodb_table_name"], msg["submission_id"]
        )
        assert status == "Failed"

        # Verify message is on the DLQ
        sqs = boto3.client("sqs", region_name=env["region"])
        dlq_messages = sqs.receive_message(
            QueueUrl=env["dlq_input_url"], MaxNumberOfMessages=1
        )
        assert len(dlq_messages["Messages"]) == 1
        assert json.loads(dlq_messages["Messages"][0]["Body"])["submission_id"] == "sub-001"


# ---------------------------------------------------------------------------
# Test: Video Disabled Rejection
# ---------------------------------------------------------------------------


class TestVideoDisabledRejection:
    """Test that video files are rejected when the feature flag is disabled.

    Validates: Requirements 2.3, 2.4
    """

    def test_video_disabled_rejection(self, aws_environment):
        """An .mp4 file is rejected when video processing is disabled."""
        env = aws_environment

        # Step 1: Parse message with .mp4 file
        message_body = _build_sqs_message(
            original_file_name="recording.mp4",
            s3_file_key="uploads/user-001/sub-001/recording.mp4",
        )
        parse_result = parse_message(message_body)
        assert parse_result["valid"] is True
        msg = parse_result["message"]

        # Step 2: Update status to Processing
        _update_status_processing(env["dynamodb_table_name"], msg["submission_id"])

        # Step 3: Validate format with video_processing_enabled=False
        validate_result = validate_format_handler(
            {
                "original_file_name": msg["original_file_name"],
                "video_processing_enabled": False,
            },
            None,
        )
        assert validate_result["valid"] is True  # format is valid (it's .mp4)
        assert validate_result["decision"] == "fail"
        assert "video" in validate_result["reason"].lower()

        # Step 4: Handle failure — updates DynamoDB with reason
        failure_result = handle_failure(
            submission_id=msg["submission_id"],
            step_name="ValidateFileFormat",
            error_type="VideoDisabledError",
            error_message=validate_result["reason"],
            retry_count_exhausted=0,
            original_message=message_body,
            failure_source="input",
            dynamodb_table_name=env["dynamodb_table_name"],
            sns_topic_arn=env["sns_topic_arn"],
            dlq_input_url=env["dlq_input_url"],
            dlq_handoff_url=env["dlq_handoff_url"],
        )

        assert failure_result["dynamodb_updated"] is True

        # Verify DynamoDB status is Failed
        status = _get_submission_status(
            env["dynamodb_table_name"], msg["submission_id"]
        )
        assert status == "Failed"


# ---------------------------------------------------------------------------
# Test: Successful Video Processing Flow (with mocked MediaConvert)
# ---------------------------------------------------------------------------


class TestSuccessfulVideoProcessingFlow:
    """Test video processing when the feature flag is enabled.

    Validates: Requirements 2.4, 3.1, 4.1, 7.1
    The audio extraction step is simulated (MediaConvert would be mocked
    at a higher level in a real Step Function execution).
    """

    def test_successful_video_processing_flow(self, aws_environment):
        """Video file with flag enabled proceeds through extraction to handoff."""
        env = aws_environment

        # Step 1: Parse message with .mp4 file
        message_body = _build_sqs_message(
            original_file_name="recording.mp4",
            s3_file_key="uploads/user-001/sub-001/recording.mp4",
        )
        parse_result = parse_message(message_body)
        assert parse_result["valid"] is True
        msg = parse_result["message"]

        # Step 2: Update status to Processing
        _update_status_processing(env["dynamodb_table_name"], msg["submission_id"])

        # Step 3: Validate format with video_processing_enabled=True
        validate_result = validate_format_handler(
            {
                "original_file_name": msg["original_file_name"],
                "video_processing_enabled": True,
            },
            None,
        )
        assert validate_result["valid"] is True
        assert validate_result["decision"] == "extract_audio"

        # Step 4: Simulate audio extraction (MediaConvert output)
        # In real workflow, MediaConvert extracts audio and places it in S3
        s3 = boto3.client("s3", region_name=env["region"])
        extracted_audio_key = (
            f"processed/{msg['user_id']}/{msg['submission_id']}/audio.mp3"
        )
        s3.put_object(
            Bucket=env["s3_bucket"],
            Key=extracted_audio_key,
            Body=b"extracted-audio-content",
        )

        # Step 5: Chunk extracted audio
        audio_chunks = chunk_audio(
            s3_bucket=env["s3_bucket"],
            s3_audio_key=extracted_audio_key,
            submission_id=msg["submission_id"],
            user_id=msg["user_id"],
            chunk_size_seconds=30,
            chunk_overlap_seconds=5,
            total_duration_seconds=45.0,
        )
        assert len(audio_chunks) > 0

        # Step 6: Create embeddings (simulated)
        embedding_results = []
        for chunk in audio_chunks:
            result = EmbeddingResult(
                submission_id=chunk.submission_id,
                user_id=chunk.user_id,
                chunk_index=chunk.chunk_index,
                chunk_timestamp_start=chunk.timestamp_start_seconds,
                chunk_timestamp_end=chunk.timestamp_end_seconds,
                embedding_vector=[0.5] * 384,
                embedding_model_version="amazon.titan-embed-image-v1",
            )
            embedding_results.append(result)

        # Step 7: Store vectors
        store_result = store_vectors(
            embedding_results=embedding_results,
            vector_store_endpoint=env["vector_store_bucket"],
            vector_store_type="s3",
        )
        assert store_result["stored_count"] == len(embedding_results)

        # Step 8: Publish handoff
        handoff_result = publish_handoff(
            submission_id=msg["submission_id"],
            user_id=msg["user_id"],
            s3_file_key=extracted_audio_key,
            vector_store_location=store_result["vector_store_location"],
            chunk_count=len(audio_chunks),
            presentation_title=msg["presentation_title"],
            queue_url=env["handoff_queue_url"],
        )
        assert "message_id" in handoff_result

        # Step 9: Update status to Completed
        _update_status_completed(env["dynamodb_table_name"], msg["submission_id"])

        # Verify final state
        final_status = _get_submission_status(
            env["dynamodb_table_name"], msg["submission_id"]
        )
        assert final_status == "Completed"


# ---------------------------------------------------------------------------
# Test: Embedding Failure Routes to DLQ
# ---------------------------------------------------------------------------


class TestEmbeddingFailureRoutesToDLQ:
    """Test that embedding failure after retries routes to DLQ and updates status.

    Validates: Requirements 4.1, 6.1, 6.2
    """

    def test_embedding_failure_routes_to_dlq(self, aws_environment):
        """After embedding fails, status is Failed and message is on DLQ."""
        env = aws_environment

        # Step 1: Parse and validate (audio file — valid)
        message_body = _build_sqs_message()
        parse_result = parse_message(message_body)
        msg = parse_result["message"]

        # Step 2: Update status to Processing
        _update_status_processing(env["dynamodb_table_name"], msg["submission_id"])

        # Step 3: Simulate embedding failure after retries
        # (In reality, Bedrock would throw after max retries)
        failure_result = handle_failure(
            submission_id=msg["submission_id"],
            step_name="CreateEmbeddings",
            error_type="BedrockServiceError",
            error_message="Model invocation failed after 3 retries",
            retry_count_exhausted=3,
            original_message=message_body,
            failure_source="input",
            dynamodb_table_name=env["dynamodb_table_name"],
            sns_topic_arn=env["sns_topic_arn"],
            dlq_input_url=env["dlq_input_url"],
            dlq_handoff_url=env["dlq_handoff_url"],
        )

        assert failure_result["dynamodb_updated"] is True
        assert failure_result["sns_published"] is True
        assert failure_result["dlq_routed"] is True
        assert failure_result["dlq_used"] == "input"

        # Verify DynamoDB status
        status = _get_submission_status(
            env["dynamodb_table_name"], msg["submission_id"]
        )
        assert status == "Failed"

        # Verify message on DLQ
        sqs = boto3.client("sqs", region_name=env["region"])
        dlq_messages = sqs.receive_message(
            QueueUrl=env["dlq_input_url"], MaxNumberOfMessages=1
        )
        assert len(dlq_messages["Messages"]) == 1


# ---------------------------------------------------------------------------
# Test: Handoff Publish Failure Routes to DLQ_Handoff
# ---------------------------------------------------------------------------


class TestHandoffPublishFailureRoutesToDLQHandoff:
    """Test that handoff publish failure routes to DLQ_Handoff.

    Validates: Requirements 7.5, 6.2
    """

    def test_handoff_publish_failure_routes_to_dlq_handoff(self, aws_environment):
        """When handoff publish fails, message is routed to DLQ_Handoff."""
        env = aws_environment

        # Steps 1-6: Successful processing up to the point of handoff
        message_body = _build_sqs_message()
        parse_result = parse_message(message_body)
        msg = parse_result["message"]

        _update_status_processing(env["dynamodb_table_name"], msg["submission_id"])

        # Simulate successful embedding and storage
        audio_chunks = chunk_audio(
            s3_bucket=env["s3_bucket"],
            s3_audio_key=msg["s3_file_key"],
            submission_id=msg["submission_id"],
            user_id=msg["user_id"],
            chunk_size_seconds=30,
            chunk_overlap_seconds=5,
            total_duration_seconds=60.0,
        )
        embedding_results = [
            EmbeddingResult(
                submission_id=chunk.submission_id,
                user_id=chunk.user_id,
                chunk_index=chunk.chunk_index,
                chunk_timestamp_start=chunk.timestamp_start_seconds,
                chunk_timestamp_end=chunk.timestamp_end_seconds,
                embedding_vector=[0.1] * 256,
                embedding_model_version="amazon.titan-embed-image-v1",
            )
            for chunk in audio_chunks
        ]
        store_result = store_vectors(
            embedding_results=embedding_results,
            vector_store_endpoint=env["vector_store_bucket"],
            vector_store_type="s3",
        )

        # Step 7: Handoff publish fails → handle_failure with failure_source="handoff"
        failure_result = handle_failure(
            submission_id=msg["submission_id"],
            step_name="PublishHandoff",
            error_type="SQSPublishError",
            error_message="FIFO queue unavailable after 3 retries",
            retry_count_exhausted=3,
            original_message=message_body,
            failure_source="handoff",
            dynamodb_table_name=env["dynamodb_table_name"],
            sns_topic_arn=env["sns_topic_arn"],
            dlq_input_url=env["dlq_input_url"],
            dlq_handoff_url=env["dlq_handoff_url"],
        )

        assert failure_result["dynamodb_updated"] is True
        assert failure_result["sns_published"] is True
        assert failure_result["dlq_routed"] is True
        assert failure_result["dlq_used"] == "handoff"

        # Verify DynamoDB status is Failed
        status = _get_submission_status(
            env["dynamodb_table_name"], msg["submission_id"]
        )
        assert status == "Failed"

        # Verify message is on DLQ_Handoff (FIFO)
        sqs = boto3.client("sqs", region_name=env["region"])
        dlq_messages = sqs.receive_message(
            QueueUrl=env["dlq_handoff_url"], MaxNumberOfMessages=1
        )
        assert len(dlq_messages["Messages"]) == 1
        assert (
            json.loads(dlq_messages["Messages"][0]["Body"])["submission_id"]
            == "sub-001"
        )
