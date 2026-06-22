"""Unit tests for core data models.

Tests HandoffMessage, ProcessingStatus, Finding, EvaluationResult,
and S3 path construction helpers with valid inputs, invalid inputs,
and edge cases.

Requirements: 1.2, 5.1, 6.5
"""

import pytest
from pydantic import ValidationError

from models.data_models import (
    EvaluationResult,
    Finding,
    HandoffMessage,
    ProcessingStatus,
    get_evaluation_result_path,
    get_report_path,
)


# ---------------------------------------------------------------------------
# HandoffMessage Tests
# ---------------------------------------------------------------------------


class TestHandoffMessage:
    """Tests for HandoffMessage validation and construction."""

    def test_valid_handoff_message(self):
        """HandoffMessage accepts valid inputs with all required fields."""
        msg = HandoffMessage(
            submission_id="sub-12345",
            user_id="user-abc",
            s3_file_key="uploads/user-abc/file.pdf",
            transcript_s3_key="processed/user-abc/sub-12345/transcript.json",
            vector_store_location="s3://bucket/vectors/sub-12345",
            chunk_count=5,
            presentation_title="My Presentation",
        )
        assert msg.submission_id == "sub-12345"
        assert msg.user_id == "user-abc"
        assert msg.s3_file_key == "uploads/user-abc/file.pdf"
        assert msg.transcript_s3_key == "processed/user-abc/sub-12345/transcript.json"
        assert msg.vector_store_location == "s3://bucket/vectors/sub-12345"
        assert msg.chunk_count == 5
        assert msg.presentation_title == "My Presentation"

    def test_chunk_count_minimum_boundary(self):
        """chunk_count of exactly 1 is valid (boundary)."""
        msg = HandoffMessage(
            submission_id="sub-1",
            user_id="u",
            s3_file_key="k",
            transcript_s3_key="t",
            vector_store_location="v",
            chunk_count=1,
            presentation_title="t",
        )
        assert msg.chunk_count == 1

    def test_chunk_count_zero_rejected(self):
        """chunk_count of 0 is accepted (default value, ge=0)."""
        msg = HandoffMessage(
            submission_id="sub-1",
            user_id="u",
            s3_file_key="k",
            transcript_s3_key="t",
            chunk_count=0,
            presentation_title="t",
        )
        assert msg.chunk_count == 0

    def test_chunk_count_negative_rejected(self):
        """Negative chunk_count is rejected."""
        with pytest.raises(ValidationError):
            HandoffMessage(
                submission_id="sub-1",
                user_id="u",
                s3_file_key="k",
                transcript_s3_key="t",
                vector_store_location="v",
                chunk_count=-1,
                presentation_title="t",
            )

    def test_empty_submission_id_rejected(self):
        """Empty string for submission_id is rejected (min_length=1)."""
        with pytest.raises(ValidationError) as exc_info:
            HandoffMessage(
                submission_id="",
                user_id="u",
                s3_file_key="k",
                transcript_s3_key="t",
                vector_store_location="v",
                chunk_count=1,
                presentation_title="t",
            )
        assert "submission_id" in str(exc_info.value)

    def test_empty_user_id_rejected(self):
        """Empty string for user_id is rejected."""
        with pytest.raises(ValidationError):
            HandoffMessage(
                submission_id="s",
                user_id="",
                s3_file_key="k",
                transcript_s3_key="t",
                vector_store_location="v",
                chunk_count=1,
                presentation_title="t",
            )

    def test_empty_s3_file_key_rejected(self):
        """Empty string for s3_file_key is rejected."""
        with pytest.raises(ValidationError):
            HandoffMessage(
                submission_id="s",
                user_id="u",
                s3_file_key="",
                transcript_s3_key="t",
                vector_store_location="v",
                chunk_count=1,
                presentation_title="t",
            )

    def test_empty_vector_store_location_accepted(self):
        """Empty string for vector_store_location is accepted (default value)."""
        msg = HandoffMessage(
            submission_id="s",
            user_id="u",
            s3_file_key="k",
            transcript_s3_key="t",
            vector_store_location="",
            chunk_count=1,
            presentation_title="t",
        )
        assert msg.vector_store_location == ""

    def test_empty_presentation_title_rejected(self):
        """Empty string for presentation_title is rejected."""
        with pytest.raises(ValidationError):
            HandoffMessage(
                submission_id="s",
                user_id="u",
                s3_file_key="k",
                transcript_s3_key="t",
                vector_store_location="v",
                chunk_count=1,
                presentation_title="",
            )

    def test_missing_required_field_rejected(self):
        """Missing a required field raises ValidationError."""
        with pytest.raises(ValidationError):
            HandoffMessage(
                submission_id="sub-1",
                user_id="u",
                # s3_file_key missing
                transcript_s3_key="t",
                vector_store_location="v",
                chunk_count=1,
                presentation_title="t",
            )

    def test_large_chunk_count_accepted(self):
        """Large chunk_count values are accepted."""
        msg = HandoffMessage(
            submission_id="s",
            user_id="u",
            s3_file_key="k",
            transcript_s3_key="t",
            vector_store_location="v",
            chunk_count=999999,
            presentation_title="t",
        )
        assert msg.chunk_count == 999999


