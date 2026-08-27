"""Unit tests for synthesis utility functions.

Tests the apply_findings_cap() function and associated ranking/cap logic.
"""

import pytest

from models.synthesized_report import (
    EffortTag,
    ImpactTag,
    Severity,
    SynthesizedFinding,
)
from services.synthesis_utils import _has_evidence, apply_findings_cap


def _make_finding(
    *,
    score: float = 5.0,
    evidence_quote: str | None = None,
    evidence_timestamp_seconds: float | None = None,
    title: str = "Test finding",
) -> SynthesizedFinding:
    """Helper to create a SynthesizedFinding with minimal boilerplate."""
    return SynthesizedFinding(
        severity=Severity.MEDIUM,
        title=title,
        explanation="This is a test explanation for the finding.",
        suggestion="Try doing something differently.",
        effort_tag=EffortTag.MODERATE,
        impact_tag=ImpactTag.MEDIUM,
        evidence_quote=evidence_quote,
        evidence_timestamp_seconds=evidence_timestamp_seconds,
        projected_impact_score=score,
    )


class TestHasEvidence:
    """Tests for the _has_evidence helper."""

    def test_no_evidence(self):
        f = _make_finding()
        assert _has_evidence(f) is False

    def test_has_quote(self):
        f = _make_finding(evidence_quote="Speaker said something")
        assert _has_evidence(f) is True

    def test_has_timestamp(self):
        f = _make_finding(evidence_timestamp_seconds=42.5)
        assert _has_evidence(f) is True

    def test_has_both(self):
        f = _make_finding(
            evidence_quote="Words", evidence_timestamp_seconds=10.0
        )
        assert _has_evidence(f) is True

    def test_empty_quote_no_timestamp(self):
        f = _make_finding(evidence_quote="")
        assert _has_evidence(f) is False


class TestApplyFindingsCap:
    """Tests for apply_findings_cap()."""

    def test_under_cap_returns_unchanged(self):
        findings = [_make_finding(score=i) for i in range(3)]
        result = apply_findings_cap(findings, cap=5)
        assert len(result) == 3
        assert result == findings

    def test_at_cap_returns_unchanged(self):
        findings = [_make_finding(score=i) for i in range(5)]
        result = apply_findings_cap(findings, cap=5)
        assert len(result) == 5

    def test_over_cap_drops_no_evidence_first(self):
        # 3 findings with evidence, 4 without evidence => 7 total
        with_evidence = [
            _make_finding(score=9.0, evidence_quote="Quote A"),
            _make_finding(score=8.0, evidence_quote="Quote B"),
            _make_finding(score=7.0, evidence_timestamp_seconds=5.0),
        ]
        without_evidence = [
            _make_finding(score=6.0, title="No ev 6"),
            _make_finding(score=5.0, title="No ev 5"),
            _make_finding(score=4.0, title="No ev 4"),
            _make_finding(score=3.0, title="No ev 3"),
        ]
        findings = with_evidence + without_evidence
        result = apply_findings_cap(findings, cap=5)

        assert len(result) == 5
        # All 3 evidence findings should survive
        for f in with_evidence:
            assert f in result
        # The 2 highest-impact no-evidence findings should survive
        assert without_evidence[0] in result  # score 6.0
        assert without_evidence[1] in result  # score 5.0

    def test_lowest_impact_no_evidence_dropped_first(self):
        # 6 findings without evidence, cap=5
        findings = [_make_finding(score=float(i)) for i in range(6)]
        result = apply_findings_cap(findings, cap=5)

        assert len(result) == 5
        # The finding with score 0.0 should be dropped (lowest impact)
        scores = [f.projected_impact_score for f in result]
        assert 0.0 not in scores

    def test_drops_evidence_findings_when_no_evidence_exhausted(self):
        # 6 findings all with evidence, cap=5
        findings = [
            _make_finding(score=float(i), evidence_quote=f"Quote {i}")
            for i in range(6)
        ]
        result = apply_findings_cap(findings, cap=5)

        assert len(result) == 5
        # The lowest-impact finding (score 0.0) should be dropped
        scores = [f.projected_impact_score for f in result]
        assert 0.0 not in scores

    def test_result_sorted_descending_by_impact(self):
        findings = [
            _make_finding(score=2.0),
            _make_finding(score=8.0, evidence_quote="Q"),
            _make_finding(score=5.0),
            _make_finding(score=9.0, evidence_timestamp_seconds=1.0),
            _make_finding(score=3.0),
            _make_finding(score=7.0, evidence_quote="R"),
        ]
        result = apply_findings_cap(findings, cap=5)

        scores = [f.projected_impact_score for f in result]
        assert scores == sorted(scores, reverse=True)

    def test_empty_list(self):
        result = apply_findings_cap([], cap=5)
        assert result == []

    def test_custom_cap(self):
        findings = [_make_finding(score=float(i)) for i in range(10)]
        result = apply_findings_cap(findings, cap=3)
        assert len(result) == 3

    def test_cap_of_zero(self):
        findings = [_make_finding(score=5.0)]
        result = apply_findings_cap(findings, cap=0)
        assert len(result) == 0


