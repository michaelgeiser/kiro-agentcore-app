"""Unit tests for ReportGeneratorV2 error handling.

Tests the error classification and handling behavior of ReportGeneratorV2:
- Validation failures → ReportValidationError with field list
- Template missing → ReportRenderError
- Template syntax error → ReportRenderError
- WeasyPrint failure → ReportRenderError
- 30s timeout → ReportRenderError
- S3 recoverable errors → retries 3× with backoff
- S3 unrecoverable errors → fail immediately without retry
- DynamoDB status update failure → logs both errors

Requirements: 14.1, 14.2, 14.3, 14.4, 14.5, 14.6
"""

import concurrent.futures
import logging
import time
from unittest.mock import MagicMock, Mock, patch

import pytest
from botocore.exceptions import ClientError

from models.synthesized_report import (
    DimensionEntry,
    Provenance,
    ScoreBand,
    SeverityCounts,
    SynthesizedFinding,
    SynthesizedReport,
    TalkTimeline,
    ThreeMove,
    TranscriptMetrics,
)
from services.report_errors import (
    ReportRenderError,
    ReportUploadError,
    ReportValidationError,
)
from services.report_generator import ReportGeneratorV2


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

DIMENSIONS = [
    "Delivery",
    "Structure",
    "Executive Presence",
    "Technical Communication",
    "Audience Engagement",
    "Pacing",
    "Persuasion",
]


def _make_finding(severity="high", score=5.0):
    """Create a minimal valid SynthesizedFinding."""
    return SynthesizedFinding(
        severity=severity,
        title="Test finding title",
        explanation="You need to improve your delivery style for better impact.",
        suggestion="Try slowing down during key points.",
        effort_tag="quick-win",
        impact_tag="high",
        projected_impact_score=score,
    )


def _make_dimension_entry(name: str, rank: int, is_weakest: bool = False):
    """Create a minimal valid DimensionEntry."""
    return DimensionEntry(
        dimension_name=name,
        score=5.0 + rank * 0.5,
        score_band=ScoreBand.COMPETENT,
        rank=rank,
        one_sentence_verdict="You show solid fundamentals here.",
        severity_counts=SeverityCounts(high=1, medium=1, low=0, strength=1),
        findings=[_make_finding()],
        strengths=["Good pacing"],
        swap_pair=None,
        practice_drill=None,
        is_weakest=is_weakest,
    )


def _make_valid_report(report_id: str = "test-report-001") -> SynthesizedReport:
    """Create a valid SynthesizedReport for testing."""
    dimensions = []
    for i, dim_name in enumerate(DIMENSIONS):
        dimensions.append(
            _make_dimension_entry(
                name=dim_name,
                rank=i + 1,
                is_weakest=(i == 0),
            )
        )

    return SynthesizedReport(
        user_name="Test User",
        presentation_title="Test Presentation",
        file_name="test.mp4",
        upload_date="2025-01-15T10:00:00Z",
        audio_duration_seconds=300.0,
        report_id=report_id,
        speaker_identified=False,
        overall_score=6.2,
        score_band=ScoreBand.COMPETENT,
        distance_to_next_band=0.3,
        two_sentence_verdict="You deliver clearly. Your structure needs work.",
        lede_paragraph="This presentation shows competent delivery with room to grow.",
        dimensions=dimensions,
        three_moves=[
            ThreeMove(
                title="Improve your opening hook",
                coaching_advice="You should start with a compelling question or story.",
                projected_impact_score=7.5,
                dimensions_lifted=["Delivery", "Structure"],
            ),
            ThreeMove(
                title="Add audience interaction",
                coaching_advice="You should pause and ask questions to engage your listeners.",
                projected_impact_score=6.8,
                dimensions_lifted=["Audience Engagement"],
            ),
            ThreeMove(
                title="Strengthen your close",
                coaching_advice="You should end with a clear call to action.",
                projected_impact_score=6.0,
                dimensions_lifted=["Persuasion"],
            ),
        ],
        strengths_to_protect=["Your voice is clear and confident."],
        diagnosis_paragraph="You show strong fundamentals but need to engage your audience more.",
        transcript_metrics=TranscriptMetrics(
            speaking_rate_wpm=145,
            target_range_wpm=(130, 160),
            filler_word_count=3,
            so_opener_count=1,
            pauses_over_one_second=5,
            longest_unbroken_run_seconds=45.2,
            close_share_percent=12.5,
            enunciation_confidence=0.92,
        ),
        talk_timeline=TalkTimeline(
            total_duration_seconds=300.0,
            open_percent=15.0,
            body_percent=72.5,
            close_percent=12.5,
            timeline_pins=[],
        ),
        provenance=Provenance(
            report_id=report_id,
            evaluator_release="1.0.0",
            rubric_version="1.0.0",
            prompt_set_version="1.0.0",
            model_id="us.anthropic.claude-sonnet-4-6",
            model_temperature=0.3,
            transcription_service="aws-transcribe",
            evaluation_window="PT5M",
            run_completed_timestamp="2025-01-15T10:05:00Z",
        ),
    )