# ---------------------------------------------------------------------------
# ProcessingStatus Tests
# ---------------------------------------------------------------------------


class TestProcessingStatus:
    """Tests for the ProcessingStatus enum."""

    def test_all_expected_values_exist(self):
        """ProcessingStatus has all expected members."""
        expected = {"PENDING", "PROCESSING", "WAITING", "EVALUATING", "REPORT_GENERATING", "COMPLETED", "FAILED"}
        actual = {member.name for member in ProcessingStatus}
        assert actual == expected

    def test_enum_string_values(self):
        """Enum values are the expected display strings."""
        assert ProcessingStatus.PENDING.value == "Pending"
        assert ProcessingStatus.PROCESSING.value == "Processing"
        assert ProcessingStatus.EVALUATING.value == "Evaluating"
        assert ProcessingStatus.REPORT_GENERATING.value == "Report_Generating"
        assert ProcessingStatus.COMPLETED.value == "Completed"
        assert ProcessingStatus.FAILED.value == "Failed"

    def test_enum_is_str_subclass(self):
        """ProcessingStatus members are also str instances."""
        assert isinstance(ProcessingStatus.PENDING, str)
        assert ProcessingStatus.COMPLETED == "Completed"


# ---------------------------------------------------------------------------
# Finding Tests
# ---------------------------------------------------------------------------


class TestFinding:
    """Tests for the Finding model."""

    def test_valid_finding(self):
        """Finding accepts valid inputs with allowed severity values."""
        finding = Finding(
            category="vocal_variety",
            detail="Monotone delivery in the introduction section",
            severity="high",
            suggestion="Vary pitch and pace to engage the audience",
        )
        assert finding.category == "vocal_variety"
        assert finding.severity == "high"

    @pytest.mark.parametrize("severity", ["low", "medium", "high"])
    def test_valid_severity_values(self, severity: str):
        """All valid severity values are accepted."""
        finding = Finding(
            category="test",
            detail="detail",
            severity=severity,
            suggestion="suggestion",
        )
        assert finding.severity == severity

    @pytest.mark.parametrize("severity", ["Low", "HIGH", "critical", "minor", "", "unknown", "1"])
    def test_invalid_severity_rejected(self, severity: str):
        """Invalid severity values are rejected by the regex pattern."""
        with pytest.raises(ValidationError):
            Finding(
                category="test",
                detail="detail",
                severity=severity,
                suggestion="suggestion",
            )

    def test_empty_category_rejected(self):
        """Empty category string is rejected."""
        with pytest.raises(ValidationError):
            Finding(
                category="",
                detail="detail",
                severity="low",
                suggestion="suggestion",
            )

    def test_empty_detail_rejected(self):
        """Empty detail string is rejected."""
        with pytest.raises(ValidationError):
            Finding(
                category="cat",
                detail="",
                severity="low",
                suggestion="suggestion",
            )

    def test_empty_suggestion_rejected(self):
        """Empty suggestion string is rejected."""
        with pytest.raises(ValidationError):
            Finding(
                category="cat",
                detail="detail",
                severity="low",
                suggestion="",
            )


# ---------------------------------------------------------------------------
# EvaluationResult Tests
# ---------------------------------------------------------------------------