class TestRankFindings:
    """Tests for CoachingSupervisor._rank_findings() via integration."""

    def test_rank_findings_sorts_descending(self):
        """Verifying _rank_findings sorts by projected_impact_score descending."""
        from unittest.mock import MagicMock

        from agents.coaching_supervisor import CoachingSupervisor

        # Create a supervisor with a mocked registry
        mock_registry = MagicMock()
        mock_registry.get_available_agents.return_value = []
        supervisor = CoachingSupervisor(registry=mock_registry)

        findings = [
            _make_finding(score=3.0),
            _make_finding(score=9.0),
            _make_finding(score=1.0),
            _make_finding(score=7.0),
            _make_finding(score=5.0),
        ]

        ranked = supervisor._rank_findings(findings)

        scores = [f.projected_impact_score for f in ranked]
        assert scores == [9.0, 7.0, 5.0, 3.0, 1.0]

    def test_rank_findings_empty_list(self):
        from unittest.mock import MagicMock

        from agents.coaching_supervisor import CoachingSupervisor

        mock_registry = MagicMock()
        mock_registry.get_available_agents.return_value = []
        supervisor = CoachingSupervisor(registry=mock_registry)

        assert supervisor._rank_findings([]) == []

    def test_rank_findings_single_item(self):
        from unittest.mock import MagicMock

        from agents.coaching_supervisor import CoachingSupervisor

        mock_registry = MagicMock()
        mock_registry.get_available_agents.return_value = []
        supervisor = CoachingSupervisor(registry=mock_registry)

        findings = [_make_finding(score=5.0)]
        ranked = supervisor._rank_findings(findings)
        assert len(ranked) == 1
        assert ranked[0].projected_impact_score == 5.0

    def test_rank_findings_equal_scores_stable(self):
        from unittest.mock import MagicMock

        from agents.coaching_supervisor import CoachingSupervisor

        mock_registry = MagicMock()
        mock_registry.get_available_agents.return_value = []
        supervisor = CoachingSupervisor(registry=mock_registry)

        findings = [
            _make_finding(score=5.0, title="First"),
            _make_finding(score=5.0, title="Second"),
            _make_finding(score=5.0, title="Third"),
        ]
        ranked = supervisor._rank_findings(findings)
        # Python's sorted is stable, so order should be preserved for equal keys
        assert [f.title for f in ranked] == ["First", "Second", "Third"]


class TestApplyCaps:
    """Tests for CoachingSupervisor._apply_caps()."""

    def _get_supervisor(self):
        from unittest.mock import MagicMock

        from agents.coaching_supervisor import CoachingSupervisor

        mock_registry = MagicMock()
        mock_registry.get_available_agents.return_value = []
        return CoachingSupervisor(registry=mock_registry)

    def test_applies_cap_per_dimension(self):
        supervisor = self._get_supervisor()
        findings_by_dim = {
            "delivery": [_make_finding(score=float(i)) for i in range(7)],
            "structure": [_make_finding(score=float(i)) for i in range(3)],
        }
        result = supervisor._apply_caps(findings_by_dim)

        assert len(result["delivery"]) == 5
        assert len(result["structure"]) == 3

    def test_empty_dimensions(self):
        supervisor = self._get_supervisor()
        result = supervisor._apply_caps({})
        assert result == {}

    def test_dimension_at_cap(self):
        supervisor = self._get_supervisor()
        findings_by_dim = {
            "pacing": [_make_finding(score=float(i)) for i in range(5)],
        }
        result = supervisor._apply_caps(findings_by_dim)
        assert len(result["pacing"]) == 5

    def test_evidence_prioritized_in_cap(self):
        supervisor = self._get_supervisor()
        # 6 findings: 2 with evidence (low impact), 4 without evidence (high impact)
        findings = [
            _make_finding(score=1.0, evidence_quote="Evidence A"),
            _make_finding(score=2.0, evidence_timestamp_seconds=10.0),
            _make_finding(score=9.0, title="No ev 9"),
            _make_finding(score=8.0, title="No ev 8"),
            _make_finding(score=7.0, title="No ev 7"),
            _make_finding(score=6.0, title="No ev 6"),
        ]
        findings_by_dim = {"delivery": findings}
        result = supervisor._apply_caps(findings_by_dim)

        # Should keep all 5: both evidence findings survive, lowest-impact no-evidence dropped
        assert len(result["delivery"]) == 5
        # Both evidence findings must survive
        evidence_scores = [
            f.projected_impact_score
            for f in result["delivery"]
            if f.evidence_quote or f.evidence_timestamp_seconds is not None
        ]
        assert 1.0 in evidence_scores
        assert 2.0 in evidence_scores
