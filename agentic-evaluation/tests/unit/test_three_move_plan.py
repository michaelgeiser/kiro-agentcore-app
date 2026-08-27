"""Unit tests for Three Move Plan derivation methods.

Tests _derive_three_moves, _generate_strengths_to_protect, and
_generate_diagnosis_paragraph methods on the CoachingSupervisor class.

Requirements: 1.5, 1.11, 1.12
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from agents.coaching_supervisor import CoachingSupervisor
from models.data_models import EvaluationResult, Finding
from models.synthesized_report import (
    EffortTag,
    ImpactTag,
    Severity,
    SynthesizedFinding,
    ThreeMove,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_supervisor() -> CoachingSupervisor:
    """Create a CoachingSupervisor with a mock registry for testing."""
    registry = MagicMock()
    registry.get_available_agents.return_value = []
    with patch("agents.coaching_supervisor.importlib.import_module"):
        supervisor = CoachingSupervisor(registry=registry)
    return supervisor


def _make_finding(
    title: str = "Test finding",
    score: float = 5.0,
    severity: Severity = Severity.HIGH,
    explanation: str = "You need to improve your delivery technique.",
    suggestion: str = "Try slowing down and emphasizing key points.",
    projected_impact: float = 7.5,
    cross_dimension_note: str | None = None,
) -> SynthesizedFinding:
    """Create a SynthesizedFinding for testing."""
    return SynthesizedFinding(
        severity=severity,
        title=title[:80],
        explanation=explanation,
        suggestion=suggestion,
        effort_tag=EffortTag.MODERATE,
        impact_tag=ImpactTag.HIGH if severity == Severity.HIGH else ImpactTag.MEDIUM,
        evidence_quote=None,
        evidence_timestamp_seconds=None,
        cross_dimension_note=cross_dimension_note,
        projected_impact_score=projected_impact,
    )


def _make_evaluation_result(
    dimension: str, score: float = 7.5, strengths: list[str] | None = None
) -> EvaluationResult:
    """Create a test EvaluationResult."""
    return EvaluationResult(
        dimension=dimension,
        score=score,
        findings=[],
        strengths=strengths or [f"Good {dimension} skills"],
        improvements=[],
        agent_id=f"{dimension}-evaluator-v1",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


# ---------------------------------------------------------------------------
# _derive_three_moves tests
# ---------------------------------------------------------------------------


class TestDeriveThreeMoves:
    """Tests for _derive_three_moves method.

    Requirements: 1.5, 1.11
    """

    def test_returns_exactly_three_moves(self):
        """_derive_three_moves returns exactly 3 ThreeMove objects."""
        supervisor = _make_supervisor()
        findings = [
            _make_finding(title="Delivery improvement needed", projected_impact=9.0),
            _make_finding(title="Structure reorganization", projected_impact=8.0),
            _make_finding(title="Pacing adjustment needed", projected_impact=7.0),
            _make_finding(title="Lower priority item", projected_impact=5.0),
        ]

        result = supervisor._derive_three_moves(findings)

        assert len(result) == 3

    def test_moves_preserve_impact_scores(self):
        """ThreeMove impact scores correspond to the top 3 findings' scores."""
        supervisor = _make_supervisor()
        findings = [
            _make_finding(title="Top finding", projected_impact=9.5),
            _make_finding(title="Second finding", projected_impact=8.2),
            _make_finding(title="Third finding", projected_impact=7.1),
            _make_finding(title="Fourth finding", projected_impact=4.0),
        ]

        result = supervisor._derive_three_moves(findings)

        assert result[0].projected_impact_score == 9.5
        assert result[1].projected_impact_score == 8.2
        assert result[2].projected_impact_score == 7.1

    def test_title_max_60_chars(self):
        """ThreeMove titles are capped at 60 characters."""
        supervisor = _make_supervisor()
        long_title = "A" * 80  # Exceeds 60 char limit
        findings = [
            _make_finding(title=long_title, projected_impact=9.0),
            _make_finding(title="Short title", projected_impact=8.0),
            _make_finding(title="Another short title", projected_impact=7.0),
        ]

        result = supervisor._derive_three_moves(findings)

        assert len(result[0].title) <= 60

    def test_coaching_advice_max_150_words(self):
        """ThreeMove coaching_advice is capped at 150 words."""
        supervisor = _make_supervisor()
        # Explanation limited to 100 words, suggestion to 80 words
        # Combined they exceed 150 words, so the method should cap it
        long_explanation = " ".join(["word"] * 100)
        long_suggestion = " ".join(["advice"] * 80)
        findings = [
            _make_finding(
                title="Finding one",
                projected_impact=9.0,
                explanation=long_explanation,
                suggestion=long_suggestion,
            ),
            _make_finding(title="Finding two", projected_impact=8.0),
            _make_finding(title="Finding three", projected_impact=7.0),
        ]

        result = supervisor._derive_three_moves(findings)

        assert len(result[0].coaching_advice.split()) <= 150

    def test_dimensions_lifted_non_empty(self):
        """Each ThreeMove has at least one dimension in dimensions_lifted."""
        supervisor = _make_supervisor()
        findings = [
            _make_finding(title="Delivery issue", projected_impact=9.0),
            _make_finding(title="Structure problem", projected_impact=8.0),
            _make_finding(title="Pacing concern", projected_impact=7.0),
        ]

        result = supervisor._derive_three_moves(findings)

        for move in result:
            assert len(move.dimensions_lifted) >= 1

    def test_dimensions_lifted_from_cross_dimension_note(self):
        """dimensions_lifted includes dimensions from cross_dimension_note."""
        supervisor = _make_supervisor()
        findings = [
            _make_finding(
                title="Delivery weakness",
                projected_impact=9.0,
                cross_dimension_note="Also impacts: Structure, Pacing",
            ),
            _make_finding(title="Other finding", projected_impact=8.0),
            _make_finding(title="Third finding", projected_impact=7.0),
        ]

        result = supervisor._derive_three_moves(findings)

        # Should include Structure and Pacing from the cross_dimension_note
        # plus Delivery from the title
        assert "Delivery" in result[0].dimensions_lifted
        assert "Structure" in result[0].dimensions_lifted
        assert "Pacing" in result[0].dimensions_lifted

    def test_projected_impact_score_in_valid_range(self):
        """All projected_impact_scores are between 0.0 and 10.0."""
        supervisor = _make_supervisor()
        findings = [
            _make_finding(title="A", projected_impact=10.0),
            _make_finding(title="B", projected_impact=0.0),
            _make_finding(title="C", projected_impact=5.5),
        ]

        result = supervisor._derive_three_moves(findings)

        for move in result:
            assert 0.0 <= move.projected_impact_score <= 10.0


