# Feature: coaching-report-v2, Properties 1–6: Synthesis pass correctness
"""Property-based tests for the Coaching Supervisor synthesis pass.

Covers:
- Property 1: Synthesis produces valid output from any valid evaluation results
- Property 2: Duplicate collapse merges same-category findings with impact note
- Property 3: Global ranking is sorted descending by Projected Impact Score
- Property 4: Three Move Plan derives from the top-3 ranked findings
- Property 5: Per-dimension caps are enforced
- Property 6: Finding drop priority preserves evidence over impact

Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.10, 1.13
"""

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st
from hypothesis.strategies import composite

from agents.coaching_supervisor import CoachingSupervisor, SubmissionMetadata
from agents.registry import AgentRegistry
from models.data_models import EvaluationResult, Finding
from models.synthesized_report import (
    DimensionEntry,
    EffortTag,
    ImpactTag,
    Severity,
    SynthesizedFinding,
    SynthesizedReport,
)
from services.synthesis_utils import apply_findings_cap

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

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

valid_score = st.floats(
    min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False
)

severity_st = st.sampled_from(["low", "medium", "high"])

# Short safe text for categories/details (letters, digits, spaces only)
safe_text = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "Zs")),
    min_size=1,
    max_size=40,
)

# A category string for findings — limited to avoid duplication unless intended
category_st = st.text(
    alphabet=st.characters(whitelist_categories=("L",)),
    min_size=3,
    max_size=20,
)


@composite
def valid_finding_model(draw):
    """Generate a valid Finding (from data_models)."""
    return Finding(
        category=draw(category_st),
        detail=draw(safe_text),
        severity=draw(severity_st),
        suggestion=draw(safe_text),
    )