def _make_client_error(error_code: str, message: str = "Test error") -> ClientError:
    """Create a botocore ClientError with the given error code."""
    return ClientError(
        error_response={"Error": {"Code": error_code, "Message": message}},
        operation_name="PutObject",
    )


@pytest.fixture
def mock_s3_client():
    """Create a mock S3 client."""
    return MagicMock()


@pytest.fixture
def mock_dynamodb_resource():
    """Create a mock DynamoDB resource with a Table mock."""
    resource = MagicMock()
    table = MagicMock()
    resource.Table.return_value = table
    return resource


@pytest.fixture
def generator_with_mocks(mock_s3_client, mock_dynamodb_resource, tmp_path):
    """Create a ReportGeneratorV2 with mocked dependencies and a real template."""
    # Create a minimal valid Jinja2 template
    template_dir = tmp_path / "templates"
    template_dir.mkdir()
    template_file = template_dir / "coaching_report.html"
    template_file.write_text(
        "<html><body><h1>{{ presentation_title }}</h1>"
        "<p>Score: {{ overall_score }}</p></body></html>"
    )

    with patch.object(ReportGeneratorV2, "_resolve_template_dir", return_value=template_dir):
        gen = ReportGeneratorV2(
            bucket_name="test-bucket",
            template_path="templates/coaching_report.html",
            s3_client=mock_s3_client,
            dynamodb_resource=mock_dynamodb_resource,
            timeout_seconds=30.0,
        )
    return gen


# ---------------------------------------------------------------------------
# Test: Validation failure returns ReportValidationError with field list
# Requirement 14.1
# ---------------------------------------------------------------------------


class TestValidationErrors:
    """Tests that validation failures produce ReportValidationError with field details."""

    def test_validation_failure_raises_report_validation_error(
        self, generator_with_mocks
    ):
        """Validation failure returns ReportValidationError identifying invalid fields.

        Requirement 14.1: IF the SynthesizedReport fails validation, THEN return
        an error immediately with a message identifying each invalid field.
        """
        report = _make_valid_report()
        # Manually set provenance report_id to mismatch (triggers validation error)
        report.provenance.report_id = "mismatched-id"

        with pytest.raises(ReportValidationError) as exc_info:
            generator_with_mocks.generate(
                report=report, user_id="user-1", submission_id="sub-1"
            )

        error = exc_info.value
        assert error.report_id == "test-report-001"
        assert error.invalid_fields is not None
        assert len(error.invalid_fields) > 0
        # Check that the field list identifies which field failed
        field_names = [f["field"] for f in error.invalid_fields]
        assert "provenance.report_id" in field_names

    def test_validation_error_lists_all_invalid_fields(
        self, generator_with_mocks
    ):
        """When multiple fields fail, all are included in invalid_fields list."""
        report = _make_valid_report()
        # Mismatch provenance and manually break weakest count
        report.provenance.report_id = "wrong-id"
        # Set all dimensions to is_weakest=False so validation fails
        for dim in report.dimensions:
            dim.is_weakest = False

        with pytest.raises(ReportValidationError) as exc_info:
            generator_with_mocks.generate(
                report=report, user_id="user-1", submission_id="sub-1"
            )

        error = exc_info.value
        assert len(error.invalid_fields) >= 2
        field_names = [f["field"] for f in error.invalid_fields]
        assert "provenance.report_id" in field_names
        assert "dimensions.is_weakest" in field_names


# ---------------------------------------------------------------------------
# Test: Template missing raises ReportRenderError
# Requirement 14.2
# ---------------------------------------------------------------------------


