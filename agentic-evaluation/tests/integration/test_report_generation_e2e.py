"""Integration test for end-to-end report generation pipeline.

Tests the full pipeline:
    EvaluationResult[] → CoachingSupervisor.synthesis_pass() → SynthesizedReport
    → ReportGeneratorV2.generate() → HTML → PDF → S3 upload (mocked)

Verifies:
- SynthesizedReport passes Pydantic validation
- PDF is valid (starts with %PDF), non-empty, within 10MB size limit
- S3 key matches expected path pattern: reports/{user_id}/{submission_id}/coaching_report.pdf
- DynamoDB update_item is called with correct args

Requirements: 4.1, 4.4, 4.8
"""

import importlib.util
import re
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from agents.coaching_supervisor import CoachingSupervisor, SubmissionMetadata
from models.data_models import EvaluationResult, Finding
from models.synthesized_report import SynthesizedReport
from services.report_generator import ReportGeneratorV2
from services.transcript_metrics import TranscriptData, WordTiming


# ---------------------------------------------------------------------------
# Skip entire module if WeasyPrint is not available
# ---------------------------------------------------------------------------

_weasyprint_available = importlib.util.find_spec("weasyprint") is not None

try:
    if _weasyprint_available:
        from weasyprint import HTML

        HTML(string="<p>test</p>").write_pdf()
except Exception:
    _weasyprint_available = False