# ---------------------------------------------------------------------------
# _generate_strengths_to_protect tests
# ---------------------------------------------------------------------------


class TestGenerateStrengthsToProtect:
    """Tests for _generate_strengths_to_protect method.

    Requirements: 1.12
    """

    def test_returns_max_4_strengths(self):
        """strengths_to_protect has at most 4 items."""
        supervisor = _make_supervisor()
        results = [
            _make_evaluation_result(
                "delivery", strengths=["Strong voice.", "Good energy.", "Clear tone."]
            ),
            _make_evaluation_result(
                "structure", strengths=["Logical flow.", "Clean transitions."]
            ),
        ]

        result = supervisor._generate_strengths_to_protect(results)

        assert len(result) <= 4

    def test_returns_at_least_1_strength(self):
        """strengths_to_protect always has at least 1 item."""
        supervisor = _make_supervisor()
        results = [_make_evaluation_result("delivery", strengths=[])]

        result = supervisor._generate_strengths_to_protect(results)

        assert len(result) >= 1

    def test_each_strength_max_30_words(self):
        """Each strength is at most 30 words."""
        supervisor = _make_supervisor()
        long_strength = " ".join(["word"] * 40)
        results = [_make_evaluation_result("delivery", strengths=[long_strength])]

        result = supervisor._generate_strengths_to_protect(results)

        for s in result:
            assert len(s.split()) <= 31  # +1 for potential period

    def test_prioritizes_higher_scoring_dimensions(self):
        """Strengths from higher-scoring dimensions come first."""
        supervisor = _make_supervisor()
        results = [
            _make_evaluation_result("delivery", score=9.0, strengths=["Exceptional delivery."]),
            _make_evaluation_result("structure", score=4.0, strengths=["Basic structure."]),
        ]

        result = supervisor._generate_strengths_to_protect(results)

        # First strength should be from the higher-scoring dimension
        assert "delivery" in result[0].lower() or "Exceptional" in result[0]

    def test_deduplicates_strengths(self):
        """Duplicate strengths (case-insensitive) are removed."""
        supervisor = _make_supervisor()
        results = [
            _make_evaluation_result("delivery", strengths=["Good voice control."]),
            _make_evaluation_result("pacing", strengths=["Good voice control."]),
        ]

        result = supervisor._generate_strengths_to_protect(results)

        assert len(result) == 1