class TestTemplateMissing:
    """Tests that a missing template raises ReportRenderError."""

    def test_template_not_found_raises_report_render_error(
        self, mock_s3_client, mock_dynamodb_resource, tmp_path
    ):
        """Missing template file raises ReportRenderError with template path.

        Requirement 14.2: IF the Jinja2 template is missing, THEN log the
        rendering error with template path, and return a failure status.
        """
        # Create an empty template directory (no template file)
        template_dir = tmp_path / "templates"
        template_dir.mkdir()

        with patch.object(
            ReportGeneratorV2, "_resolve_template_dir", return_value=template_dir
        ):
            gen = ReportGeneratorV2(
                bucket_name="test-bucket",
                template_path="templates/coaching_report.html",
                s3_client=mock_s3_client,
                dynamodb_resource=mock_dynamodb_resource,
            )

        report = _make_valid_report()

        with pytest.raises(ReportRenderError) as exc_info:
            gen.generate(report=report, user_id="user-1", submission_id="sub-1")

        error = exc_info.value
        assert error.report_id == "test-report-001"
        assert "templates/coaching_report.html" in error.template_path or (
            error.template_path is not None
        )
        # S3 upload should NOT have been called
        mock_s3_client.put_object.assert_not_called()


# ---------------------------------------------------------------------------
# Test: Template syntax error raises ReportRenderError
# Requirement 14.2
# ---------------------------------------------------------------------------


class TestTemplateSyntaxError:
    """Tests that template syntax errors raise ReportRenderError."""

    def test_template_syntax_error_raises_report_render_error(
        self, mock_s3_client, mock_dynamodb_resource, tmp_path
    ):
        """Template with syntax error raises ReportRenderError with details.

        Requirement 14.2: IF the Jinja2 template contains syntax errors, THEN
        log the rendering error with template path and error location.
        """
        template_dir = tmp_path / "templates"
        template_dir.mkdir()
        template_file = template_dir / "coaching_report.html"
        # Invalid Jinja2 syntax — unclosed block
        template_file.write_text("{% if True %}<p>Missing endif</p>")

        with patch.object(
            ReportGeneratorV2, "_resolve_template_dir", return_value=template_dir
        ):
            gen = ReportGeneratorV2(
                bucket_name="test-bucket",
                template_path="templates/coaching_report.html",
                s3_client=mock_s3_client,
                dynamodb_resource=mock_dynamodb_resource,
            )

        report = _make_valid_report()

        with pytest.raises(ReportRenderError) as exc_info:
            gen.generate(report=report, user_id="user-1", submission_id="sub-1")

        error = exc_info.value
        assert error.report_id == "test-report-001"
        assert error.template_path is not None
        # S3 should not be called
        mock_s3_client.put_object.assert_not_called()


# ---------------------------------------------------------------------------
# Test: WeasyPrint failure raises ReportRenderError
# Requirement 14.2
# ---------------------------------------------------------------------------


class TestWeasyPrintFailure:
    """Tests that WeasyPrint rendering failure raises ReportRenderError."""

    def test_weasyprint_exception_raises_report_render_error(
        self, generator_with_mocks, mock_s3_client
    ):
        """WeasyPrint rendering exception raises ReportRenderError.

        Requirement 14.2: IF WeasyPrint rendering raises an exception, THEN
        log the error and return failure without uploading to S3.
        """
        report = _make_valid_report()

        # Mock WeasyPrint to raise an exception
        with patch.object(
            ReportGeneratorV2,
            "_do_weasyprint_render",
            side_effect=RuntimeError("Cairo rendering failed"),
        ):
            with pytest.raises(ReportRenderError) as exc_info:
                generator_with_mocks.generate(
                    report=report, user_id="user-1", submission_id="sub-1"
                )

        error = exc_info.value
        assert error.report_id == "test-report-001"
        assert "rendering failed" in error.message.lower() or "failed" in error.message.lower()
        # S3 should not be called
        mock_s3_client.put_object.assert_not_called()


# ---------------------------------------------------------------------------
# Test: 30s timeout terminates and raises ReportRenderError
# Requirement 14.2 (4.10)
# ---------------------------------------------------------------------------