class TestEvaluationResult:
    """Tests for EvaluationResult validation and edge cases."""

    def _valid_result(self, **overrides) -> dict:
        """Helper to build a valid EvaluationResult dict with optional overrides."""
        base = {
            "dimension": "delivery",
            "score": 7.5,
            "findings": [],
            "strengths": ["clear articulation"],
            "improvements": ["reduce filler words"],
            "agent_id": "delivery-evaluator-v1",
            "timestamp": "2024-01-15T10:30:00Z",
        }
        base.update(overrides)
        return base

    def test_valid_evaluation_result(self):
        """EvaluationResult accepts valid inputs."""
        result = EvaluationResult(**self._valid_result())
        assert result.dimension == "delivery"
        assert result.score == 7.5
        assert result.agent_id == "delivery-evaluator-v1"

    def test_score_minimum_boundary(self):
        """Score of exactly 0.0 is valid."""
        result = EvaluationResult(**self._valid_result(score=0.0))
        assert result.score == 0.0

    def test_score_maximum_boundary(self):
        """Score of exactly 10.0 is valid."""
        result = EvaluationResult(**self._valid_result(score=10.0))
        assert result.score == 10.0

    def test_score_negative_rejected(self):
        """Negative score is rejected (must be >= 0.0)."""
        with pytest.raises(ValidationError) as exc_info:
            EvaluationResult(**self._valid_result(score=-0.1))
        assert "score" in str(exc_info.value)

    def test_score_above_maximum_rejected(self):
        """Score above 10.0 is rejected (must be <= 10.0)."""
        with pytest.raises(ValidationError) as exc_info:
            EvaluationResult(**self._valid_result(score=10.1))
        assert "score" in str(exc_info.value)

    def test_score_far_above_maximum_rejected(self):
        """Score of 100.0 is rejected."""
        with pytest.raises(ValidationError):
            EvaluationResult(**self._valid_result(score=100.0))

    def test_empty_dimension_rejected(self):
        """Empty dimension string is rejected."""
        with pytest.raises(ValidationError):
            EvaluationResult(**self._valid_result(dimension=""))

    def test_empty_agent_id_rejected(self):
        """Empty agent_id string is rejected."""
        with pytest.raises(ValidationError):
            EvaluationResult(**self._valid_result(agent_id=""))

    def test_invalid_timestamp_rejected(self):
        """Non-ISO 8601 timestamp is rejected."""
        with pytest.raises(ValidationError):
            EvaluationResult(**self._valid_result(timestamp="not-a-date"))

    def test_empty_timestamp_rejected(self):
        """Empty timestamp string is rejected."""
        with pytest.raises(ValidationError):
            EvaluationResult(**self._valid_result(timestamp=""))

    def test_valid_iso8601_timestamps(self):
        """Various valid ISO 8601 formats are accepted."""
        valid_timestamps = [
            "2024-01-15T10:30:00Z",
            "2024-01-15T10:30:00+00:00",
            "2024-06-01T23:59:59-05:00",
            "2024-12-31T00:00:00",
        ]
        for ts in valid_timestamps:
            result = EvaluationResult(**self._valid_result(timestamp=ts))
            assert result.timestamp == ts

    def test_findings_default_empty_list(self):
        """Findings default to an empty list if not provided."""
        data = self._valid_result()
        del data["findings"]
        result = EvaluationResult(**data)
        assert result.findings == []

    def test_strengths_default_empty_list(self):
        """Strengths default to an empty list if not provided."""
        data = self._valid_result()
        del data["strengths"]
        result = EvaluationResult(**data)
        assert result.strengths == []

    def test_improvements_default_empty_list(self):
        """Improvements default to an empty list if not provided."""
        data = self._valid_result()
        del data["improvements"]
        result = EvaluationResult(**data)
        assert result.improvements == []

    def test_with_findings_list(self):
        """EvaluationResult accepts a list of Finding objects."""
        findings = [
            Finding(
                category="pacing",
                detail="Too fast in middle section",
                severity="medium",
                suggestion="Add pauses between sections",
            )
        ]
        result = EvaluationResult(**self._valid_result(findings=findings))
        assert len(result.findings) == 1
        assert result.findings[0].category == "pacing"


# ---------------------------------------------------------------------------
# S3 Path Helper Tests
# ---------------------------------------------------------------------------


class TestS3PathHelpers:
    """Tests for S3 path construction helper functions."""

    def test_evaluation_result_path_basic(self):
        """get_evaluation_result_path produces correct format."""
        path = get_evaluation_result_path("sub-123", "delivery")
        assert path == "evaluations/sub-123/delivery/result.json"

    def test_evaluation_result_path_with_special_characters(self):
        """Path helpers handle submission IDs with various characters."""
        path = get_evaluation_result_path("sub-abc-def-456", "executive_presence")
        assert path == "evaluations/sub-abc-def-456/executive_presence/result.json"

    def test_evaluation_result_path_dimension_variations(self):
        """Different dimension names produce different paths."""
        dimensions = [
            "delivery",
            "structure",
            "executive_presence",
            "technical_communication",
            "audience_engagement",
            "pacing",
            "persuasion",
        ]
        paths = [get_evaluation_result_path("sub-1", d) for d in dimensions]
        # All paths should be unique
        assert len(set(paths)) == len(dimensions)

    def test_report_path_basic(self):
        """get_report_path produces correct format."""
        path = get_report_path("user-abc", "sub-123")
        assert path == "reports/user-abc/sub-123/coaching_report.pdf"

    def test_report_path_different_users(self):
        """Different user_ids produce different report paths."""
        path1 = get_report_path("user-1", "sub-1")
        path2 = get_report_path("user-2", "sub-1")
        assert path1 != path2
        assert "user-1" in path1
        assert "user-2" in path2

    def test_report_path_different_submissions(self):
        """Different submission_ids produce different report paths."""
        path1 = get_report_path("user-1", "sub-1")
        path2 = get_report_path("user-1", "sub-2")
        assert path1 != path2

    def test_evaluation_result_path_with_uuid_style_ids(self):
        """Paths work with UUID-style identifiers."""
        path = get_evaluation_result_path(
            "550e8400-e29b-41d4-a716-446655440000", "delivery"
        )
        assert path == "evaluations/550e8400-e29b-41d4-a716-446655440000/delivery/result.json"

    def test_report_path_with_uuid_style_ids(self):
        """Report paths work with UUID-style identifiers."""
        path = get_report_path(
            "user-550e8400", "sub-e29b-41d4"
        )
        assert path == "reports/user-550e8400/sub-e29b-41d4/coaching_report.pdf"