# ---------------------------------------------------------------------------
# _generate_diagnosis_paragraph tests
# ---------------------------------------------------------------------------


class TestGenerateDiagnosisParagraph:
    """Tests for _generate_diagnosis_paragraph method.

    Requirements: 1.12
    """

    def test_returns_non_empty_string(self):
        """diagnosis_paragraph is never empty."""
        supervisor = _make_supervisor()
        moves = [
            ThreeMove(
                title="Improve delivery",
                coaching_advice="Focus on vocal variety.",
                projected_impact_score=9.0,
                dimensions_lifted=["Delivery"],
            ),
            ThreeMove(
                title="Better structure",
                coaching_advice="Organize your key points clearly.",
                projected_impact_score=8.0,
                dimensions_lifted=["Structure"],
            ),
            ThreeMove(
                title="Engage audience",
                coaching_advice="Use questions to involve listeners.",
                projected_impact_score=7.0,
                dimensions_lifted=["Audience Engagement"],
            ),
        ]

        result = supervisor._generate_diagnosis_paragraph(moves)

        assert len(result) > 0

    def test_max_150_words(self):
        """diagnosis_paragraph is at most 150 words."""
        supervisor = _make_supervisor()
        moves = [
            ThreeMove(
                title="A" * 60,
                coaching_advice="Advice " * 50,
                projected_impact_score=9.0,
                dimensions_lifted=["Delivery"],
            ),
            ThreeMove(
                title="B" * 60,
                coaching_advice="More advice " * 50,
                projected_impact_score=8.0,
                dimensions_lifted=["Structure"],
            ),
            ThreeMove(
                title="C" * 60,
                coaching_advice="Even more advice " * 50,
                projected_impact_score=7.0,
                dimensions_lifted=["Pacing"],
            ),
        ]

        result = supervisor._generate_diagnosis_paragraph(moves)

        assert len(result.split()) <= 150

    def test_references_move_titles(self):
        """diagnosis_paragraph references the move titles."""
        supervisor = _make_supervisor()
        moves = [
            ThreeMove(
                title="Improve vocal variety",
                coaching_advice="Work on tone modulation.",
                projected_impact_score=9.0,
                dimensions_lifted=["Delivery"],
            ),
            ThreeMove(
                title="Strengthen opening",
                coaching_advice="Start with a hook.",
                projected_impact_score=8.0,
                dimensions_lifted=["Structure"],
            ),
            ThreeMove(
                title="Add audience questions",
                coaching_advice="Engage with queries.",
                projected_impact_score=7.0,
                dimensions_lifted=["Audience Engagement"],
            ),
        ]

        result = supervisor._generate_diagnosis_paragraph(moves)

        assert "Improve vocal variety" in result
        assert "Strengthen opening" in result
        assert "Add audience questions" in result

    def test_uses_second_person_voice(self):
        """diagnosis_paragraph uses second-person pronouns."""
        supervisor = _make_supervisor()
        moves = [
            ThreeMove(
                title="Better delivery",
                coaching_advice="Focus on clarity.",
                projected_impact_score=9.0,
                dimensions_lifted=["Delivery"],
            ),
            ThreeMove(
                title="Better structure",
                coaching_advice="Organize points.",
                projected_impact_score=8.0,
                dimensions_lifted=["Structure"],
            ),
            ThreeMove(
                title="Better pacing",
                coaching_advice="Slow down.",
                projected_impact_score=7.0,
                dimensions_lifted=["Pacing"],
            ),
        ]

        result = supervisor._generate_diagnosis_paragraph(moves)

        # Should contain "Your" or "you" (second person)
        lower_result = result.lower()
        assert "your" in lower_result or "you" in lower_result

    def test_handles_empty_moves_gracefully(self):
        """diagnosis_paragraph handles empty moves list."""
        supervisor = _make_supervisor()

        result = supervisor._generate_diagnosis_paragraph([])

        assert len(result) > 0
        assert len(result.split()) <= 150
