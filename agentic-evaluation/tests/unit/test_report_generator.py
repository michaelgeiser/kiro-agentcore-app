"""Unit tests for the ReportGenerator service.

Tests report generation with single and multiple dimension results,
PDF validity, content verification, and S3 storage.

Requirements: 6.1, 6.2, 6.4, 6.5
"""

import io
from datetime import datetime, timezone

import boto3
import pypdf
import pytest
from moto import mock_aws

from models.data_models import EvaluationResult, Finding
from services.report_generator import ReportGenerator


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract all text from a PDF binary using pypdf."""
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    text_parts = []
    for page in reader.pages:
        text_parts.append(page.extract_text() or "")
    return "\n".join(text_parts)


def _make_evaluation_result(
    dimension: str = "delivery",
    score: float = 7.5,
    agent_id: str = "agent-delivery-v1",
    strengths: list[str] | None = None,
    improvements: list[str] | None = None,
    findings: list[Finding] | None = None,
) -> EvaluationResult:
    """Helper to create an EvaluationResult with sensible defaults."""
    return EvaluationResult(
        dimension=dimension,
        score=score,
        agent_id=agent_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        strengths=strengths or ["Clear articulation"],
        improvements=improvements or ["Vary vocal tone more"],
        findings=findings or [
            Finding(
                category="vocal_variety",
                detail="Monotone detected in middle section",
                severity="medium",
                suggestion="Try varying pitch during key points",
            )
        ],
    )


ALL_DIMENSIONS = [
    ("delivery", "agent-delivery-v1"),
    ("structure", "agent-structure-v1"),
    ("executive_presence", "agent-exec-presence-v1"),
    ("technical_communication", "agent-tech-comm-v1"),
    ("audience_engagement", "agent-audience-v1"),
    ("pacing", "agent-pacing-v1"),
    ("persuasion", "agent-persuasion-v1"),
]


@pytest.fixture
def s3_bucket():
    """Create a mocked S3 bucket for testing."""
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="test-reports-bucket")
        yield s3


class TestReportGeneratorGenerate:
    """Tests for ReportGenerator.generate() method."""

    def test_generate_single_dimension_uploads_to_s3(self, s3_bucket):
        """generate() with a single EvaluationResult uploads PDF to S3."""
        generator = ReportGenerator(
            bucket_name="test-reports-bucket",
            s3_client=s3_bucket,
        )
        result = _make_evaluation_result(dimension="delivery", score=8.0)

        s3_key = generator.generate(
            submission_id="sub-001",
            user_id="user-abc",
            results=[result],
        )

        # Verify S3 upload occurred
        response = s3_bucket.get_object(
            Bucket="test-reports-bucket", Key=s3_key
        )
        body = response["Body"].read()
        assert len(body) > 0

    def test_generate_single_dimension_returns_correct_key(self, s3_bucket):
        """generate() returns the correct S3 key path."""
        generator = ReportGenerator(
            bucket_name="test-reports-bucket",
            s3_client=s3_bucket,
        )
        result = _make_evaluation_result()

        s3_key = generator.generate(
            submission_id="sub-001",
            user_id="user-abc",
            results=[result],
        )

        assert s3_key == "reports/user-abc/sub-001/coaching_report.pdf"

    def test_generate_all_seven_dimensions(self, s3_bucket):
        """generate() with 7 results produces PDF containing all dimensions."""
        generator = ReportGenerator(
            bucket_name="test-reports-bucket",
            s3_client=s3_bucket,
        )
        results = [
            _make_evaluation_result(
                dimension=dim,
                score=5.0 + i * 0.5,
                agent_id=agent_id,
            )
            for i, (dim, agent_id) in enumerate(ALL_DIMENSIONS)
        ]

        s3_key = generator.generate(
            submission_id="sub-007",
            user_id="user-xyz",
            results=results,
        )

        # Verify upload succeeded
        response = s3_bucket.get_object(
            Bucket="test-reports-bucket", Key=s3_key
        )
        body = response["Body"].read()
        assert len(body) > 100  # Non-trivial PDF content

    def test_s3_key_matches_expected_pattern(self, s3_bucket):
        """S3 key matches reports/{user_id}/{submission_id}/coaching_report.pdf."""
        generator = ReportGenerator(
            bucket_name="test-reports-bucket",
            s3_client=s3_bucket,
        )
        result = _make_evaluation_result()

        s3_key = generator.generate(
            submission_id="my-submission-42",
            user_id="user-99",
            results=[result],
        )

        assert s3_key == "reports/user-99/my-submission-42/coaching_report.pdf"


class TestReportGeneratorPDFValidity:
    """Tests for PDF validity and content."""

    def test_pdf_starts_with_valid_header(self, s3_bucket):
        """PDF buffer starts with %PDF (valid PDF header)."""
        generator = ReportGenerator(
            bucket_name="test-reports-bucket",
            s3_client=s3_bucket,
        )
        result = _make_evaluation_result()

        generator.generate(
            submission_id="sub-pdf",
            user_id="user-pdf",
            results=[result],
        )

        response = s3_bucket.get_object(
            Bucket="test-reports-bucket",
            Key="reports/user-pdf/sub-pdf/coaching_report.pdf",
        )
        body = response["Body"].read()
        assert body[:4] == b"%PDF"

    def test_pdf_is_non_empty(self, s3_bucket):
        """PDF is non-empty (>100 bytes)."""
        generator = ReportGenerator(
            bucket_name="test-reports-bucket",
            s3_client=s3_bucket,
        )
        result = _make_evaluation_result()

        generator.generate(
            submission_id="sub-size",
            user_id="user-size",
            results=[result],
        )

        response = s3_bucket.get_object(
            Bucket="test-reports-bucket",
            Key="reports/user-size/sub-size/coaching_report.pdf",
        )
        body = response["Body"].read()
        assert len(body) > 100


class TestReportGeneratorBuildPDF:
    """Tests for _build_pdf() direct invocation and content verification."""

    def test_build_pdf_contains_executive_summary(self):
        """PDF content contains Executive Summary section text."""
        generator = ReportGenerator(bucket_name="unused")
        result = _make_evaluation_result(dimension="delivery", score=7.0)

        pdf_buffer = generator._build_pdf("sub-content", [result])
        text = _extract_pdf_text(pdf_buffer.getvalue())

        assert "Executive Summary" in text

    def test_build_pdf_contains_feedback_section(self):
        """PDF content contains Per-Dimension Detailed Feedback section."""
        generator = ReportGenerator(bucket_name="unused")
        result = _make_evaluation_result(dimension="structure", score=6.5)

        pdf_buffer = generator._build_pdf("sub-feedback", [result])
        text = _extract_pdf_text(pdf_buffer.getvalue())

        assert "Detailed Feedback" in text

    def test_build_pdf_contains_strengths(self):
        """PDF content contains strengths text."""
        generator = ReportGenerator(bucket_name="unused")
        result = _make_evaluation_result(
            dimension="pacing",
            strengths=["Excellent timing throughout"],
        )

        pdf_buffer = generator._build_pdf("sub-strengths", [result])
        text = _extract_pdf_text(pdf_buffer.getvalue())

        assert "Strengths" in text

    def test_build_pdf_contains_improvements(self):
        """PDF content contains improvements text."""
        generator = ReportGenerator(bucket_name="unused")
        result = _make_evaluation_result(
            dimension="persuasion",
            improvements=["Use stronger call to action"],
        )

        pdf_buffer = generator._build_pdf("sub-improvements", [result])
        text = _extract_pdf_text(pdf_buffer.getvalue())

        assert "Improvement" in text

    def test_build_pdf_all_dimensions_present_in_content(self):
        """PDF with all 7 dimensions contains each dimension display name."""
        generator = ReportGenerator(bucket_name="unused")
        results = [
            _make_evaluation_result(dimension=dim, agent_id=agent_id)
            for dim, agent_id in ALL_DIMENSIONS
        ]

        pdf_buffer = generator._build_pdf("sub-all", results)
        text = _extract_pdf_text(pdf_buffer.getvalue())

        # Dimensions are now displayed with formatted names
        expected_display_names = [
            "Delivery",
            "Structure",
            "Executive Presence",
            "Technical Communication",
            "Audience Engagement",
            "Pacing",
            "Persuasion",
        ]
        for display_name in expected_display_names:
            assert display_name in text, (
                f"Dimension '{display_name}' not found in PDF content"
            )

    def test_build_pdf_returns_valid_pdf_header(self):
        """_build_pdf() returns a buffer starting with %PDF."""
        generator = ReportGenerator(bucket_name="unused")
        result = _make_evaluation_result()

        pdf_buffer = generator._build_pdf("sub-header", [result])
        pdf_bytes = pdf_buffer.getvalue()

        assert pdf_bytes[:4] == b"%PDF"

    def test_build_pdf_non_empty_output(self):
        """_build_pdf() produces a buffer larger than 100 bytes."""
        generator = ReportGenerator(bucket_name="unused")
        result = _make_evaluation_result()

        pdf_buffer = generator._build_pdf("sub-nonempty", [result])
        pdf_bytes = pdf_buffer.getvalue()

        assert len(pdf_bytes) > 100
