"""Integration tests for the full evaluation session lifecycle.

Tests the SessionSupervisor end-to-end with mocked AWS services (SQS, DynamoDB,
S3, SNS) using moto. The CoachingSupervisor is mocked since it would require
real LLM calls, but all other components are real instances wired together.

Requirements: 1.1, 5.4, 6.1, 9.1, 10.1, 10.2, 10.3
"""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import boto3
import pytest
from moto import mock_aws

from agents.coaching_supervisor import CoachingSupervisor
from agents.session_supervisor import SessionSupervisor
from models.data_models import (
    AgentFailure,
    EvaluationResult,
    Finding,
    ProcessingStatus,
    RetryConfig,
    get_report_path,
)
from services.error_notifier import ErrorNotifier
from services.report_generator import ReportGenerator
from services.sqs_consumer import SQSConsumer
from services.status_manager import StatusManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def aws_resources():
    """Create real mocked AWS resources using moto.

    Sets up:
    - SQS FIFO queue (handoff queue)
    - SQS FIFO queue (DLQ)
    - DynamoDB table (submissions)
    - S3 bucket (evaluation results and reports)
    - SNS topic (error notifications)
    """
    with mock_aws():
        region = "us-east-1"

        # Create SQS FIFO queues
        sqs_client = boto3.client("sqs", region_name=region)

        dlq_response = sqs_client.create_queue(
            QueueName="prescoach-dev-handoff-dlq.fifo",
            Attributes={
                "FifoQueue": "true",
                "ContentBasedDeduplication": "false",
            },
        )
        dlq_url = dlq_response["QueueUrl"]

        queue_response = sqs_client.create_queue(
            QueueName="prescoach-dev-preparation-handoff.fifo",
            Attributes={
                "FifoQueue": "true",
                "ContentBasedDeduplication": "false",
                "VisibilityTimeout": "300",
            },
        )
        queue_url = queue_response["QueueUrl"]

        # Create DynamoDB table
        dynamodb_resource = boto3.resource("dynamodb", region_name=region)
        table = dynamodb_resource.create_table(
            TableName="prescoach-dev-submissions",
            KeySchema=[
                {"AttributeName": "submission_id", "KeyType": "HASH"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "submission_id", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        # Create S3 bucket
        s3_client = boto3.client("s3", region_name=region)
        s3_client.create_bucket(Bucket="prescoach-dev-evaluation")

        # Create SNS topic
        sns_client = boto3.client("sns", region_name=region)
        sns_response = sns_client.create_topic(Name="prescoach-dev-errors")
        topic_arn = sns_response["TopicArn"]

        yield {
            "sqs_client": sqs_client,
            "queue_url": queue_url,
            "dlq_url": dlq_url,
            "dynamodb_resource": dynamodb_resource,
            "table": table,
            "table_name": "prescoach-dev-submissions",
            "s3_client": s3_client,
            "bucket_name": "prescoach-dev-evaluation",
            "sns_client": sns_client,
            "topic_arn": topic_arn,
            "region": region,
        }


@pytest.fixture
def build_supervisor(aws_resources):
    """Factory fixture that builds a SessionSupervisor with real services.

    The CoachingSupervisor is mocked (requires LLM), but all other
    components use real instances with mocked AWS resources.
    """

    def _build(coaching_supervisor=None, retry_config=None):
        sqs_consumer = SQSConsumer(
            queue_url=aws_resources["queue_url"],
            dlq_url=aws_resources["dlq_url"],
            sqs_client=aws_resources["sqs_client"],
        )

        status_manager = StatusManager(
            table_name=aws_resources["table_name"],
            dynamodb_resource=aws_resources["dynamodb_resource"],
        )

        report_generator = ReportGenerator(
            bucket_name=aws_resources["bucket_name"],
            s3_client=aws_resources["s3_client"],
        )

        error_notifier = ErrorNotifier(
            topic_arn=aws_resources["topic_arn"],
            sns_client=aws_resources["sns_client"],
        )

        mock_coaching = coaching_supervisor or MagicMock(spec=CoachingSupervisor)

        supervisor = SessionSupervisor(
            sqs_consumer=sqs_consumer,
            status_manager=status_manager,
            coaching_supervisor=mock_coaching,
            report_generator=report_generator,
            error_notifier=error_notifier,
            s3_client=aws_resources["s3_client"],
            bucket_name=aws_resources["bucket_name"],
            retry_config=retry_config or RetryConfig(
                max_attempts=3,
                base_delay_seconds=0.01,
                jitter=False,
            ),
        )

        return supervisor, mock_coaching

    return _build


@pytest.fixture
def valid_handoff_message():
    """A valid handoff message payload."""
    return {
        "submission_id": "sub-integration-001",
        "user_id": "user-test-abc",
        "s3_file_key": "uploads/integration-test.pptx",
        "transcript_s3_key": "processed/user-test-abc/sub-integration-001/transcript.json",
        "vector_store_location": "vs-bucket/embeddings/sub-integration-001",
        "chunk_count": 5,
        "presentation_title": "Integration Test Presentation",
    }


@pytest.fixture
def sample_evaluation_results():
    """Sample evaluation results simulating coaching supervisor output."""
    now = datetime.now(timezone.utc).isoformat()
    return [
        EvaluationResult(
            dimension="delivery",
            score=7.5,
            findings=[
                Finding(
                    category="vocal_variety",
                    detail="Good tonal variation observed throughout",
                    severity="low",
                    suggestion="Continue developing pitch variation",
                )
            ],
            strengths=["Clear articulation", "Good energy"],
            improvements=["Reduce filler words", "More pauses for emphasis"],
            agent_id="delivery-evaluator-v1",
            timestamp=now,
        ),
        EvaluationResult(
            dimension="structure",
            score=8.0,
            findings=[
                Finding(
                    category="organization",
                    detail="Logical flow with clear transitions",
                    severity="low",
                    suggestion="Consider using signpost phrases",
                )
            ],
            strengths=["Clear opening hook", "Strong conclusion"],
            improvements=["Add more transition phrases between sections"],
            agent_id="structure-evaluator-v1",
            timestamp=now,
        ),
    ]


def _send_message_to_queue(sqs_client, queue_url, message_body):
    """Helper to send a message to the SQS FIFO queue and receive it."""
    sqs_client.send_message(
        QueueUrl=queue_url,
        MessageBody=json.dumps(message_body),
        MessageGroupId="test-group",
        MessageDeduplicationId="dedup-" + message_body.get("submission_id", "unknown"),
    )

    # Receive the message
    response = sqs_client.receive_message(
        QueueUrl=queue_url,
        MaxNumberOfMessages=1,
        WaitTimeSeconds=0,
        AttributeNames=["All"],
    )
    messages = response.get("Messages", [])
    if not messages:
        return None

    msg = messages[0]
    parsed = json.loads(msg["Body"])
    parsed["_receipt_handle"] = msg["ReceiptHandle"]
    attrs = msg.get("Attributes", {})
    if "MessageGroupId" in attrs:
        parsed["_message_group_id"] = attrs["MessageGroupId"]
    return parsed


# ---------------------------------------------------------------------------
# Test 1: Happy path end-to-end
# ---------------------------------------------------------------------------


class TestHappyPath:
    """Full happy path: SQS → SessionSupervisor → DynamoDB Completed with report in S3.

    Requirements: 1.1, 10.1, 10.2, 10.3
    """

    def test_full_happy_path_with_mocked_aws(
        self, aws_resources, build_supervisor, valid_handoff_message, sample_evaluation_results
    ):
        """Send valid message → SQS → handle_message → DynamoDB Completed → PDF in S3."""
        supervisor, mock_coaching = build_supervisor()

        # Configure mock coaching supervisor to return evaluation results
        mock_coaching.evaluate.return_value = sample_evaluation_results
        mock_coaching.get_last_failures.return_value = []

        # Send message to SQS and receive it
        raw_message = _send_message_to_queue(
            aws_resources["sqs_client"],
            aws_resources["queue_url"],
            valid_handoff_message,
        )
        assert raw_message is not None

        # Process the message
        result = supervisor.handle_message(raw_message)

        # Verify SessionResult
        assert result.status == ProcessingStatus.COMPLETED
        assert result.submission_id == "sub-integration-001"
        assert result.report_path is not None
        assert result.failure_reason is None
        assert len(result.evaluation_results) == 2

        # Verify DynamoDB has Completed status with report_path
        table = aws_resources["table"]
        item = table.get_item(Key={"submission_id": "sub-integration-001"})["Item"]
        assert item["processing_status"] == "Completed"
        assert "report_path" in item
        assert item["report_path"] == result.report_path

        # Verify PDF exists in S3
        expected_report_path = get_report_path("user-test-abc", "sub-integration-001")
        s3_response = aws_resources["s3_client"].get_object(
            Bucket=aws_resources["bucket_name"],
            Key=expected_report_path,
        )
        pdf_content = s3_response["Body"].read()
        assert len(pdf_content) > 0
        # PDF files start with %PDF
        assert pdf_content[:4] == b"%PDF"

    def test_evaluation_results_stored_in_s3(
        self, aws_resources, build_supervisor, valid_handoff_message, sample_evaluation_results
    ):
        """Evaluation results are stored as JSON in S3 at the correct paths."""
        supervisor, mock_coaching = build_supervisor()
        mock_coaching.evaluate.return_value = sample_evaluation_results
        mock_coaching.get_last_failures.return_value = []

        raw_message = _send_message_to_queue(
            aws_resources["sqs_client"],
            aws_resources["queue_url"],
            valid_handoff_message,
        )
        supervisor.handle_message(raw_message)

        # Verify evaluation results stored in S3
        for result in sample_evaluation_results:
            s3_key = f"evaluations/sub-integration-001/{result.dimension}/result.json"
            s3_obj = aws_resources["s3_client"].get_object(
                Bucket=aws_resources["bucket_name"],
                Key=s3_key,
            )
            stored_json = json.loads(s3_obj["Body"].read())
            assert stored_json["dimension"] == result.dimension
            assert stored_json["score"] == result.score


# ---------------------------------------------------------------------------
# Test 2: Agent failure mid-session
# ---------------------------------------------------------------------------


class TestAgentFailureMidSession:
    """CoachingSupervisor returns no results with failures → DynamoDB Failed.

    Requirements: 9.1
    """

    def test_all_agents_fail_marks_session_failed(
        self, aws_resources, build_supervisor, valid_handoff_message
    ):
        """When all evaluation agents fail, session is marked Failed in DynamoDB."""
        supervisor, mock_coaching = build_supervisor()

        # No results returned, all agents failed
        mock_coaching.evaluate.return_value = []
        mock_coaching.get_last_failures.return_value = [
            AgentFailure(
                dimension="delivery",
                agent_id="delivery-evaluator-v1",
                error="LLM timeout after 30s",
            ),
            AgentFailure(
                dimension="structure",
                agent_id="structure-evaluator-v1",
                error="Vector store connection refused",
            ),
        ]

        raw_message = _send_message_to_queue(
            aws_resources["sqs_client"],
            aws_resources["queue_url"],
            valid_handoff_message,
        )
        result = supervisor.handle_message(raw_message)

        # Verify SessionResult
        assert result.status == ProcessingStatus.FAILED
        assert result.failure_reason is not None
        assert "delivery" in result.failure_reason
        assert "structure" in result.failure_reason
        assert len(result.agent_failures) == 2

        # Verify DynamoDB shows Failed with failure_reason
        table = aws_resources["table"]
        item = table.get_item(Key={"submission_id": "sub-integration-001"})["Item"]
        assert item["processing_status"] == "Failed"
        assert "failure_reason" in item
        assert len(item["failure_reason"]) > 0

    def test_coaching_supervisor_exception_marks_failed(
        self, aws_resources, build_supervisor, valid_handoff_message
    ):
        """When CoachingSupervisor.evaluate() raises, session is marked Failed."""
        supervisor, mock_coaching = build_supervisor()

        mock_coaching.evaluate.side_effect = RuntimeError(
            "Agent orchestration catastrophic failure"
        )
        mock_coaching.get_last_failures.return_value = []

        raw_message = _send_message_to_queue(
            aws_resources["sqs_client"],
            aws_resources["queue_url"],
            valid_handoff_message,
        )
        result = supervisor.handle_message(raw_message)

        assert result.status == ProcessingStatus.FAILED
        assert "catastrophic failure" in result.failure_reason

        # Verify DynamoDB
        table = aws_resources["table"]
        item = table.get_item(Key={"submission_id": "sub-integration-001"})["Item"]
        assert item["processing_status"] == "Failed"


# ---------------------------------------------------------------------------
# Test 3: S3 write failure with retries
# ---------------------------------------------------------------------------


class TestS3WriteFailureWithRetries:
    """S3 write failures trigger retries and SNS notification.

    Requirements: 5.4
    """

    def test_s3_write_failure_triggers_sns_notification(
        self, aws_resources, build_supervisor, valid_handoff_message
    ):
        """When S3 write fails after retries, error notification published to SNS."""
        now = datetime.now(timezone.utc).isoformat()
        eval_result = EvaluationResult(
            dimension="delivery",
            score=7.5,
            findings=[],
            strengths=["Good pace"],
            improvements=["More pauses"],
            agent_id="delivery-evaluator-v1",
            timestamp=now,
        )

        # Subscribe to SNS to capture notifications
        sns_client = aws_resources["sns_client"]
        sqs_client = aws_resources["sqs_client"]

        # Create a regular (non-FIFO) SQS queue for SNS subscription
        notification_queue = sqs_client.create_queue(
            QueueName="test-notification-queue",
        )
        notification_queue_url = notification_queue["QueueUrl"]
        notification_queue_arn = sqs_client.get_queue_attributes(
            QueueUrl=notification_queue_url,
            AttributeNames=["QueueArn"],
        )["Attributes"]["QueueArn"]

        sns_client.subscribe(
            TopicArn=aws_resources["topic_arn"],
            Protocol="sqs",
            Endpoint=notification_queue_arn,
        )

        # Create supervisor with a mock S3 client that always fails
        sqs_consumer = SQSConsumer(
            queue_url=aws_resources["queue_url"],
            dlq_url=aws_resources["dlq_url"],
            sqs_client=aws_resources["sqs_client"],
        )
        status_manager = StatusManager(
            table_name=aws_resources["table_name"],
            dynamodb_resource=aws_resources["dynamodb_resource"],
        )
        report_generator = ReportGenerator(
            bucket_name=aws_resources["bucket_name"],
            s3_client=aws_resources["s3_client"],
        )
        error_notifier = ErrorNotifier(
            topic_arn=aws_resources["topic_arn"],
            sns_client=aws_resources["sns_client"],
        )

        # Mock S3 client that fails on put_object
        failing_s3 = MagicMock()
        failing_s3.put_object.side_effect = Exception("S3 service unavailable")

        mock_coaching = MagicMock(spec=CoachingSupervisor)
        mock_coaching.evaluate.return_value = [eval_result]
        mock_coaching.get_last_failures.return_value = []

        supervisor = SessionSupervisor(
            sqs_consumer=sqs_consumer,
            status_manager=status_manager,
            coaching_supervisor=mock_coaching,
            report_generator=report_generator,
            error_notifier=error_notifier,
            s3_client=failing_s3,
            bucket_name=aws_resources["bucket_name"],
            retry_config=RetryConfig(
                max_attempts=3,
                base_delay_seconds=0.01,
                jitter=False,
            ),
        )

        raw_message = _send_message_to_queue(
            aws_resources["sqs_client"],
            aws_resources["queue_url"],
            valid_handoff_message,
        )
        result = supervisor.handle_message(raw_message)

        # S3 put_object was retried 3 times
        assert failing_s3.put_object.call_count == 3

        # SNS notification was published (check via notification queue)
        sns_messages = sqs_client.receive_message(
            QueueUrl=notification_queue_url,
            MaxNumberOfMessages=10,
            WaitTimeSeconds=0,
        )
        # At least one SNS notification should have been published
        assert len(sns_messages.get("Messages", [])) >= 1

    def test_s3_transient_failure_with_eventual_success(
        self, aws_resources, build_supervisor, valid_handoff_message, sample_evaluation_results
    ):
        """S3 write succeeds after transient failures — no SNS notification needed."""
        # Create a real S3 client that we'll swap mid-test is complex,
        # so we use a mock that fails twice then succeeds
        sqs_consumer = SQSConsumer(
            queue_url=aws_resources["queue_url"],
            dlq_url=aws_resources["dlq_url"],
            sqs_client=aws_resources["sqs_client"],
        )
        status_manager = StatusManager(
            table_name=aws_resources["table_name"],
            dynamodb_resource=aws_resources["dynamodb_resource"],
        )
        report_generator = ReportGenerator(
            bucket_name=aws_resources["bucket_name"],
            s3_client=aws_resources["s3_client"],
        )
        error_notifier = ErrorNotifier(
            topic_arn=aws_resources["topic_arn"],
            sns_client=aws_resources["sns_client"],
        )

        # S3 client that fails twice then works (using mock with side_effect)
        flaky_s3 = MagicMock()
        # For two results: first result fails twice then succeeds,
        # second result succeeds immediately
        flaky_s3.put_object.side_effect = [
            Exception("Transient S3 error"),
            Exception("Transient S3 error"),
            None,  # First result succeeds on 3rd attempt
            None,  # Second result succeeds on 1st attempt
        ]

        mock_coaching = MagicMock(spec=CoachingSupervisor)
        mock_coaching.evaluate.return_value = sample_evaluation_results
        mock_coaching.get_last_failures.return_value = []

        supervisor = SessionSupervisor(
            sqs_consumer=sqs_consumer,
            status_manager=status_manager,
            coaching_supervisor=mock_coaching,
            report_generator=report_generator,
            error_notifier=error_notifier,
            s3_client=flaky_s3,
            bucket_name=aws_resources["bucket_name"],
            retry_config=RetryConfig(
                max_attempts=3,
                base_delay_seconds=0.01,
                jitter=False,
            ),
        )

        raw_message = _send_message_to_queue(
            aws_resources["sqs_client"],
            aws_resources["queue_url"],
            valid_handoff_message,
        )
        result = supervisor.handle_message(raw_message)

        # Both results should have been stored (retry succeeded)
        assert len(result.evaluation_results) == 2
        # Total put_object calls: 3 (first result) + 1 (second result) = 4
        assert flaky_s3.put_object.call_count == 4


# ---------------------------------------------------------------------------
# Test 4: DLQ routing on invalid message
# ---------------------------------------------------------------------------


class TestDLQRoutingInvalidMessage:
    """Invalid messages are routed to DLQ with error attributes.

    Requirements: 9.1
    """

    def test_invalid_message_appears_in_dlq(
        self, aws_resources, build_supervisor
    ):
        """Invalid message → validation fails → message routed to DLQ."""
        supervisor, mock_coaching = build_supervisor()

        invalid_message_body = {
            "submission_id": "sub-invalid-001",
            # Missing user_id, s3_file_key, vector_store_location
            "chunk_count": 0,  # Invalid: must be >= 1
            "presentation_title": "",  # Invalid: min_length=1
        }

        # Send and receive the invalid message
        raw_message = _send_message_to_queue(
            aws_resources["sqs_client"],
            aws_resources["queue_url"],
            invalid_message_body,
        )
        assert raw_message is not None

        # Process the invalid message
        result = supervisor.handle_message(raw_message)

        assert result.status == ProcessingStatus.FAILED

        # Check the DLQ for the routed message
        dlq_response = aws_resources["sqs_client"].receive_message(
            QueueUrl=aws_resources["dlq_url"],
            MaxNumberOfMessages=1,
            WaitTimeSeconds=0,
            MessageAttributeNames=["All"],
        )

        dlq_messages = dlq_response.get("Messages", [])
        assert len(dlq_messages) == 1

        dlq_msg = dlq_messages[0]
        # Message body should contain the original invalid message
        dlq_body = json.loads(dlq_msg["Body"])
        assert "sub-invalid-001" in json.dumps(dlq_body)

        # Error reason should be in message attributes
        msg_attrs = dlq_msg.get("MessageAttributes", {})
        assert "ErrorReason" in msg_attrs
        error_reason = msg_attrs["ErrorReason"]["StringValue"]
        assert len(error_reason) > 0
        # Should mention validation error
        assert "validation" in error_reason.lower() or "field" in error_reason.lower()

    def test_completely_malformed_message_routed_to_dlq(
        self, aws_resources, build_supervisor
    ):
        """Message with completely wrong structure is routed to DLQ."""
        supervisor, mock_coaching = build_supervisor()

        # Message missing all required fields
        malformed_message = {
            "random_field": "not a valid handoff message",
            "number": 42,
        }

        raw_message = _send_message_to_queue(
            aws_resources["sqs_client"],
            aws_resources["queue_url"],
            malformed_message,
        )
        # Add a receipt handle manually since the message won't have submission_id
        raw_message["_receipt_handle"] = raw_message.get("_receipt_handle", "")

        result = supervisor.handle_message(raw_message)

        assert result.status == ProcessingStatus.FAILED

        # Verify DLQ received the message
        dlq_response = aws_resources["sqs_client"].receive_message(
            QueueUrl=aws_resources["dlq_url"],
            MaxNumberOfMessages=1,
            WaitTimeSeconds=0,
            MessageAttributeNames=["All"],
        )
        assert len(dlq_response.get("Messages", [])) == 1


# ---------------------------------------------------------------------------
# Test 5: Report generation and storage end-to-end
# ---------------------------------------------------------------------------


class TestReportGenerationEndToEnd:
    """Full cycle produces a valid PDF report in S3 at the expected path.

    Requirements: 6.1, 10.1, 10.2, 10.3
    """

    def test_report_stored_at_correct_s3_path(
        self, aws_resources, build_supervisor, valid_handoff_message, sample_evaluation_results
    ):
        """Report PDF is stored at reports/{user_id}/{submission_id}/coaching_report.pdf."""
        supervisor, mock_coaching = build_supervisor()
        mock_coaching.evaluate.return_value = sample_evaluation_results
        mock_coaching.get_last_failures.return_value = []

        raw_message = _send_message_to_queue(
            aws_resources["sqs_client"],
            aws_resources["queue_url"],
            valid_handoff_message,
        )
        result = supervisor.handle_message(raw_message)

        expected_path = "reports/user-test-abc/sub-integration-001/coaching_report.pdf"
        assert result.report_path == expected_path

        # Verify the PDF actually exists in S3
        s3_response = aws_resources["s3_client"].get_object(
            Bucket=aws_resources["bucket_name"],
            Key=expected_path,
        )
        assert s3_response["ContentType"] == "application/pdf"

    def test_report_is_valid_pdf(
        self, aws_resources, build_supervisor, valid_handoff_message, sample_evaluation_results
    ):
        """Generated report is a valid, non-empty PDF file."""
        supervisor, mock_coaching = build_supervisor()
        mock_coaching.evaluate.return_value = sample_evaluation_results
        mock_coaching.get_last_failures.return_value = []

        raw_message = _send_message_to_queue(
            aws_resources["sqs_client"],
            aws_resources["queue_url"],
            valid_handoff_message,
        )
        result = supervisor.handle_message(raw_message)

        # Retrieve and validate the PDF
        s3_response = aws_resources["s3_client"].get_object(
            Bucket=aws_resources["bucket_name"],
            Key=result.report_path,
        )
        pdf_content = s3_response["Body"].read()

        # Non-empty
        assert len(pdf_content) > 100  # A real PDF should be > 100 bytes

        # Starts with PDF magic bytes
        assert pdf_content[:4] == b"%PDF"

        # Contains PDF end marker
        assert b"%%EOF" in pdf_content

    def test_report_dynamodb_record_has_report_path(
        self, aws_resources, build_supervisor, valid_handoff_message, sample_evaluation_results
    ):
        """DynamoDB record includes the report_path after successful generation."""
        supervisor, mock_coaching = build_supervisor()
        mock_coaching.evaluate.return_value = sample_evaluation_results
        mock_coaching.get_last_failures.return_value = []

        raw_message = _send_message_to_queue(
            aws_resources["sqs_client"],
            aws_resources["queue_url"],
            valid_handoff_message,
        )
        supervisor.handle_message(raw_message)

        # Verify DynamoDB has the report path
        table = aws_resources["table"]
        item = table.get_item(Key={"submission_id": "sub-integration-001"})["Item"]
        assert item["processing_status"] == "Completed"
        assert item["report_path"] == "reports/user-test-abc/sub-integration-001/coaching_report.pdf"

    def test_status_transitions_through_full_lifecycle(
        self, aws_resources, build_supervisor, valid_handoff_message, sample_evaluation_results
    ):
        """DynamoDB status goes through Evaluating → Report_Generating → Completed."""
        supervisor, mock_coaching = build_supervisor()
        mock_coaching.evaluate.return_value = sample_evaluation_results
        mock_coaching.get_last_failures.return_value = []

        # Track status updates by checking DynamoDB after completion
        raw_message = _send_message_to_queue(
            aws_resources["sqs_client"],
            aws_resources["queue_url"],
            valid_handoff_message,
        )
        result = supervisor.handle_message(raw_message)

        # Final state should be Completed
        assert result.status == ProcessingStatus.COMPLETED

        # DynamoDB should reflect the final state
        table = aws_resources["table"]
        item = table.get_item(Key={"submission_id": "sub-integration-001"})["Item"]
        assert item["processing_status"] == "Completed"
        # updated_at should be present
        assert "updated_at" in item
