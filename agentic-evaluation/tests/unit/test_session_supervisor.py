"""Unit tests for Session Supervisor message validation and DLQ routing.

Tests the handle_message() validation flow:
- Valid messages are acknowledged after successful validation
- Invalid messages are routed to DLQ with error notification
- Message acknowledgment occurs at the correct time

Requirements: 1.4, 8.3, 8.4, 9.1, 9.2, 9.3
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from agents.session_supervisor import SessionSupervisor
from models.data_models import EvaluationResult, Finding, ProcessingStatus


@pytest.fixture
def mock_dependencies():
    """Create mocked dependencies for the SessionSupervisor."""
    sqs_consumer = MagicMock()
    status_manager = MagicMock()
    coaching_supervisor = MagicMock()
    report_generator = MagicMock()
    error_notifier = MagicMock()
    s3_client = MagicMock()
    registry = MagicMock()

    return {
        "sqs_consumer": sqs_consumer,
        "status_manager": status_manager,
        "coaching_supervisor": coaching_supervisor,
        "report_generator": report_generator,
        "error_notifier": error_notifier,
        "s3_client": s3_client,
        "registry": registry,
    }


@pytest.fixture
def supervisor(mock_dependencies):
    """Create a SessionSupervisor with mocked dependencies."""
    return SessionSupervisor(
        sqs_consumer=mock_dependencies["sqs_consumer"],
        status_manager=mock_dependencies["status_manager"],
        coaching_supervisor=mock_dependencies["coaching_supervisor"],
        report_generator=mock_dependencies["report_generator"],
        error_notifier=mock_dependencies["error_notifier"],
        s3_client=mock_dependencies["s3_client"],
        bucket_name="test-bucket",
        registry=mock_dependencies["registry"],
    )


@pytest.fixture
def valid_raw_message():
    """A valid raw message as received from SQS."""
    return {
        "submission_id": "sub-12345",
        "user_id": "user-abc",
        "s3_file_key": "uploads/presentation.pptx",
        "transcript_s3_key": "processed/user-abc/sub-12345/transcript.json",
        "vector_store_location": "vs-bucket/embeddings/sub-12345",
        "chunk_count": 10,
        "presentation_title": "Quarterly Business Review",
        "_receipt_handle": "test-receipt-handle-123",
        "_message_group_id": "group-1",
    }


@pytest.fixture
def sample_evaluation_result():
    """A valid EvaluationResult for mocking coaching supervisor responses."""
    return EvaluationResult(
        dimension="delivery",
        score=7.5,
        findings=[
            Finding(
                category="vocal_variety",
                detail="Good tonal variation observed",
                severity="low",
                suggestion="Continue varying pitch",
            )
        ],
        strengths=["Clear articulation"],
        improvements=["Reduce filler words"],
        agent_id="delivery-evaluator-v1",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


class TestMessageValidation:
    """Tests for HandoffMessage validation in handle_message()."""

    def test_valid_message_passes_validation(
        self, supervisor, mock_dependencies, valid_raw_message, sample_evaluation_result
    ):
        """A valid message is accepted without routing to DLQ."""
        # Set up coaching supervisor to return results
        mock_dependencies["coaching_supervisor"].evaluate.return_value = [sample_evaluation_result]
        mock_dependencies["coaching_supervisor"].get_last_failures.return_value = []
        mock_dependencies["report_generator"].generate.return_value = (
            "reports/user-abc/sub-12345/coaching_report.pdf"
        )
        mock_dependencies["registry"].get_available_agents.return_value = []

        result = supervisor.handle_message(valid_raw_message)

        # Should NOT route to DLQ
        mock_dependencies["sqs_consumer"].send_to_dlq.assert_not_called()
        # Should succeed
        assert result.status == ProcessingStatus.COMPLETED

    def test_missing_required_field_fails_validation(
        self, supervisor, mock_dependencies
    ):
        """Message missing submission_id fails validation."""
        invalid_message = {
            # Missing submission_id
            "user_id": "user-abc",
            "s3_file_key": "uploads/file.pptx",
            "vector_store_location": "vs-bucket/embeddings",
            "chunk_count": 5,
            "presentation_title": "Test",
            "_receipt_handle": "receipt-handle-1",
        }

        result = supervisor.handle_message(invalid_message)

        assert result.status == ProcessingStatus.FAILED
        assert "Validation" in result.failure_reason or "validation" in result.failure_reason.lower()

    def test_empty_string_field_fails_validation(
        self, supervisor, mock_dependencies
    ):
        """Message with empty string for a min_length=1 field fails validation."""
        invalid_message = {
            "submission_id": "",  # min_length=1 violated
            "user_id": "user-abc",
            "s3_file_key": "uploads/file.pptx",
            "vector_store_location": "vs-bucket/embeddings",
            "chunk_count": 5,
            "presentation_title": "Test",
            "_receipt_handle": "receipt-handle-2",
        }

        result = supervisor.handle_message(invalid_message)

        assert result.status == ProcessingStatus.FAILED
        assert result.failure_reason is not None

    def test_invalid_chunk_count_fails_validation(
        self, supervisor, mock_dependencies
    ):
        """Message with chunk_count < 1 fails validation."""
        invalid_message = {
            "submission_id": "sub-001",
            "user_id": "user-abc",
            "s3_file_key": "uploads/file.pptx",
            "vector_store_location": "vs-bucket/embeddings",
            "chunk_count": 0,  # ge=1 violated
            "presentation_title": "Test",
            "_receipt_handle": "receipt-handle-3",
        }

        result = supervisor.handle_message(invalid_message)

        assert result.status == ProcessingStatus.FAILED
        assert result.failure_reason is not None

    def test_non_integer_chunk_count_fails_validation(
        self, supervisor, mock_dependencies
    ):
        """Message with non-integer chunk_count fails validation."""
        invalid_message = {
            "submission_id": "sub-001",
            "user_id": "user-abc",
            "s3_file_key": "uploads/file.pptx",
            "vector_store_location": "vs-bucket/embeddings",
            "chunk_count": "not-a-number",
            "presentation_title": "Test",
            "_receipt_handle": "receipt-handle-4",
        }

        result = supervisor.handle_message(invalid_message)

        assert result.status == ProcessingStatus.FAILED

    def test_underscore_prefixed_keys_stripped_before_validation(
        self, supervisor, mock_dependencies, valid_raw_message, sample_evaluation_result
    ):
        """Internal _prefixed keys are stripped and don't cause validation failures."""
        # Add extra _prefixed keys that should be stripped
        valid_raw_message["_sequence_number"] = "12345"
        valid_raw_message["_custom_internal"] = "ignored"

        mock_dependencies["coaching_supervisor"].evaluate.return_value = [sample_evaluation_result]
        mock_dependencies["coaching_supervisor"].get_last_failures.return_value = []
        mock_dependencies["report_generator"].generate.return_value = (
            "reports/user-abc/sub-12345/coaching_report.pdf"
        )
        mock_dependencies["registry"].get_available_agents.return_value = []

        result = supervisor.handle_message(valid_raw_message)

        # Should not fail validation
        mock_dependencies["sqs_consumer"].send_to_dlq.assert_not_called()