@composite
def valid_evaluation_result(draw, dimension=None, findings=None):
    """Generate a valid EvaluationResult for a given or random dimension."""
    dim = dimension or draw(st.sampled_from(ALL_DIMENSIONS))
    score = draw(valid_score)
    if findings is None:
        findings = draw(st.lists(valid_finding_model(), min_size=0, max_size=4))
    strengths = draw(
        st.lists(safe_text, min_size=0, max_size=4)
    )
    return EvaluationResult(
        dimension=dim,
        score=score,
        findings=findings,
        strengths=strengths,
        improvements=[],
        agent_id=f"{dim.lower().replace(' ', '_')}-evaluator-v1",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@composite
def valid_synthesized_finding(draw, has_evidence=None):
    """Generate a valid SynthesizedFinding with controllable evidence."""
    if has_evidence is None:
        has_evidence = draw(st.booleans())

    evidence_quote = None
    evidence_timestamp = None
    if has_evidence:
        # Either quote or timestamp or both
        choice = draw(st.integers(min_value=0, max_value=2))
        if choice == 0:
            evidence_quote = "You said something here that needs work"
        elif choice == 1:
            evidence_timestamp = draw(
                st.floats(min_value=0.0, max_value=3600.0, allow_nan=False, allow_infinity=False)
            )
        else:
            evidence_quote = "You said something here that needs work"
            evidence_timestamp = draw(
                st.floats(min_value=0.0, max_value=3600.0, allow_nan=False, allow_infinity=False)
            )

    return SynthesizedFinding(
        severity=draw(st.sampled_from(list(Severity))),
        title=draw(
            st.text(
                alphabet=st.characters(whitelist_categories=("L", "N", "Zs")),
                min_size=1,
                max_size=80,
            )
        ),
        explanation="You need to work on improving your delivery in this area.",
        suggestion="Try speaking more slowly and with clearer enunciation.",
        effort_tag=draw(st.sampled_from(list(EffortTag))),
        impact_tag=draw(st.sampled_from(list(ImpactTag))),
        evidence_quote=evidence_quote,
        evidence_timestamp_seconds=evidence_timestamp,
        projected_impact_score=draw(valid_score),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_manifest() -> Path:
    """Create a temporary agent manifest for CoachingSupervisor."""
    agents_data = []
    for dim in ALL_DIMENSIONS:
        dim_id = dim.lower().replace(" ", "_")
        agents_data.append(
            {
                "agent_id": f"{dim_id}-evaluator-v1",
                "dimension": dim_id,
                "display_name": f"{dim} Evaluator",
                "description": f"Evaluates {dim}.",
                "version": "1.0.0",
                "enabled": True,
                "tool_module": f"agents.{dim_id}_evaluator",
            }
        )
    manifest = {"agents": agents_data}
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    )
    json.dump(manifest, tmp, indent=2)
    tmp.close()
    return Path(tmp.name)


def _make_supervisor() -> CoachingSupervisor:
    """Create a CoachingSupervisor instance with mocked agent."""
    manifest_path = _create_manifest()
    registry = AgentRegistry(manifest_path=manifest_path)
    mock_agent = MagicMock()
    supervisor = CoachingSupervisor(registry=registry, agent=mock_agent)
    return supervisor


def _make_transcript_data():
    """Create minimal valid TranscriptData for synthesis_pass."""
    from services.transcript_metrics import TranscriptData, WordTiming

    words = [
        WordTiming(word="Hello", start_seconds=0.0, end_seconds=0.5, confidence=0.95),
        WordTiming(word="world", start_seconds=0.6, end_seconds=1.0, confidence=0.90),
        WordTiming(word="this", start_seconds=1.1, end_seconds=1.4, confidence=0.88),
        WordTiming(word="is", start_seconds=1.5, end_seconds=1.7, confidence=0.92),
        WordTiming(word="a", start_seconds=1.8, end_seconds=1.9, confidence=0.95),
        WordTiming(word="test", start_seconds=2.0, end_seconds=2.4, confidence=0.91),
    ]
    return TranscriptData(words=words, close_start_seconds=2.0)


def _make_metadata() -> SubmissionMetadata:
    """Create valid SubmissionMetadata for synthesis_pass."""
    return SubmissionMetadata(
        user_name="Test User",
        presentation_title="Test Presentation",
        file_name="test_recording.mp3",
        upload_date=datetime.now(timezone.utc).isoformat(),
        audio_duration_seconds=120.0,
        speaker_identified=False,
        user_id="user-123",
        submission_id="sub-456",
    )


# ---------------------------------------------------------------------------
# Property 1: Synthesis produces valid output from any valid evaluation results
# ---------------------------------------------------------------------------


@composite
def evaluation_results_1_to_7(draw):
    """Generate 1 to 7 EvaluationResults with unique dimensions."""
    num_dims = draw(st.integers(min_value=1, max_value=7))
    dims = draw(
        st.lists(
            st.sampled_from(ALL_DIMENSIONS),
            min_size=num_dims,
            max_size=num_dims,
            unique=True,
        )
    )
    results = []
    for dim in dims:
        result = draw(valid_evaluation_result(dimension=dim))
        results.append(result)
    return results


@pytest.mark.property
@settings(max_examples=50, deadline=10000)
@given(results=evaluation_results_1_to_7())
def test_synthesis_produces_valid_output(results: list[EvaluationResult]) -> None:
    """For any list of 1 to 7 valid EvaluationResult objects, synthesis_pass()
    SHALL produce a valid SynthesizedReport that passes Pydantic validation.

    **Validates: Requirements 1.1, 1.13**
    """
    supervisor = _make_supervisor()
    transcript = _make_transcript_data()
    metadata = _make_metadata()

    # Execute the synthesis pass
    report = supervisor.synthesis_pass(results, transcript, metadata)

    # Assert output is a valid SynthesizedReport (Pydantic would have raised on construction)
    assert isinstance(report, SynthesizedReport)

    # Verify dimensions list always has exactly 7 entries
    assert len(report.dimensions) == 7

    # Verify three_moves has exactly 3 entries
    assert len(report.three_moves) == 3

    # Verify score fields are in valid ranges
    assert 0.0 <= report.overall_score <= 10.0
    assert report.distance_to_next_band >= 0.0


# ---------------------------------------------------------------------------
# Property 2: Duplicate collapse merges same-category findings with impact note
# ---------------------------------------------------------------------------


@composite
def evaluation_results_with_shared_category(draw):
    """Generate EvaluationResults where ≥3 dimensions share a category.

    Ensures the collapse condition (≥3 agents raising same category) is met.
    """
    # Pick at least 3 dimensions that will share a category
    num_sharing = draw(st.integers(min_value=3, max_value=7))
    sharing_dims = draw(
        st.lists(
            st.sampled_from(ALL_DIMENSIONS),
            min_size=num_sharing,
            max_size=num_sharing,
            unique=True,
        )
    )

    # The shared category
    shared_category = "shared_behavior_category"

    results = []
    for dim in sharing_dims:
        # Create a finding with the shared category
        shared_finding = Finding(
            category=shared_category,
            detail=f"Issue observed in {dim}",
            severity=draw(severity_st),
            suggestion=f"Improve this aspect in {dim}",
        )
        # May have additional unique findings
        other_findings = draw(
            st.lists(valid_finding_model(), min_size=0, max_size=2)
        )
        all_findings = [shared_finding] + other_findings

        result = EvaluationResult(
            dimension=dim,
            score=draw(valid_score),
            findings=all_findings,
            strengths=["Good effort."],
            improvements=[],
            agent_id=f"{dim.lower().replace(' ', '_')}-evaluator-v1",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        results.append(result)

    return results, shared_category


@pytest.mark.property
@settings(max_examples=50, deadline=10000)
@given(data=evaluation_results_with_shared_category())
def test_duplicate_collapse_merges_with_impact_note(
    data: tuple[list[EvaluationResult], str],
) -> None:
    """For any set of EvaluationResult objects where 3 or more dimensions contain
    findings with the same category field, _collapse_duplicates() SHALL produce
    exactly one surviving finding for that category, attributed to the dimension
    with the lowest score, with a non-null cross_dimension_note of at most
    120 characters.

    **Validates: Requirements 1.2, 1.3**
    """
    results, shared_category = data
    supervisor = _make_supervisor()

    # Run collapse
    collapsed = supervisor._collapse_duplicates(results)

    # Find the collapsed finding for our shared category
    collapsed_for_category = [
        f for f in collapsed if f.title.startswith(shared_category[:80])
    ]

    # Exactly one collapsed finding for the shared category
    assert len(collapsed_for_category) == 1, (
        f"Expected exactly 1 collapsed finding for '{shared_category}', "
        f"got {len(collapsed_for_category)}"
    )

    collapsed_finding = collapsed_for_category[0]

    # cross_dimension_note must be non-null and ≤120 characters
    assert collapsed_finding.cross_dimension_note is not None, (
        "Collapsed finding must have a non-null cross_dimension_note"
    )
    assert len(collapsed_finding.cross_dimension_note) <= 120, (
        f"cross_dimension_note exceeds 120 chars: "
        f"{len(collapsed_finding.cross_dimension_note)}"
    )

    # The finding should be attributed to the dimension with the lowest score
    # (i.e., projected_impact_score = 10.0 - lowest_score)
    lowest_score = min(r.score for r in results)
    expected_impact = round(10.0 - lowest_score, 1)
    expected_impact = max(0.0, min(10.0, expected_impact))
    assert collapsed_finding.projected_impact_score == expected_impact, (
        f"Expected projected_impact_score={expected_impact} (from lowest "
        f"score={lowest_score}), got {collapsed_finding.projected_impact_score}"
    )


# ---------------------------------------------------------------------------
# Property 3: Global ranking is sorted descending by Projected Impact Score
# ---------------------------------------------------------------------------


@pytest.mark.property
@settings(max_examples=100, deadline=5000)
@given(
    findings=st.lists(valid_synthesized_finding(), min_size=1, max_size=20)
)
def test_rank_findings_sorted_descending(
    findings: list[SynthesizedFinding],
) -> None:
    """For any list of SynthesizedFinding objects, _rank_findings() SHALL return
    them in strictly non-increasing order of projected_impact_score.

    **Validates: Requirements 1.4**
    """
    supervisor = _make_supervisor()

    ranked = supervisor._rank_findings(findings)

    # Verify non-increasing order
    for i in range(len(ranked) - 1):
        assert ranked[i].projected_impact_score >= ranked[i + 1].projected_impact_score, (
            f"Ranking violated at index {i}: "
            f"{ranked[i].projected_impact_score} < {ranked[i + 1].projected_impact_score}"
        )

    # Verify same set of findings (no loss or duplication)
    assert len(ranked) == len(findings)


# ---------------------------------------------------------------------------
# Property 4: Three Move Plan derives from the top-3 ranked findings
# ---------------------------------------------------------------------------


@composite
def ranked_findings_at_least_3(draw):
    """Generate a list of ≥3 SynthesizedFindings with distinct impact scores."""
    count = draw(st.integers(min_value=3, max_value=15))
    findings = draw(
        st.lists(valid_synthesized_finding(), min_size=count, max_size=count)
    )
    return findings


@pytest.mark.property
@settings(max_examples=50, deadline=10000)
@given(findings=ranked_findings_at_least_3())
def test_three_moves_derive_from_top3(
    findings: list[SynthesizedFinding],
) -> None:
    """For any globally-ranked findings list of length ≥ 3, the three_moves list
    SHALL contain entries whose projected_impact_score values correspond to the
    three highest values in the ranked findings list.

    **Validates: Requirements 1.5**
    """
    supervisor = _make_supervisor()

    # Rank the findings first (as synthesis_pass would)
    ranked = supervisor._rank_findings(findings)

    # Derive three moves
    three_moves = supervisor._derive_three_moves(ranked)

    # The three_moves should have projected_impact_scores matching top-3 ranked
    top_3_scores = [f.projected_impact_score for f in ranked[:3]]
    move_scores = [m.projected_impact_score for m in three_moves]

    assert move_scores == top_3_scores, (
        f"Three moves scores {move_scores} do not match "
        f"top-3 ranked scores {top_3_scores}"
    )


# ---------------------------------------------------------------------------
# Property 5: Per-dimension caps are enforced
# ---------------------------------------------------------------------------


@pytest.mark.property
@settings(max_examples=50, deadline=10000)
@given(results=evaluation_results_1_to_7())
def test_per_dimension_caps_enforced(results: list[EvaluationResult]) -> None:
    """For any SynthesizedReport, every DimensionEntry SHALL have at most
    5 findings and at most 3 strengths.

    **Validates: Requirements 1.6, 1.7**
    """
    supervisor = _make_supervisor()
    transcript = _make_transcript_data()
    metadata = _make_metadata()

    report = supervisor.synthesis_pass(results, transcript, metadata)

    for dim_entry in report.dimensions:
        assert len(dim_entry.findings) <= 5, (
            f"Dimension '{dim_entry.dimension_name}' has {len(dim_entry.findings)} "
            f"findings, exceeding cap of 5"
        )
        assert len(dim_entry.strengths) <= 3, (
            f"Dimension '{dim_entry.dimension_name}' has {len(dim_entry.strengths)} "
            f"strengths, exceeding cap of 3"
        )


# ---------------------------------------------------------------------------
# Property 6: Finding drop priority preserves evidence over impact
# ---------------------------------------------------------------------------


@composite
def findings_exceeding_cap(draw):
    """Generate a list of >5 SynthesizedFindings with a mix of evidence/no-evidence."""
    count = draw(st.integers(min_value=6, max_value=12))
    # Generate some with evidence and some without
    findings = []
    for _ in range(count):
        has_evidence = draw(st.booleans())
        f = draw(valid_synthesized_finding(has_evidence=has_evidence))
        findings.append(f)
    return findings


@pytest.mark.property
@settings(max_examples=100, deadline=5000)
@given(findings=findings_exceeding_cap())
def test_findings_cap_preserves_evidence_over_impact(
    findings: list[SynthesizedFinding],
) -> None:
    """For any list of SynthesizedFinding objects exceeding the cap of 5,
    apply_findings_cap() SHALL drop findings without evidence before those with
    evidence, and within each group, lower projected_impact_score findings are
    dropped first.

    **Validates: Requirements 1.10**
    """
    assume(len(findings) > 5)

    result = apply_findings_cap(findings, cap=5)

    # Result must not exceed cap
    assert len(result) <= 5, f"Cap not enforced: got {len(result)} findings"

    # Partition original findings into evidence / no-evidence groups
    original_with_evidence = [
        f for f in findings
        if f.evidence_quote or f.evidence_timestamp_seconds is not None
    ]
    original_no_evidence = [
        f for f in findings
        if not f.evidence_quote and f.evidence_timestamp_seconds is None
    ]

    # Partition result into evidence / no-evidence groups
    result_with_evidence = [
        f for f in result
        if f.evidence_quote or f.evidence_timestamp_seconds is not None
    ]
    result_no_evidence = [
        f for f in result
        if not f.evidence_quote and f.evidence_timestamp_seconds is None
    ]

    # Key assertion: if any no-evidence findings survived in the result,
    # then ALL evidence findings must also have survived (evidence preserved first)
    if result_no_evidence:
        assert len(result_with_evidence) == len(original_with_evidence), (
            "Evidence findings were dropped before no-evidence findings. "
            f"Original with evidence: {len(original_with_evidence)}, "
            f"Result with evidence: {len(result_with_evidence)}, "
            f"Result without evidence: {len(result_no_evidence)}"
        )

    # Within each group, survivors should have higher or equal impact than dropped
    # Check no-evidence group: dropped items should have lower impact than survivors
    dropped_no_evidence = [
        f for f in original_no_evidence if f not in result_no_evidence
    ]
    if result_no_evidence and dropped_no_evidence:
        min_surviving_no_evidence = min(
            f.projected_impact_score for f in result_no_evidence
        )
        for dropped in dropped_no_evidence:
            assert dropped.projected_impact_score <= min_surviving_no_evidence, (
                f"A no-evidence finding with score {dropped.projected_impact_score} "
                f"was dropped while one with {min_surviving_no_evidence} survived"
            )

    # Check evidence group: if any evidence findings were dropped, they should
    # have lower impact than survivors
    dropped_with_evidence = [
        f for f in original_with_evidence if f not in result_with_evidence
    ]
    if result_with_evidence and dropped_with_evidence:
        min_surviving_evidence = min(
            f.projected_impact_score for f in result_with_evidence
        )
        for dropped in dropped_with_evidence:
            assert dropped.projected_impact_score <= min_surviving_evidence, (
                f"An evidence finding with score {dropped.projected_impact_score} "
                f"was dropped while one with {min_surviving_evidence} survived"
            )