class TestRenderingTimeout:
    """Tests that rendering timeout raises ReportRenderError."""

    def test_timeout_raises_report_render_error(
        self, mock_s3_client, mock_dynamodb_resource, tmp_path
    ):
        """Rendering timeout terminates operation and raises ReportRenderError.

        Requirement 4.10: IF rendering does not complete within 30 seconds,
        THEN terminate and return an error immediately.
        """
        template_dir = tmp_path / "templates"
        template_dir.mkdir()
        template_file = template_dir / "coaching_report.html"
        template_file.write_text(
            "<html><body><h1>{{ presentation_title }}</h1></body></html>"
        )

        # Create generator with very short timeout for testing
        with patch.object(
            ReportGeneratorV2, "_resolve_template_dir", return_value=template_dir
        ):
            gen = ReportGeneratorV2(
                bucket_name="test-bucket",
                template_path="templates/coaching_report.html",
                s3_client=mock_s3_client,
                dynamodb_resource=mock_dynamodb_resource,
                timeout_seconds=0.1,  # Very short timeout for testing
            )

        report = _make_valid_report()

        # Mock WeasyPrint to block for longer than the timeout
        def slow_render(html):
            time.sleep(5)  # Will exceed the 0.1s timeout
            return b"%PDF-fake"

        with patch.object(
            ReportGeneratorV2, "_do_weasyprint_render", side_effect=slow_render
        ):
            with pytest.raises(ReportRenderError) as exc_info:
                gen.generate(report=report, user_id="user-1", submission_id="sub-1")

        error = exc_info.value
        assert error.report_id == "test-report-001"
        assert "timed out" in error.message.lower() or "timeout" in error.message.lower()
        # S3 should not be called
        mock_s3_client.put_object.assert_not_called()


# ---------------------------------------------------------------------------
# Test: S3 recoverable error (ThrottlingException) retries 3× with backoff
# Requirement 14.3
# ---------------------------------------------------------------------------


class TestS3RecoverableRetry:
    """Tests that recoverable S3 errors trigger retry with exponential backoff."""

    def test_throttling_retries_three_times(
        self, generator_with_mocks, mock_s3_client
    ):
        """S3 ThrottlingException retries 3 times before raising ReportUploadError.

        Requirement 14.3: IF S3 upload fails with a recoverable error, THEN
        retry with exponential backoff up to 3 attempts.
        """
        report = _make_valid_report()

        # Mock WeasyPrint to return valid PDF
        with patch.object(
            ReportGeneratorV2,
            "_do_weasyprint_render",
            return_value=b"%PDF-1.4 fake pdf content",
        ):
            # S3 always fails with ThrottlingException
            mock_s3_client.put_object.side_effect = _make_client_error(
                "ThrottlingException"
            )

            with patch("services.report_generator.time.sleep") as mock_sleep:
                with pytest.raises(ReportUploadError) as exc_info:
                    generator_with_mocks.generate(
                        report=report, user_id="user-1", submission_id="sub-1"
                    )

        error = exc_info.value
        assert error.report_id == "test-report-001"
        # Should have been called 3 times total (initial + 2 retries)
        assert mock_s3_client.put_object.call_count == 3
        # Should have slept between retries (2 sleeps for 3 attempts)
        assert mock_sleep.call_count == 2

    def test_recoverable_error_succeeds_on_retry(
        self, generator_with_mocks, mock_s3_client
    ):
        """S3 recoverable error succeeds on second attempt."""
        report = _make_valid_report()

        # First call fails with throttling, second succeeds
        mock_s3_client.put_object.side_effect = [
            _make_client_error("ThrottlingException"),
            None,  # Success on retry
        ]

        with patch.object(
            ReportGeneratorV2,
            "_do_weasyprint_render",
            return_value=b"%PDF-1.4 fake pdf content",
        ):
            with patch("services.report_generator.time.sleep"):
                s3_key = generator_with_mocks.generate(
                    report=report, user_id="user-1", submission_id="sub-1"
                )

        assert s3_key == "reports/user-1/sub-1/coaching_report.pdf"
        assert mock_s3_client.put_object.call_count == 2


# ---------------------------------------------------------------------------
# Test: S3 unrecoverable error (AccessDenied) fails immediately without retry
# Requirement 14.4
# ---------------------------------------------------------------------------