class TestDLQRouting:
    """Tests for DLQ routing on validation failure."""

    def test_invalid_message_routed_to_dlq(
        self, supervisor, mock_dependencies
    ):
        """Invalid message body is sent to DLQ via sqs_consumer.send_to_dlq()."""
        invalid_message = {
            "user_id": "user-abc",
            # Missing submission_id, s3_file_key, etc.
            "_receipt_handle": "receipt-handle-dlq",
        }

        supervisor.handle_message(invalid_message)

        mock_dependencies["sqs_consumer"].send_to_dlq.assert_called_once()
        call_args = mock_dependencies["sqs_consumer"].send_to_dlq.call_args
        # First argument is the message body (JSON string)
        message_body = call_args[0][0]
        assert "user-abc" in message_body
        # Second argument is the error reason
        error_reason = call_args[0][1]
        assert len(error_reason) > 0

    def test_invalid_message_acknowledged_after_dlq_routing(
        self, supervisor, mock_dependencies
    ):
        """Invalid message is acknowledged (deleted from queue) after DLQ routing."""
        invalid_message = {
            "submission_id": "",  # Invalid: empty string
            "user_id": "user-abc",
            "s3_file_key": "uploads/file.pptx",
            "vector_store_location": "vs-bucket/embeddings",
            "chunk_count": 5,
            "presentation_title": "Test",
            "_receipt_handle": "receipt-handle-ack",
        }

        supervisor.handle_message(invalid_message)

        # Message should be acknowledged (removed from main queue)
        mock_dependencies["sqs_consumer"].acknowledge.assert_called_once_with(
            "receipt-handle-ack"
        )

    def test_invalid_message_triggers_error_notification(
        self, supervisor, mock_dependencies
    ):
        """Invalid message triggers an error notification via error_notifier.notify()."""
        invalid_message = {
            "submission_id": "sub-bad",
            "user_id": "user-abc",
            # Missing required fields
            "_receipt_handle": "receipt-handle-notify",
        }

        supervisor.handle_message(invalid_message)

        mock_dependencies["error_notifier"].notify.assert_called_once()
        call_kwargs = mock_dependencies["error_notifier"].notify.call_args[1]
        assert call_kwargs["submission_id"] == "sub-bad"
        assert call_kwargs["component_name"] == "SessionSupervisor"
        assert call_kwargs["error_type"] == "ValidationError"
        assert len(call_kwargs["error_message"]) > 0

    def test_invalid_message_returns_failed_session_result(
        self, supervisor, mock_dependencies
    ):
        """Invalid message returns SessionResult with Failed status and reason."""
        invalid_message = {
            "submission_id": "sub-fail",
            "user_id": "user-abc",
            "chunk_count": -1,  # Invalid
            "_receipt_handle": "receipt-handle-fail",
        }

        result = supervisor.handle_message(invalid_message)

        assert result.submission_id == "sub-fail"
        assert result.status == ProcessingStatus.FAILED
        assert result.failure_reason is not None
        assert "Validation" in result.failure_reason or "validation" in result.failure_reason.lower()

    def test_missing_receipt_handle_skips_acknowledgment(
        self, supervisor, mock_dependencies
    ):
        """If _receipt_handle is missing/None, acknowledgment is skipped gracefully."""
        invalid_message = {
            "submission_id": "sub-no-handle",
            # Missing _receipt_handle (simulates edge case)
        }

        result = supervisor.handle_message(invalid_message)

        assert result.status == ProcessingStatus.FAILED
        # acknowledge should not be called since there's no receipt handle
        mock_dependencies["sqs_consumer"].acknowledge.assert_not_called()

    def test_dlq_send_failure_does_not_crash(
        self, supervisor, mock_dependencies
    ):
        """If send_to_dlq raises, the handler still returns a SessionResult."""
        invalid_message = {
            "submission_id": "sub-dlq-fail",
            "_receipt_handle": "receipt-handle-x",
        }
        mock_dependencies["sqs_consumer"].send_to_dlq.side_effect = Exception(
            "DLQ unavailable"
        )

        result = supervisor.handle_message(invalid_message)

        # Should still return a failed result, not crash
        assert result.status == ProcessingStatus.FAILED
        assert result.submission_id == "sub-dlq-fail"