pytestmark = pytest.mark.skipif(
    not _weasyprint_available,
    reason="WeasyPrint is not installed or system dependencies (cairo, pango) are missing",
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALL_DIMENSIONS = [
    "Delivery",
    "Structure",
    "Executive Presence",
    "Technical Communication",
    "Audience Engagement",
    "Pacing",
    "Persuasion",
]

USER_ID = "user-e2e-test-001"
SUBMISSION_ID = "sub-e2e-test-001"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def realistic_evaluation_results() -> list[EvaluationResult]:
    """Create realistic EvaluationResults for all 7 dimensions.

    Each result has multiple findings with varying severity, evidence quotes,
    strengths, and improvements — simulating real specialist agent output.
    """
    now = datetime.now(timezone.utc).isoformat()

    results = []
    scores = [5.5, 7.0, 4.2, 6.8, 8.1, 3.9, 7.5]
    agent_ids = [
        "delivery-evaluator-v1",
        "structure-evaluator-v1",
        "executive-presence-evaluator-v1",
        "technical-communication-evaluator-v1",
        "audience-engagement-evaluator-v1",
        "pacing-evaluator-v1",
        "persuasion-evaluator-v1",
    ]

    findings_data = [
        # Delivery
        [
            Finding(
                category="vocal_variety",
                detail="Monotone delivery in the opening two minutes reduces listener engagement",
                severity="high",
                suggestion="Vary your pitch when introducing key points to signal importance",
            ),
            Finding(
                category="filler_words",
                detail="Excessive use of 'um' and 'like' during transitions between slides",
                severity="medium",
                suggestion="Pause silently instead of filling gaps with filler words",
            ),
        ],
        # Structure
        [
            Finding(
                category="transitions",
                detail="Abrupt topic shifts between slides three and four confuse the audience",
                severity="medium",
                suggestion="Use signpost phrases like 'Moving on to' or 'Building on that'",
            ),
        ],
        # Executive Presence
        [
            Finding(
                category="confidence",
                detail="Hedging language undermines your authority on the subject matter",
                severity="high",
                suggestion="Replace 'I think maybe' with direct assertions like 'Our data shows'",
            ),
            Finding(
                category="authority",
                detail="Apologizing for slides that look basic signals low confidence",
                severity="medium",
                suggestion="Present visuals confidently regardless of their complexity",
            ),
            Finding(
                category="posture",
                detail="Verbal cues suggest physical tension during the Q&A segment",
                severity="low",
                suggestion="Practice power poses before presenting to build physical confidence",
            ),
        ],
        # Technical Communication
        [
            Finding(
                category="jargon_usage",
                detail="Technical acronyms used without expansion in the first three minutes",
                severity="medium",
                suggestion="Define acronyms on first use even when audience seems technical",
            ),
        ],
        # Audience Engagement
        [
            Finding(
                category="questions",
                detail="Strong use of rhetorical questions to maintain audience attention",
                severity="low",
                suggestion="Continue using questions but add brief pauses after for effect",
            ),
        ],
        # Pacing
        [
            Finding(
                category="speed",
                detail="Speaking rate exceeds 180 WPM during the technical explanation section",
                severity="high",
                suggestion="Slow down to 140-160 WPM when explaining complex concepts",
            ),
            Finding(
                category="rushing",
                detail="The conclusion was rushed at over 200 WPM suggesting time pressure",
                severity="medium",
                suggestion="Allocate 15% of your time budget to the closing segment",
            ),
        ],
        # Persuasion
        [
            Finding(
                category="evidence_usage",
                detail="Claims made without supporting data in slides six through eight",
                severity="medium",
                suggestion="Back every claim with a specific data point or credible source",
            ),
        ],
    ]

    strengths_data = [
        ["Clear articulation", "Good energy levels"],
        ["Logical flow", "Clear opening hook", "Strong conclusion"],
        ["Good eye contact cues"],
        ["Accurate technical content", "Good code examples"],
        ["Effective use of stories", "Good audience rapport", "Interactive style"],
        ["Good use of pauses for emphasis"],
        ["Clear call to action", "Good emotional appeal"],
    ]

    improvements_data = [
        ["Reduce filler words", "Vary pitch more"],
        ["Smoother transitions needed"],
        ["Remove hedging language", "Strengthen closing authority"],
        ["Simplify jargon for mixed audiences"],
        ["Add more interactive elements"],
        ["Slow down during complex sections", "Practice timing the conclusion"],
        ["Support claims with more evidence"],
    ]

    for i, dim in enumerate(ALL_DIMENSIONS):
        results.append(
            EvaluationResult(
                dimension=dim,
                score=scores[i],
                findings=findings_data[i],
                strengths=strengths_data[i],
                improvements=improvements_data[i],
                agent_id=agent_ids[i],
                timestamp=now,
            )
        )

    return results


@pytest.fixture
def realistic_transcript() -> TranscriptData:
    """Create realistic TranscriptData with word-level timings.

    Simulates a ~60 second presentation excerpt with natural pauses,
    filler words, and varying confidence scores.
    """
    words = []
    text_segments = [
        ("So", 0.5, 0.8, 0.95),
        ("today", 0.85, 1.2, 0.98),
        ("I", 1.25, 1.3, 0.99),
        ("want", 1.32, 1.55, 0.97),
        ("to", 1.57, 1.65, 0.96),
        ("talk", 1.67, 1.9, 0.98),
        ("about", 1.92, 2.2, 0.97),
        ("our", 2.25, 2.4, 0.96),
        ("new", 2.42, 2.6, 0.98),
        ("architecture", 2.62, 3.1, 0.94),
        # Pause > 1s
        ("um", 4.5, 4.7, 0.85),
        ("the", 4.8, 4.95, 0.97),
        ("key", 5.0, 5.2, 0.98),
        ("insight", 5.22, 5.6, 0.96),
        ("here", 5.62, 5.85, 0.97),
        ("is", 5.87, 5.95, 0.98),
        ("that", 5.97, 6.1, 0.97),
        ("microservices", 6.15, 6.8, 0.91),
        ("give", 6.85, 7.0, 0.97),
        ("you", 7.02, 7.15, 0.98),
        ("flexibility", 7.17, 7.7, 0.95),
        # Pause > 1s
        ("So", 9.0, 9.2, 0.96),
        ("like", 9.25, 9.4, 0.93),
        ("I", 9.7, 9.8, 0.98),
        ("think", 9.82, 10.0, 0.97),
        ("we", 10.02, 10.15, 0.98),
        ("should", 10.17, 10.4, 0.97),
        ("consider", 10.42, 10.8, 0.96),
        ("three", 10.85, 11.0, 0.98),
        ("options", 11.02, 11.4, 0.97),
        # More content with natural flow
        ("first", 11.6, 11.85, 0.98),
        ("we", 11.87, 11.95, 0.97),
        ("could", 11.97, 12.15, 0.96),
        ("refactor", 12.17, 12.55, 0.95),
        ("the", 12.57, 12.65, 0.98),
        ("existing", 12.67, 13.0, 0.96),
        ("monolith", 13.02, 13.4, 0.93),
        # Short pause
        ("second", 13.8, 14.1, 0.98),
        ("we", 14.12, 14.2, 0.97),
        ("build", 14.22, 14.45, 0.98),
        ("new", 14.47, 14.6, 0.97),
        ("services", 14.62, 15.0, 0.96),
        ("from", 15.02, 15.2, 0.97),
        ("scratch", 15.22, 15.55, 0.96),
        # Pause > 1s
        ("and", 16.8, 16.95, 0.97),
        ("third", 16.97, 17.2, 0.98),
        ("uh", 17.25, 17.4, 0.82),
        ("a", 17.45, 17.5, 0.96),
        ("hybrid", 17.52, 17.85, 0.95),
        ("approach", 17.87, 18.3, 0.96),
        # Closing segment starts at ~45s mark
        ("so", 45.0, 45.2, 0.96),
        ("to", 45.22, 45.35, 0.97),
        ("wrap", 45.37, 45.55, 0.98),
        ("up", 45.57, 45.65, 0.97),
        ("our", 45.67, 45.8, 0.96),
        ("recommendation", 45.82, 46.4, 0.94),
        ("is", 46.42, 46.5, 0.98),
        ("to", 46.52, 46.6, 0.97),
        ("go", 46.62, 46.75, 0.98),
        ("with", 46.77, 46.9, 0.97),
        ("the", 46.92, 47.0, 0.98),
        ("hybrid", 47.02, 47.35, 0.95),
        ("approach", 47.37, 47.8, 0.96),
        ("thank", 48.0, 48.2, 0.98),
        ("you", 48.22, 48.35, 0.99),
    ]

    for word_text, start, end, confidence in text_segments:
        words.append(
            WordTiming(
                word=word_text,
                start_seconds=start,
                end_seconds=end,
                confidence=confidence,
            )
        )

    return TranscriptData(
        words=words,
        close_start_seconds=45.0,  # Closing segment starts at 45s
    )


@pytest.fixture
def submission_metadata() -> SubmissionMetadata:
    """Create realistic submission metadata."""
    return SubmissionMetadata(
        user_name="Jane Smith",
        presentation_title="Microservices Architecture Decision",
        file_name="architecture-decision-2024.pptx",
        upload_date=datetime.now(timezone.utc).isoformat(),
        audio_duration_seconds=60.0,
        speaker_identified=False,
        user_id=USER_ID,
        submission_id=SUBMISSION_ID,
    )


@pytest.fixture
def mock_s3_client():
    """Create a mock S3 client that captures put_object calls."""
    mock = MagicMock()
    mock.put_object.return_value = {"ResponseMetadata": {"HTTPStatusCode": 200}}
    return mock


@pytest.fixture
def mock_dynamodb_resource():
    """Create a mock DynamoDB resource that captures update_item calls."""
    mock_resource = MagicMock()
    mock_table = MagicMock()
    mock_resource.Table.return_value = mock_table
    mock_table.update_item.return_value = {}
    return mock_resource


# ---------------------------------------------------------------------------
# Integration Test: End-to-End Report Generation
# ---------------------------------------------------------------------------


class TestEndToEndReportGeneration:
    """Integration test for the full report generation pipeline.

    Tests the flow:
    1. CoachingSupervisor.synthesis_pass(results, transcript, metadata) → SynthesizedReport
    2. ReportGeneratorV2.generate(report, user_id, submission_id) → s3_key

    Requirements: 4.1, 4.4, 4.8
    """

    def test_full_pipeline_produces_valid_report(
        self,
        realistic_evaluation_results,
        realistic_transcript,
        submission_metadata,
        mock_s3_client,
        mock_dynamodb_resource,
    ):
        """End-to-end: EvaluationResult[] → SynthesizedReport → HTML → PDF → S3.

        Verifies:
        - SynthesizedReport passes Pydantic validation
        - PDF is valid (%PDF header), non-empty, within 10MB
        - S3 key matches reports/{user_id}/{submission_id}/coaching_report.pdf
        - DynamoDB update_item is called
        """
        # --- Step 1: Run synthesis pass ---
        # We need to mock the Strands Agent since the CoachingSupervisor uses it
        # but synthesis_pass() is a pure data transformation that doesn't call LLM
        with patch("agents.coaching_supervisor.Agent"):
            supervisor = CoachingSupervisor.__new__(CoachingSupervisor)
            # Initialize only what synthesis_pass needs (no LLM dependency)
            supervisor._agent = None

        synthesized_report = supervisor.synthesis_pass(
            results=realistic_evaluation_results,
            transcript=realistic_transcript,
            metadata=submission_metadata,
        )

        # --- Step 2: Verify SynthesizedReport passes Pydantic validation ---
        assert isinstance(synthesized_report, SynthesizedReport)

        # Re-validate by round-tripping through Pydantic
        report_dict = synthesized_report.model_dump()
        re_validated = SynthesizedReport.model_validate(report_dict)
        assert re_validated.report_id == synthesized_report.report_id

        # Verify key structural properties
        assert len(synthesized_report.dimensions) == 7
        assert len(synthesized_report.three_moves) == 3
        assert 0.0 <= synthesized_report.overall_score <= 10.0
        assert synthesized_report.score_band is not None

        # Verify exactly one weakest dimension
        weakest_count = sum(
            1 for d in synthesized_report.dimensions if d.is_weakest
        )
        assert weakest_count == 1

        # --- Step 3: Run report generation pipeline ---
        generator = ReportGeneratorV2(
            bucket_name="test-e2e-bucket",
            s3_client=mock_s3_client,
            dynamodb_resource=mock_dynamodb_resource,
        )

        s3_key = generator.generate(
            report=synthesized_report,
            user_id=USER_ID,
            submission_id=SUBMISSION_ID,
        )

        # --- Step 4: Verify S3 key matches expected path pattern ---
        expected_key = f"reports/{USER_ID}/{SUBMISSION_ID}/coaching_report.pdf"
        assert s3_key == expected_key
        assert re.match(
            r"reports/[\w-]+/[\w-]+/coaching_report\.pdf", s3_key
        )

        # --- Step 5: Verify S3 put_object was called correctly ---
        mock_s3_client.put_object.assert_called_once()
        call_kwargs = mock_s3_client.put_object.call_args[1]

        assert call_kwargs["Bucket"] == "test-e2e-bucket"
        assert call_kwargs["Key"] == expected_key
        assert call_kwargs["ContentType"] == "application/pdf"

        # --- Step 6: Verify PDF is valid ---
        pdf_bytes = call_kwargs["Body"]
        assert isinstance(pdf_bytes, bytes)
        assert len(pdf_bytes) > 0, "PDF must be non-empty"
        assert pdf_bytes[:4] == b"%PDF", "PDF must start with %PDF header"
        assert len(pdf_bytes) <= 10 * 1024 * 1024, "PDF must be within 10MB limit"

        # --- Step 7: Verify DynamoDB update_item was called ---
        mock_dynamodb_resource.Table.assert_called_with("submissions")
        mock_table = mock_dynamodb_resource.Table.return_value
        mock_table.update_item.assert_called_once()

        update_kwargs = mock_table.update_item.call_args[1]
        assert update_kwargs["Key"]["user_id"] == USER_ID
        assert update_kwargs["Key"]["submission_id"] == SUBMISSION_ID
        assert ":status" in update_kwargs["ExpressionAttributeValues"]
        assert (
            update_kwargs["ExpressionAttributeValues"][":status"] == "completed"
        )
        assert (
            update_kwargs["ExpressionAttributeValues"][":s3_key"] == expected_key
        )

    def test_synthesized_report_dimension_caps_enforced(
        self,
        realistic_evaluation_results,
        realistic_transcript,
        submission_metadata,
    ):
        """Synthesis pass enforces per-dimension caps: ≤5 findings, ≤3 strengths."""
        with patch("agents.coaching_supervisor.Agent"):
            supervisor = CoachingSupervisor.__new__(CoachingSupervisor)
            supervisor._agent = None

        report = supervisor.synthesis_pass(
            results=realistic_evaluation_results,
            transcript=realistic_transcript,
            metadata=submission_metadata,
        )

        for dim_entry in report.dimensions:
            assert len(dim_entry.findings) <= 5, (
                f"Dimension '{dim_entry.dimension_name}' has "
                f"{len(dim_entry.findings)} findings (cap is 5)"
            )
            assert len(dim_entry.strengths) <= 3, (
                f"Dimension '{dim_entry.dimension_name}' has "
                f"{len(dim_entry.strengths)} strengths (cap is 3)"
            )

    def test_pdf_size_within_limit(
        self,
        realistic_evaluation_results,
        realistic_transcript,
        submission_metadata,
        mock_s3_client,
        mock_dynamodb_resource,
    ):
        """Generated PDF is within the 10MB size limit (Requirement 4.4)."""
        with patch("agents.coaching_supervisor.Agent"):
            supervisor = CoachingSupervisor.__new__(CoachingSupervisor)
            supervisor._agent = None

        report = supervisor.synthesis_pass(
            results=realistic_evaluation_results,
            transcript=realistic_transcript,
            metadata=submission_metadata,
        )

        generator = ReportGeneratorV2(
            bucket_name="test-e2e-bucket",
            s3_client=mock_s3_client,
            dynamodb_resource=mock_dynamodb_resource,
        )

        generator.generate(
            report=report,
            user_id=USER_ID,
            submission_id=SUBMISSION_ID,
        )

        pdf_bytes = mock_s3_client.put_object.call_args[1]["Body"]
        max_size = 10 * 1024 * 1024  # 10 MB
        assert len(pdf_bytes) <= max_size
        # Also verify it's a reasonable minimum size for a multi-page report
        assert len(pdf_bytes) > 1000, "PDF seems too small for a full report"

    def test_s3_key_path_pattern(
        self,
        realistic_evaluation_results,
        realistic_transcript,
        submission_metadata,
        mock_s3_client,
        mock_dynamodb_resource,
    ):
        """S3 key matches the pattern reports/{user_id}/{submission_id}/coaching_report.pdf."""
        with patch("agents.coaching_supervisor.Agent"):
            supervisor = CoachingSupervisor.__new__(CoachingSupervisor)
            supervisor._agent = None

        report = supervisor.synthesis_pass(
            results=realistic_evaluation_results,
            transcript=realistic_transcript,
            metadata=submission_metadata,
        )

        generator = ReportGeneratorV2(
            bucket_name="test-e2e-bucket",
            s3_client=mock_s3_client,
            dynamodb_resource=mock_dynamodb_resource,
        )

        s3_key = generator.generate(
            report=report,
            user_id=USER_ID,
            submission_id=SUBMISSION_ID,
        )

        # Verify exact path construction
        parts = s3_key.split("/")
        assert parts[0] == "reports"
        assert parts[1] == USER_ID
        assert parts[2] == SUBMISSION_ID
        assert parts[3] == "coaching_report.pdf"

        # Verify with regex pattern
        pattern = r"^reports/[^/]+/[^/]+/coaching_report\.pdf$"
        assert re.match(pattern, s3_key), (
            f"S3 key '{s3_key}' does not match expected pattern"
        )