class TestS3UnrecoverableError:
    """Tests that unrecoverable S3 errors fail immediately without retry."""

    def test_access_denied_fails_immediately(
        self, generator_with_mocks, mock_s3_client
    ):
        """S3 AccessDenied fails immediately without retrying.

        Requirement 14.4: IF S3 upload fails with an unrecoverable error
        (access denied), THEN fail immediately without retrying.
        """
        report = _make_valid_report()

        mock_s3_client.put_object.side_effect = _make_client_error("AccessDenied")

        with patch.object(
            ReportGeneratorV2,
            "_do_weasyprint_render",
            return_value=b"%PDF-1.4 fake pdf content",
        ):
            with pytest.raises(ReportUploadError) as exc_info:
                generator_with_mocks.generate(
                    report=report, user_id="user-1", submission_id="sub-1"
                )

        error = exc_info.value
        assert error.report_id == "test-report-001"
        assert "AccessDenied" in error.message
        # Should have been called exactly once — no retry
        assert mock_s3_client.put_object.call_count == 1

    def test_no_such_bucket_fails_immediately(
        self, generator_with_mocks, mock_s3_client
    ):
        """S3 NoSuchBucket fails immediately without retrying."""
        report = _make_valid_report()

        mock_s3_client.put_object.side_effect = _make_client_error("NoSuchBucket")

        with patch.object(
            ReportGeneratorV2,
            "_do_weasyprint_render",
            return_value=b"%PDF-1.4 fake pdf content",
        ):
            with pytest.raises(ReportUploadError) as exc_info:
                generator_with_mocks.generate(
                    report=report, user_id="user-1", submission_id="sub-1"
                )

        error = exc_info.value
        assert "NoSuchBucket" in error.message
        assert mock_s3_client.put_object.call_count == 1


# ---------------------------------------------------------------------------
# Test: DynamoDB status update failure logs both errors
# Requirement 14.6
# ---------------------------------------------------------------------------


class TestDynamoDBFailure:
    """Tests that DynamoDB failure is logged without masking the original result."""

    def test_dynamodb_failure_logs_error_and_does_not_raise(
        self, generator_with_mocks, mock_s3_client, mock_dynamodb_resource, caplog
    ):
        """DynamoDB status update failure logs both errors but still returns s3_key.

        Requirement 14.6: IF the DynamoDB status update fails, THEN log the
        original failure reason and the DynamoDB error, and propagate the
        original error to the caller.

        In the success path (upload completed), the implementation logs the
        DynamoDB error but does NOT raise — the S3 key is still valid.
        """
        report = _make_valid_report()

        # S3 upload succeeds
        mock_s3_client.put_object.return_value = None

        # DynamoDB update_item fails
        table_mock = mock_dynamodb_resource.Table.return_value
        table_mock.update_item.side_effect = ClientError(
            error_response={
                "Error": {
                    "Code": "InternalServerError",
                    "Message": "DynamoDB is unavailable",
                }
            },
            operation_name="UpdateItem",
        )

        with patch.object(
            ReportGeneratorV2,
            "_do_weasyprint_render",
            return_value=b"%PDF-1.4 fake pdf content",
        ):
            with caplog.at_level(logging.ERROR):
                # Should NOT raise — DynamoDB failure is logged but the report
                # generation is considered successful since the PDF was uploaded
                s3_key = generator_with_mocks.generate(
                    report=report, user_id="user-1", submission_id="sub-1"
                )

        # Report generation completed successfully despite DynamoDB failure
        assert s3_key == "reports/user-1/sub-1/coaching_report.pdf"

        # Verify the DynamoDB error was logged
        dynamodb_error_logged = any(
            "DynamoDB" in record.message or "update" in record.message.lower()
            for record in caplog.records
            if record.levelno >= logging.ERROR
        )
        assert dynamodb_error_logged, (
            "Expected an ERROR log mentioning DynamoDB failure"
        )

    def test_dynamodb_failure_still_attempts_update(
        self, generator_with_mocks, mock_s3_client, mock_dynamodb_resource
    ):
        """DynamoDB update_item is called even though it will fail."""
        report = _make_valid_report()

        mock_s3_client.put_object.return_value = None
        table_mock = mock_dynamodb_resource.Table.return_value
        table_mock.update_item.side_effect = ClientError(
            error_response={
                "Error": {"Code": "ConditionalCheckFailedException", "Message": "Condition not met"}
            },
            operation_name="UpdateItem",
        )

        with patch.object(
            ReportGeneratorV2,
            "_do_weasyprint_render",
            return_value=b"%PDF-1.4 fake pdf content",
        ):
            generator_with_mocks.generate(
                report=report, user_id="user-1", submission_id="sub-1"
            )

        # Verify update_item was actually called
        table_mock.update_item.assert_called_once()