class TestMessageAcknowledgment:
    """Tests for message acknowledgment after successful validation."""

    def test_valid_message_acknowledged_after_validation(
        self, supervisor, mock_dependencies, valid_raw_message, sample_evaluation_result
    ):
        """Valid message is acknowledged via sqs_consumer.acknowledge() after parsing."""
        mock_dependencies["coaching_supervisor"].evaluate.return_value = [sample_evaluation_result]
        mock_dependencies["coaching_supervisor"].get_last_failures.return_value = []
        mock_dependencies["report_generator"].generate.return_value = (
            "reports/user-abc/sub-12345/coaching_report.pdf"
        )
        mock_dependencies["registry"].get_available_agents.return_value = []

        supervisor.handle_message(valid_raw_message)

        mock_dependencies["sqs_consumer"].acknowledge.assert_called_once_with(
            "test-receipt-handle-123"
        )

    def test_acknowledge_failure_does_not_stop_processing(
        self, supervisor, mock_dependencies, valid_raw_message, sample_evaluation_result
    ):
        """If acknowledge raises, processing continues (non-fatal)."""
        mock_dependencies["sqs_consumer"].acknowledge.side_effect = Exception(
            "Network error"
        )
        mock_dependencies["coaching_supervisor"].evaluate.return_value = [sample_evaluation_result]
        mock_dependencies["coaching_supervisor"].get_last_failures.return_value = []
        mock_dependencies["report_generator"].generate.return_value = (
            "reports/user-abc/sub-12345/coaching_report.pdf"
        )
        mock_dependencies["registry"].get_available_agents.return_value = []

        # Should not raise — acknowledge failure is non-fatal
        result = supervisor.handle_message(valid_raw_message)

        # Processing continues to completion
        assert result.status == ProcessingStatus.COMPLETED

    def test_submission_id_unknown_when_not_in_invalid_message(
        self, supervisor, mock_dependencies
    ):
        """When invalid message has no submission_id, result uses 'unknown'."""
        invalid_message = {
            # No submission_id at all
            "_receipt_handle": "receipt-handle-unknown",
        }

        result = supervisor.handle_message(invalid_message)

        assert result.status == ProcessingStatus.FAILED
        assert result.submission_id == "unknown"


class TestEvaluationResultStorage:
    """Tests for evaluation result storage with retry logic.

    Requirements: 5.1, 5.2, 5.4, 5.5
    """

    def test_store_results_success(
        self, supervisor, mock_dependencies, sample_evaluation_result
    ):
        """Successful S3 write stores result and returns it."""
        results = supervisor._store_evaluation_results(
            "sub-001", [sample_evaluation_result]
        )

        assert len(results) == 1
        assert results[0].dimension == "delivery"
        mock_dependencies["s3_client"].put_object.assert_called_once()

    def test_store_results_correct_s3_path(
        self, supervisor, mock_dependencies, sample_evaluation_result
    ):
        """Results are stored at the correct S3 path."""
        supervisor._store_evaluation_results("sub-001", [sample_evaluation_result])

        call_kwargs = mock_dependencies["s3_client"].put_object.call_args[1]
        assert call_kwargs["Bucket"] == "test-bucket"
        assert call_kwargs["Key"] == "evaluations/sub-001/delivery/result.json"
        assert call_kwargs["ContentType"] == "application/json"

    def test_store_results_retries_on_failure(
        self, supervisor, mock_dependencies, sample_evaluation_result
    ):
        """S3 write is retried on transient failure."""
        from models.data_models import RetryConfig

        # Configure supervisor with fast retry for testing
        supervisor._retry_config = RetryConfig(
            max_attempts=3, base_delay_seconds=0.01, jitter=False
        )

        # Fail first two attempts, succeed on third
        mock_dependencies["s3_client"].put_object.side_effect = [
            Exception("Transient S3 error"),
            Exception("Transient S3 error"),
            None,  # Success on third attempt
        ]

        results = supervisor._store_evaluation_results(
            "sub-001", [sample_evaluation_result]
        )

        assert len(results) == 1
        assert mock_dependencies["s3_client"].put_object.call_count == 3
        # No error notification because it eventually succeeded
        mock_dependencies["error_notifier"].notify.assert_not_called()

    def test_store_results_notifies_on_exhausted_retries(
        self, supervisor, mock_dependencies, sample_evaluation_result
    ):
        """SNS notification sent when all retries exhausted."""
        from models.data_models import RetryConfig

        supervisor._retry_config = RetryConfig(
            max_attempts=2, base_delay_seconds=0.01, jitter=False
        )

        # Fail all attempts
        mock_dependencies["s3_client"].put_object.side_effect = Exception(
            "Permanent S3 error"
        )

        results = supervisor._store_evaluation_results(
            "sub-001", [sample_evaluation_result]
        )

        # Result not stored
        assert len(results) == 0
        # Error notification sent
        mock_dependencies["error_notifier"].notify.assert_called_once()
        call_kwargs = mock_dependencies["error_notifier"].notify.call_args[1]
        assert call_kwargs["submission_id"] == "sub-001"
        assert call_kwargs["error_type"] == "S3WriteError"
        assert call_kwargs["retry_count_exhausted"] == 2

    def test_store_results_continues_after_one_failure(
        self, supervisor, mock_dependencies
    ):
        """If one result fails storage, remaining results still stored."""
        from models.data_models import RetryConfig

        supervisor._retry_config = RetryConfig(
            max_attempts=1, base_delay_seconds=0.01, jitter=False
        )

        result1 = EvaluationResult(
            dimension="delivery",
            score=7.0,
            findings=[],
            strengths=["Good pace"],
            improvements=["Use pauses"],
            agent_id="delivery-v1",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        result2 = EvaluationResult(
            dimension="structure",
            score=8.0,
            findings=[],
            strengths=["Clear outline"],
            improvements=["Add transitions"],
            agent_id="structure-v1",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        # First put fails, second succeeds
        mock_dependencies["s3_client"].put_object.side_effect = [
            Exception("S3 error"),
            None,  # Success
        ]

        results = supervisor._store_evaluation_results("sub-001", [result1, result2])

        # Only second result stored successfully
        assert len(results) == 1
        assert results[0].dimension == "structure"
        # Error notification sent for first failure
        mock_dependencies["error_notifier"].notify.assert_called_once()


class TestCompletenessVerification:
    """Tests for verify_completeness() method.

    Requirements: 5.3
    """

    def test_completeness_all_dimensions_present(
        self, supervisor, mock_dependencies
    ):
        """Returns True when all expected dimensions have files in S3."""
        # head_object succeeds for all dimensions
        mock_dependencies["s3_client"].head_object.return_value = {}

        result = supervisor.verify_completeness(
            "sub-001", ["delivery", "structure", "pacing"]
        )

        assert result is True
        assert mock_dependencies["s3_client"].head_object.call_count == 3

    def test_completeness_missing_dimension(
        self, supervisor, mock_dependencies
    ):
        """Returns False when a dimension file is missing from S3."""
        # First call succeeds, second raises (object not found)
        mock_dependencies["s3_client"].head_object.side_effect = [
            {},  # delivery found
            Exception("Not Found"),  # structure missing
        ]

        result = supervisor.verify_completeness(
            "sub-001", ["delivery", "structure"]
        )

        assert result is False

    def test_completeness_empty_dimensions_returns_true(
        self, supervisor, mock_dependencies
    ):
        """Empty expected_dimensions list returns True immediately."""
        result = supervisor.verify_completeness("sub-001", [])

        assert result is True
        mock_dependencies["s3_client"].head_object.assert_not_called()

    def test_completeness_checks_correct_paths(
        self, supervisor, mock_dependencies
    ):
        """Verification checks the correct S3 paths for each dimension."""
        mock_dependencies["s3_client"].head_object.return_value = {}

        supervisor.verify_completeness("sub-xyz", ["delivery", "pacing"])

        calls = mock_dependencies["s3_client"].head_object.call_args_list
        assert calls[0][1] == {
            "Bucket": "test-bucket",
            "Key": "evaluations/sub-xyz/delivery/result.json",
        }
        assert calls[1][1] == {
            "Bucket": "test-bucket",
            "Key": "evaluations/sub-xyz/pacing/result.json",
        }

    def test_completeness_single_dimension(
        self, supervisor, mock_dependencies
    ):
        """Works correctly with a single expected dimension."""
        mock_dependencies["s3_client"].head_object.return_value = {}

        result = supervisor.verify_completeness("sub-001", ["executive_presence"])

        assert result is True
        mock_dependencies["s3_client"].head_object.assert_called_once_with(
            Bucket="test-bucket",
            Key="evaluations/sub-001/executive_presence/result.json",
        )

    def test_completeness_stops_on_first_missing(
        self, supervisor, mock_dependencies
    ):
        """Stops checking after first missing dimension (short-circuits)."""
        mock_dependencies["s3_client"].head_object.side_effect = Exception("Not Found")

        result = supervisor.verify_completeness(
            "sub-001", ["delivery", "structure", "pacing"]
        )

        assert result is False
        # Only checked the first dimension before returning False
        assert mock_dependencies["s3_client"].head_object.call_count == 1



class TestHappyPathLifecycle:
    """Tests for the full happy path lifecycle.

    Verifies: Evaluating → Report_Generating → Completed status transitions,
    report_path stored in DynamoDB on completion.

    Requirements: 1.1, 1.3, 10.1, 10.2, 10.3, 10.4
    """

    def test_full_lifecycle_status_transitions(
        self, supervisor, mock_dependencies, valid_raw_message, sample_evaluation_result
    ):
        """Happy path: status transitions Evaluating → Report_Generating → Completed."""
        mock_dependencies["coaching_supervisor"].evaluate.return_value = [sample_evaluation_result]
        mock_dependencies["coaching_supervisor"].get_last_failures.return_value = []
        mock_dependencies["report_generator"].generate.return_value = (
            "reports/user-abc/sub-12345/coaching_report.pdf"
        )
        mock_dependencies["registry"].get_available_agents.return_value = []

        supervisor.handle_message(valid_raw_message)

        # Verify all three status updates were called in order
        status_calls = mock_dependencies["status_manager"].update_status.call_args_list
        assert len(status_calls) == 3

        # First: Evaluating
        assert status_calls[0][1]["status"] == ProcessingStatus.EVALUATING
        assert status_calls[0][1]["submission_id"] == "sub-12345"

        # Second: Report_Generating
        assert status_calls[1][1]["status"] == ProcessingStatus.REPORT_GENERATING
        assert status_calls[1][1]["submission_id"] == "sub-12345"

        # Third: Completed with report_path
        assert status_calls[2][1]["status"] == ProcessingStatus.COMPLETED
        assert status_calls[2][1]["submission_id"] == "sub-12345"
        assert status_calls[2][1]["report_path"] == "reports/user-abc/sub-12345/coaching_report.pdf"

    def test_completed_result_includes_report_path(
        self, supervisor, mock_dependencies, valid_raw_message, sample_evaluation_result
    ):
        """SessionResult includes report_path on successful completion."""
        mock_dependencies["coaching_supervisor"].evaluate.return_value = [sample_evaluation_result]
        mock_dependencies["coaching_supervisor"].get_last_failures.return_value = []
        mock_dependencies["report_generator"].generate.return_value = (
            "reports/user-abc/sub-12345/coaching_report.pdf"
        )
        mock_dependencies["registry"].get_available_agents.return_value = []

        result = supervisor.handle_message(valid_raw_message)

        assert result.status == ProcessingStatus.COMPLETED
        assert result.report_path == "reports/user-abc/sub-12345/coaching_report.pdf"
        assert result.failure_reason is None

    def test_completed_result_includes_evaluation_results(
        self, supervisor, mock_dependencies, valid_raw_message, sample_evaluation_result
    ):
        """SessionResult includes evaluation results on successful completion."""
        mock_dependencies["coaching_supervisor"].evaluate.return_value = [sample_evaluation_result]
        mock_dependencies["coaching_supervisor"].get_last_failures.return_value = []
        mock_dependencies["report_generator"].generate.return_value = (
            "reports/user-abc/sub-12345/coaching_report.pdf"
        )
        mock_dependencies["registry"].get_available_agents.return_value = []

        result = supervisor.handle_message(valid_raw_message)

        assert len(result.evaluation_results) == 1
        assert result.evaluation_results[0].dimension == "delivery"
        assert result.evaluation_results[0].score == 7.5

    def test_report_path_stored_in_dynamodb_on_completion(
        self, supervisor, mock_dependencies, valid_raw_message, sample_evaluation_result
    ):
        """report_path is passed to status_manager.update_status when Completed."""
        expected_path = "reports/user-abc/sub-12345/coaching_report.pdf"
        mock_dependencies["coaching_supervisor"].evaluate.return_value = [sample_evaluation_result]
        mock_dependencies["coaching_supervisor"].get_last_failures.return_value = []
        mock_dependencies["report_generator"].generate.return_value = expected_path
        mock_dependencies["registry"].get_available_agents.return_value = []

        supervisor.handle_message(valid_raw_message)

        # The final update_status call should include report_path
        final_call = mock_dependencies["status_manager"].update_status.call_args_list[-1]
        assert final_call[1]["report_path"] == expected_path

    def test_multiple_evaluation_results_stored(
        self, supervisor, mock_dependencies, valid_raw_message
    ):
        """Multiple evaluation results are all stored in S3."""
        result1 = EvaluationResult(
            dimension="delivery",
            score=7.5,
            findings=[],
            strengths=["Good pace"],
            improvements=["Reduce fillers"],
            agent_id="delivery-v1",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        result2 = EvaluationResult(
            dimension="structure",
            score=8.0,
            findings=[],
            strengths=["Clear outline"],
            improvements=["Add transitions"],
            agent_id="structure-v1",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        mock_dependencies["coaching_supervisor"].evaluate.return_value = [result1, result2]
        mock_dependencies["coaching_supervisor"].get_last_failures.return_value = []
        mock_dependencies["report_generator"].generate.return_value = (
            "reports/user-abc/sub-12345/coaching_report.pdf"
        )
        mock_dependencies["registry"].get_available_agents.return_value = []

        result = supervisor.handle_message(valid_raw_message)

        assert result.status == ProcessingStatus.COMPLETED
        assert len(result.evaluation_results) == 2
        # S3 put_object called for each result
        assert mock_dependencies["s3_client"].put_object.call_count == 2


class TestPartialFailure:
    """Tests for partial failure handling.

    When some agents fail but others succeed, the report is still generated
    from available data and the SessionResult includes agent_failures.

    Requirements: 9.4, 4.4, 10.5
    """

    def test_partial_failure_still_generates_report(
        self, supervisor, mock_dependencies, valid_raw_message, sample_evaluation_result
    ):
        """If some agents fail but some succeed, report is still generated."""
        from models.data_models import AgentFailure

        mock_dependencies["coaching_supervisor"].evaluate.return_value = [sample_evaluation_result]
        mock_dependencies["coaching_supervisor"].get_last_failures.return_value = [
            AgentFailure(
                dimension="structure",
                agent_id="structure-evaluator-v1",
                error="Timeout during evaluation",
            )
        ]
        mock_dependencies["report_generator"].generate.return_value = (
            "reports/user-abc/sub-12345/coaching_report.pdf"
        )
        mock_dependencies["registry"].get_available_agents.return_value = []

        result = supervisor.handle_message(valid_raw_message)

        # Report still generated with partial results
        assert result.status == ProcessingStatus.COMPLETED
        assert result.report_path == "reports/user-abc/sub-12345/coaching_report.pdf"
        mock_dependencies["report_generator"].generate.assert_called_once()

    def test_partial_failure_includes_agent_failures_in_result(
        self, supervisor, mock_dependencies, valid_raw_message, sample_evaluation_result
    ):
        """SessionResult includes agent_failures listing which agents failed."""
        from models.data_models import AgentFailure

        failures = [
            AgentFailure(
                dimension="structure",
                agent_id="structure-evaluator-v1",
                error="Timeout during evaluation",
            ),
            AgentFailure(
                dimension="pacing",
                agent_id="pacing-evaluator-v1",
                error="LLM invocation error",
            ),
        ]

        mock_dependencies["coaching_supervisor"].evaluate.return_value = [sample_evaluation_result]
        mock_dependencies["coaching_supervisor"].get_last_failures.return_value = failures
        mock_dependencies["report_generator"].generate.return_value = (
            "reports/user-abc/sub-12345/coaching_report.pdf"
        )
        mock_dependencies["registry"].get_available_agents.return_value = []

        result = supervisor.handle_message(valid_raw_message)

        assert len(result.agent_failures) == 2
        assert result.agent_failures[0].dimension == "structure"
        assert result.agent_failures[0].agent_id == "structure-evaluator-v1"
        assert result.agent_failures[1].dimension == "pacing"

    def test_partial_failure_status_still_completed(
        self, supervisor, mock_dependencies, valid_raw_message, sample_evaluation_result
    ):
        """Partial failure with at least one success still results in Completed status."""
        from models.data_models import AgentFailure

        mock_dependencies["coaching_supervisor"].evaluate.return_value = [sample_evaluation_result]
        mock_dependencies["coaching_supervisor"].get_last_failures.return_value = [
            AgentFailure(
                dimension="pacing",
                agent_id="pacing-evaluator-v1",
                error="Agent crashed",
            )
        ]
        mock_dependencies["report_generator"].generate.return_value = (
            "reports/user-abc/sub-12345/coaching_report.pdf"
        )
        mock_dependencies["registry"].get_available_agents.return_value = []

        result = supervisor.handle_message(valid_raw_message)

        assert result.status == ProcessingStatus.COMPLETED


class TestTotalFailure:
    """Tests for total failure handling.

    When all agents fail (no results obtained), status is set to Failed,
    no report is generated, and detailed failure_reason is provided.

    Requirements: 9.4, 10.5
    """

    def test_all_agents_fail_sets_failed_status(
        self, supervisor, mock_dependencies, valid_raw_message
    ):
        """When all agents fail, status is set to Failed."""
        from models.data_models import AgentFailure

        mock_dependencies["coaching_supervisor"].evaluate.return_value = []
        mock_dependencies["coaching_supervisor"].get_last_failures.return_value = [
            AgentFailure(
                dimension="delivery",
                agent_id="delivery-evaluator-v1",
                error="Connection timeout",
            ),
            AgentFailure(
                dimension="structure",
                agent_id="structure-evaluator-v1",
                error="Model unavailable",
            ),
        ]
        mock_dependencies["registry"].get_available_agents.return_value = []

        result = supervisor.handle_message(valid_raw_message)

        assert result.status == ProcessingStatus.FAILED

    def test_all_agents_fail_no_report_generated(
        self, supervisor, mock_dependencies, valid_raw_message
    ):
        """When all agents fail, no report is generated."""
        from models.data_models import AgentFailure

        mock_dependencies["coaching_supervisor"].evaluate.return_value = []
        mock_dependencies["coaching_supervisor"].get_last_failures.return_value = [
            AgentFailure(
                dimension="delivery",
                agent_id="delivery-evaluator-v1",
                error="Connection timeout",
            ),
        ]
        mock_dependencies["registry"].get_available_agents.return_value = []

        result = supervisor.handle_message(valid_raw_message)

        mock_dependencies["report_generator"].generate.assert_not_called()
        assert result.report_path is None

    def test_all_agents_fail_includes_detailed_failure_reason(
        self, supervisor, mock_dependencies, valid_raw_message
    ):
        """When all agents fail, failure_reason includes agent failure details."""
        from models.data_models import AgentFailure

        mock_dependencies["coaching_supervisor"].evaluate.return_value = []
        mock_dependencies["coaching_supervisor"].get_last_failures.return_value = [
            AgentFailure(
                dimension="delivery",
                agent_id="delivery-evaluator-v1",
                error="Connection timeout",
            ),
            AgentFailure(
                dimension="structure",
                agent_id="structure-evaluator-v1",
                error="Model unavailable",
            ),
        ]
        mock_dependencies["registry"].get_available_agents.return_value = []

        result = supervisor.handle_message(valid_raw_message)

        assert result.failure_reason is not None
        assert "delivery" in result.failure_reason
        assert "structure" in result.failure_reason
        assert "Connection timeout" in result.failure_reason
        assert "Model unavailable" in result.failure_reason

    def test_all_agents_fail_updates_dynamodb_with_failed_status(
        self, supervisor, mock_dependencies, valid_raw_message
    ):
        """When all agents fail, DynamoDB is updated with Failed status and failure_reason."""
        from models.data_models import AgentFailure

        mock_dependencies["coaching_supervisor"].evaluate.return_value = []
        mock_dependencies["coaching_supervisor"].get_last_failures.return_value = [
            AgentFailure(
                dimension="delivery",
                agent_id="delivery-evaluator-v1",
                error="Timeout",
            ),
        ]
        mock_dependencies["registry"].get_available_agents.return_value = []

        supervisor.handle_message(valid_raw_message)

        # Find the Failed status call
        status_calls = mock_dependencies["status_manager"].update_status.call_args_list
        failed_calls = [
            c for c in status_calls if c[1].get("status") == ProcessingStatus.FAILED
        ]
        assert len(failed_calls) == 1
        assert failed_calls[0][1]["failure_reason"] is not None
        assert len(failed_calls[0][1]["failure_reason"]) > 0

    def test_all_agents_fail_sends_error_notification(
        self, supervisor, mock_dependencies, valid_raw_message
    ):
        """When all agents fail, an error notification is published via SNS."""
        from models.data_models import AgentFailure

        mock_dependencies["coaching_supervisor"].evaluate.return_value = []
        mock_dependencies["coaching_supervisor"].get_last_failures.return_value = [
            AgentFailure(
                dimension="delivery",
                agent_id="delivery-evaluator-v1",
                error="Timeout",
            ),
        ]
        mock_dependencies["registry"].get_available_agents.return_value = []

        supervisor.handle_message(valid_raw_message)

        mock_dependencies["error_notifier"].notify.assert_called()
        call_kwargs = mock_dependencies["error_notifier"].notify.call_args[1]
        assert call_kwargs["submission_id"] == "sub-12345"
        assert call_kwargs["error_type"] == "EvaluationSessionFailed"

    def test_coaching_supervisor_raises_exception_sets_failed(
        self, supervisor, mock_dependencies, valid_raw_message
    ):
        """If CoachingSupervisor.evaluate() raises, session is marked Failed."""
        mock_dependencies["coaching_supervisor"].evaluate.side_effect = RuntimeError(
            "Orchestration crashed"
        )
        mock_dependencies["registry"].get_available_agents.return_value = []

        result = supervisor.handle_message(valid_raw_message)

        assert result.status == ProcessingStatus.FAILED
        assert "Orchestration crashed" in result.failure_reason


class TestReportGenerationFailure:
    """Tests for report generation failure handling.

    When evaluation succeeds but report generation fails, status is set
    to Failed with appropriate reason. No report path is stored.

    Requirements: 10.5
    """

    def test_report_failure_sets_failed_status(
        self, supervisor, mock_dependencies, valid_raw_message, sample_evaluation_result
    ):
        """If report generation fails, status is set to Failed."""
        mock_dependencies["coaching_supervisor"].evaluate.return_value = [sample_evaluation_result]
        mock_dependencies["coaching_supervisor"].get_last_failures.return_value = []
        mock_dependencies["report_generator"].generate.side_effect = RuntimeError(
            "PDF library error"
        )
        mock_dependencies["registry"].get_available_agents.return_value = []

        result = supervisor.handle_message(valid_raw_message)

        assert result.status == ProcessingStatus.FAILED

    def test_report_failure_includes_reason(
        self, supervisor, mock_dependencies, valid_raw_message, sample_evaluation_result
    ):
        """If report generation fails, failure_reason explains why."""
        mock_dependencies["coaching_supervisor"].evaluate.return_value = [sample_evaluation_result]
        mock_dependencies["coaching_supervisor"].get_last_failures.return_value = []
        mock_dependencies["report_generator"].generate.side_effect = RuntimeError(
            "PDF library error"
        )
        mock_dependencies["registry"].get_available_agents.return_value = []

        result = supervisor.handle_message(valid_raw_message)

        assert result.failure_reason is not None
        assert "Report generation failed" in result.failure_reason
        assert "PDF library error" in result.failure_reason

    def test_report_failure_updates_dynamodb(
        self, supervisor, mock_dependencies, valid_raw_message, sample_evaluation_result
    ):
        """If report generation fails, DynamoDB is updated to Failed."""
        mock_dependencies["coaching_supervisor"].evaluate.return_value = [sample_evaluation_result]
        mock_dependencies["coaching_supervisor"].get_last_failures.return_value = []
        mock_dependencies["report_generator"].generate.side_effect = RuntimeError(
            "PDF library error"
        )
        mock_dependencies["registry"].get_available_agents.return_value = []

        supervisor.handle_message(valid_raw_message)

        # Find the Failed status call
        status_calls = mock_dependencies["status_manager"].update_status.call_args_list
        failed_calls = [
            c for c in status_calls if c[1].get("status") == ProcessingStatus.FAILED
        ]
        assert len(failed_calls) == 1
        assert "Report generation failed" in failed_calls[0][1]["failure_reason"]

    def test_report_failure_no_report_path_in_result(
        self, supervisor, mock_dependencies, valid_raw_message, sample_evaluation_result
    ):
        """If report generation fails, no report_path in the SessionResult."""
        mock_dependencies["coaching_supervisor"].evaluate.return_value = [sample_evaluation_result]
        mock_dependencies["coaching_supervisor"].get_last_failures.return_value = []
        mock_dependencies["report_generator"].generate.side_effect = RuntimeError(
            "PDF library error"
        )
        mock_dependencies["registry"].get_available_agents.return_value = []

        result = supervisor.handle_message(valid_raw_message)

        assert result.report_path is None

    def test_report_failure_preserves_evaluation_results(
        self, supervisor, mock_dependencies, valid_raw_message, sample_evaluation_result
    ):
        """If report generation fails, evaluation results are still in the SessionResult."""
        mock_dependencies["coaching_supervisor"].evaluate.return_value = [sample_evaluation_result]
        mock_dependencies["coaching_supervisor"].get_last_failures.return_value = []
        mock_dependencies["report_generator"].generate.side_effect = RuntimeError(
            "PDF library error"
        )
        mock_dependencies["registry"].get_available_agents.return_value = []

        result = supervisor.handle_message(valid_raw_message)

        # Results were stored before report generation, so they should be in result
        assert len(result.evaluation_results) == 1
        assert result.evaluation_results[0].dimension == "delivery"


class TestStatusTransitionOrder:
    """Tests for verifying update_status is called in the correct order.

    Requirements: 10.1, 10.2, 10.3, 10.4
    """

    def test_status_order_happy_path(
        self, supervisor, mock_dependencies, valid_raw_message, sample_evaluation_result
    ):
        """Verifies Evaluating → Report_Generating → Completed order."""
        mock_dependencies["coaching_supervisor"].evaluate.return_value = [sample_evaluation_result]
        mock_dependencies["coaching_supervisor"].get_last_failures.return_value = []
        mock_dependencies["report_generator"].generate.return_value = (
            "reports/user-abc/sub-12345/coaching_report.pdf"
        )
        mock_dependencies["registry"].get_available_agents.return_value = []

        supervisor.handle_message(valid_raw_message)

        status_calls = mock_dependencies["status_manager"].update_status.call_args_list
        statuses = [call[1]["status"] for call in status_calls]

        assert statuses == [
            ProcessingStatus.EVALUATING,
            ProcessingStatus.REPORT_GENERATING,
            ProcessingStatus.COMPLETED,
        ]

    def test_status_order_failure_after_evaluation(
        self, supervisor, mock_dependencies, valid_raw_message
    ):
        """On total failure, status goes Evaluating → Failed (no Report_Generating)."""
        from models.data_models import AgentFailure

        mock_dependencies["coaching_supervisor"].evaluate.return_value = []
        mock_dependencies["coaching_supervisor"].get_last_failures.return_value = [
            AgentFailure(
                dimension="delivery",
                agent_id="delivery-evaluator-v1",
                error="Timeout",
            ),
        ]
        mock_dependencies["registry"].get_available_agents.return_value = []

        supervisor.handle_message(valid_raw_message)

        status_calls = mock_dependencies["status_manager"].update_status.call_args_list
        statuses = [call[1]["status"] for call in status_calls]

        assert ProcessingStatus.EVALUATING in statuses
        assert ProcessingStatus.FAILED in statuses
        assert ProcessingStatus.REPORT_GENERATING not in statuses

    def test_status_order_failure_during_report(
        self, supervisor, mock_dependencies, valid_raw_message, sample_evaluation_result
    ):
        """On report failure, status goes Evaluating → Report_Generating → Failed."""
        mock_dependencies["coaching_supervisor"].evaluate.return_value = [sample_evaluation_result]
        mock_dependencies["coaching_supervisor"].get_last_failures.return_value = []
        mock_dependencies["report_generator"].generate.side_effect = RuntimeError(
            "PDF error"
        )
        mock_dependencies["registry"].get_available_agents.return_value = []

        supervisor.handle_message(valid_raw_message)

        status_calls = mock_dependencies["status_manager"].update_status.call_args_list
        statuses = [call[1]["status"] for call in status_calls]

        assert statuses == [
            ProcessingStatus.EVALUATING,
            ProcessingStatus.REPORT_GENERATING,
            ProcessingStatus.FAILED,
        ]

    def test_message_acknowledged_before_evaluation_starts(
        self, supervisor, mock_dependencies, valid_raw_message, sample_evaluation_result
    ):
        """Message is acknowledged (deleted from queue) before evaluation begins."""
        call_order = []

        def track_acknowledge(*args):
            call_order.append("acknowledge")

        def track_evaluate(*args, **kwargs):
            call_order.append("evaluate")
            return [sample_evaluation_result]

        mock_dependencies["sqs_consumer"].acknowledge.side_effect = track_acknowledge
        mock_dependencies["coaching_supervisor"].evaluate.side_effect = track_evaluate
        mock_dependencies["coaching_supervisor"].get_last_failures.return_value = []
        mock_dependencies["report_generator"].generate.return_value = (
            "reports/user-abc/sub-12345/coaching_report.pdf"
        )
        mock_dependencies["registry"].get_available_agents.return_value = []

        supervisor.handle_message(valid_raw_message)

        # acknowledge should happen before evaluate
        assert call_order.index("acknowledge") < call_order.index("evaluate")

    def test_status_evaluating_set_before_coaching_supervisor_called(
        self, supervisor, mock_dependencies, valid_raw_message, sample_evaluation_result
    ):
        """Status is set to Evaluating before CoachingSupervisor.evaluate() is called."""
        call_order = []

        def track_status(*args, **kwargs):
            call_order.append(("status", kwargs.get("status")))

        def track_evaluate(*args, **kwargs):
            call_order.append(("evaluate",))
            return [sample_evaluation_result]

        mock_dependencies["status_manager"].update_status.side_effect = track_status
        mock_dependencies["coaching_supervisor"].evaluate.side_effect = track_evaluate
        mock_dependencies["coaching_supervisor"].get_last_failures.return_value = []
        mock_dependencies["report_generator"].generate.return_value = (
            "reports/user-abc/sub-12345/coaching_report.pdf"
        )
        mock_dependencies["registry"].get_available_agents.return_value = []

        supervisor.handle_message(valid_raw_message)

        # Find indices
        evaluating_idx = next(
            i for i, c in enumerate(call_order)
            if c == ("status", ProcessingStatus.EVALUATING)
        )
        evaluate_idx = next(
            i for i, c in enumerate(call_order)
            if c == ("evaluate",)
        )

        assert evaluating_idx < evaluate_idx
