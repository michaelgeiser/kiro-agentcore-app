# Feature: coaching-report-v2, Properties 16, 17: Swap Pair and Practice Drill rules
"""Property-based tests for Swap Pair evidence rule and Practice Drill findings rule.

Property 16: Swap pair presence follows evidence rule — For any dimension in a
SynthesizedReport, swap_pair SHALL be non-null if and only if that dimension has
at least one finding with an evidence_quote of 10 or more characters. When swap_pair
is non-null, the you_said field SHALL be between 10 and 280 characters.

Property 17: Practice drill presence follows findings rule — For any dimension in a
SynthesizedReport, practice_drill SHALL be non-null if and only if that dimension has
at least one finding. When non-null, time_box_minutes SHALL be in [2, 15] and
instructions SHALL be between 50 and 500 characters.

Validates: Requirements 11.1, 11.4, 12.1, 12.4
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st
from hypothesis.strategies import composite

from agents.coaching_supervisor import CoachingSupervisor
from agents.registry import AgentRegistry
from models.synthesized_report import (
    EffortTag,
    ImpactTag,
    PracticeDrill,
    Severity,
    SwapPair,
    SynthesizedFinding,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALL_DIMENSIONS = [
    "delivery",
    "structure",
    "executive_presence",
    "technical_communication",
    "audience_engagement",
    "pacing",
    "persuasion",
]

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


@composite
def evidence_quote_with_length(draw, min_len: int = 10, max_len: int = 200):
    """Generate an evidence quote string with controlled length."""
    length = draw(st.integers(min_value=min_len, max_value=max_len))
    # Use printable ASCII chars to avoid encoding issues
    return draw(
        st.text(
            alphabet=st.characters(
                whitelist_categories=("L", "N", "Zs"),
                whitelist_characters=".,!?'-",
            ),
            min_size=length,
            max_size=length,
        )
    )


@composite
def short_evidence_quote(draw):
    """Generate an evidence quote that is too short (< 10 chars)."""
    length = draw(st.integers(min_value=1, max_value=9))
    return draw(
        st.text(
            alphabet=st.characters(whitelist_categories=("L",)),
            min_size=length,
            max_size=length,
        )
    )


@composite
def valid_finding_with_evidence(draw):
    """Generate a SynthesizedFinding that has a valid evidence_quote (≥10 chars)."""
    quote = draw(evidence_quote_with_length(min_len=10, max_len=200))
    return SynthesizedFinding(
        severity=draw(st.sampled_from(list(Severity))),
        title=draw(
            st.text(
                min_size=1,
                max_size=60,
                alphabet=st.characters(whitelist_categories=("L", "N", "Zs")),
            )
        ),
        explanation="You need to work on improving your delivery in this section.",
        suggestion="Try slowing down and enunciating more clearly.",
        effort_tag=draw(st.sampled_from(list(EffortTag))),
        impact_tag=draw(st.sampled_from(list(ImpactTag))),
        evidence_quote=quote,
        evidence_timestamp_seconds=draw(
            st.one_of(st.none(), st.floats(min_value=0.0, max_value=3600.0))
        ),
        cross_dimension_note=None,
        projected_impact_score=draw(
            st.floats(min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False)
        ),
    )


@composite
def valid_finding_without_evidence(draw):
    """Generate a SynthesizedFinding with no evidence_quote or one < 10 chars."""
    use_short = draw(st.booleans())
    if use_short:
        quote = draw(short_evidence_quote())
    else:
        quote = None

    return SynthesizedFinding(
        severity=draw(st.sampled_from(list(Severity))),
        title=draw(
            st.text(
                min_size=1,
                max_size=60,
                alphabet=st.characters(whitelist_categories=("L", "N", "Zs")),
            )
        ),
        explanation="You need to work on improving your delivery in this section.",
        suggestion="Try slowing down and enunciating more clearly.",
        effort_tag=draw(st.sampled_from(list(EffortTag))),
        impact_tag=draw(st.sampled_from(list(ImpactTag))),
        evidence_quote=quote,
        evidence_timestamp_seconds=None,
        cross_dimension_note=None,
        projected_impact_score=draw(
            st.floats(min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False)
        ),
    )


@composite
def findings_by_dim_strategy(draw):
    """Generate a findings_by_dim dict with random dimensions and findings.

    Returns a tuple of (findings_by_dim, dims_with_evidence, dims_with_findings)
    so tests can assert the expected behavior.
    """
    # Choose a subset of dimensions to include (at least 1)
    num_dims = draw(st.integers(min_value=1, max_value=7))
    chosen_dims = draw(
        st.lists(
            st.sampled_from(ALL_DIMENSIONS),
            min_size=num_dims,
            max_size=num_dims,
            unique=True,
        )
    )

    findings_by_dim: dict[str, list[SynthesizedFinding]] = {}
    dims_with_evidence: set[str] = set()
    dims_with_findings: set[str] = set()

    for dim in chosen_dims:
        # Decide: no findings, findings without evidence, or findings with evidence
        scenario = draw(st.sampled_from(["empty", "no_evidence", "with_evidence", "mixed"]))

        if scenario == "empty":
            findings_by_dim[dim] = []
        elif scenario == "no_evidence":
            num_findings = draw(st.integers(min_value=1, max_value=5))
            findings = [draw(valid_finding_without_evidence()) for _ in range(num_findings)]
            findings_by_dim[dim] = findings
            dims_with_findings.add(dim)
        elif scenario == "with_evidence":
            num_findings = draw(st.integers(min_value=1, max_value=5))
            findings = [draw(valid_finding_with_evidence()) for _ in range(num_findings)]
            findings_by_dim[dim] = findings
            dims_with_evidence.add(dim)
            dims_with_findings.add(dim)
        else:  # mixed
            num_with = draw(st.integers(min_value=1, max_value=3))
            num_without = draw(st.integers(min_value=1, max_value=2))
            findings_with = [draw(valid_finding_with_evidence()) for _ in range(num_with)]
            findings_without = [draw(valid_finding_without_evidence()) for _ in range(num_without)]
            findings_by_dim[dim] = findings_with + findings_without
            dims_with_evidence.add(dim)
            dims_with_findings.add(dim)

    return findings_by_dim, dims_with_evidence, dims_with_findings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_minimal_manifest() -> Path:
    """Create a minimal agent manifest for constructing CoachingSupervisor."""
    agents_data = []
    for dim in ALL_DIMENSIONS:
        agents_data.append(
            {
                "agent_id": f"{dim}-evaluator-v1",
                "dimension": dim,
                "display_name": f"{dim.replace('_', ' ').title()} Evaluator",
                "description": f"Evaluates {dim}.",
                "version": "1.0.0",
                "enabled": True,
                "tool_module": f"agents.{dim}_evaluator",
            }
        )

    manifest = {"agents": agents_data}
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    )
    json.dump(manifest, tmp, indent=2)
    tmp.close()
    return Path(tmp.name)


def _create_supervisor() -> CoachingSupervisor:
    """Create a CoachingSupervisor instance for testing generation methods."""
    manifest_path = _create_minimal_manifest()
    try:
        registry = AgentRegistry(manifest_path=manifest_path)
    finally:
        manifest_path.unlink(missing_ok=True)

    mock_agent = MagicMock()
    return CoachingSupervisor(registry=registry, agent=mock_agent)


# ---------------------------------------------------------------------------
# Property 16: Swap pair presence follows evidence rule
# ---------------------------------------------------------------------------


@pytest.mark.property
@settings(max_examples=100, deadline=5000)
@given(data=findings_by_dim_strategy())
def test_swap_pair_present_iff_evidence_exists(
    data: tuple[dict[str, list[SynthesizedFinding]], set[str], set[str]],
) -> None:
    """For any dimension in a SynthesizedReport, swap_pair SHALL be non-null
    if and only if that dimension has at least one finding with an evidence_quote
    of 10 or more characters.

    **Validates: Requirements 11.1**
    """
    findings_by_dim, dims_with_evidence, _ = data

    supervisor = _create_supervisor()
    swap_pairs = supervisor._generate_swap_pairs(findings_by_dim)

    for dim, findings in findings_by_dim.items():
        # Check if the dimension actually has qualifying evidence
        has_evidence = any(
            f.evidence_quote is not None and len(f.evidence_quote) >= 10
            for f in findings
        )

        swap_pair = swap_pairs.get(dim)

        if has_evidence:
            assert swap_pair is not None, (
                f"Dimension '{dim}' has findings with evidence_quote ≥10 chars, "
                f"but swap_pair is None. "
                f"Findings evidence quotes: {[f.evidence_quote for f in findings]}"
            )
        else:
            assert swap_pair is None, (
                f"Dimension '{dim}' has no finding with evidence_quote ≥10 chars, "
                f"but swap_pair is not None. "
                f"Findings evidence quotes: {[f.evidence_quote for f in findings]}"
            )


@pytest.mark.property
@settings(max_examples=100, deadline=5000)
@given(data=findings_by_dim_strategy())
def test_swap_pair_you_said_length_constraints(
    data: tuple[dict[str, list[SynthesizedFinding]], set[str], set[str]],
) -> None:
    """When swap_pair is non-null, the you_said field SHALL be between 10 and
    280 characters.

    **Validates: Requirements 11.1, 11.4**
    """
    findings_by_dim, _, _ = data

    supervisor = _create_supervisor()
    swap_pairs = supervisor._generate_swap_pairs(findings_by_dim)

    for dim, swap_pair in swap_pairs.items():
        if swap_pair is not None:
            assert 10 <= len(swap_pair.you_said) <= 280, (
                f"Dimension '{dim}': swap_pair.you_said has length "
                f"{len(swap_pair.you_said)}, expected between 10 and 280. "
                f"Value: '{swap_pair.you_said[:50]}...'"
            )


@pytest.mark.property
@settings(max_examples=100, deadline=5000)
@given(data=findings_by_dim_strategy())
def test_swap_pair_try_instead_length_constraint(
    data: tuple[dict[str, list[SynthesizedFinding]], set[str], set[str]],
) -> None:
    """When swap_pair is non-null, the try_instead field SHALL not exceed
    400 characters.

    **Validates: Requirements 11.1**
    """
    findings_by_dim, _, _ = data

    supervisor = _create_supervisor()
    swap_pairs = supervisor._generate_swap_pairs(findings_by_dim)

    for dim, swap_pair in swap_pairs.items():
        if swap_pair is not None:
            assert len(swap_pair.try_instead) <= 400, (
                f"Dimension '{dim}': swap_pair.try_instead has length "
                f"{len(swap_pair.try_instead)}, expected ≤ 400."
            )


# ---------------------------------------------------------------------------
# Property 17: Practice drill presence follows findings rule
# ---------------------------------------------------------------------------


@pytest.mark.property
@settings(max_examples=100, deadline=5000)
@given(data=findings_by_dim_strategy())
def test_practice_drill_present_iff_findings_exist(
    data: tuple[dict[str, list[SynthesizedFinding]], set[str], set[str]],
) -> None:
    """For any dimension in a SynthesizedReport, practice_drill SHALL be non-null
    if and only if that dimension has at least one finding.

    **Validates: Requirements 12.1**
    """
    findings_by_dim, _, dims_with_findings = data

    supervisor = _create_supervisor()
    drills = supervisor._generate_practice_drills(findings_by_dim)

    for dim, findings in findings_by_dim.items():
        has_findings = len(findings) > 0
        drill = drills.get(dim)

        if has_findings:
            assert drill is not None, (
                f"Dimension '{dim}' has {len(findings)} finding(s), "
                f"but practice_drill is None."
            )
        else:
            assert drill is None, (
                f"Dimension '{dim}' has no findings, "
                f"but practice_drill is not None."
            )


@pytest.mark.property
@settings(max_examples=100, deadline=5000)
@given(data=findings_by_dim_strategy())
def test_practice_drill_time_box_in_range(
    data: tuple[dict[str, list[SynthesizedFinding]], set[str], set[str]],
) -> None:
    """When practice_drill is non-null, time_box_minutes SHALL be in [2, 15].

    **Validates: Requirements 12.1, 12.4**
    """
    findings_by_dim, _, _ = data

    supervisor = _create_supervisor()
    drills = supervisor._generate_practice_drills(findings_by_dim)

    for dim, drill in drills.items():
        if drill is not None:
            assert 2 <= drill.time_box_minutes <= 15, (
                f"Dimension '{dim}': practice_drill.time_box_minutes = "
                f"{drill.time_box_minutes}, expected in [2, 15]."
            )


@pytest.mark.property
@settings(max_examples=100, deadline=5000)
@given(data=findings_by_dim_strategy())
def test_practice_drill_instructions_length_constraints(
    data: tuple[dict[str, list[SynthesizedFinding]], set[str], set[str]],
) -> None:
    """When practice_drill is non-null, instructions SHALL be between 50 and
    500 characters.

    **Validates: Requirements 12.1, 12.4**
    """
    findings_by_dim, _, _ = data

    supervisor = _create_supervisor()
    drills = supervisor._generate_practice_drills(findings_by_dim)

    for dim, drill in drills.items():
        if drill is not None:
            assert 50 <= len(drill.instructions) <= 500, (
                f"Dimension '{dim}': practice_drill.instructions has length "
                f"{len(drill.instructions)}, expected between 50 and 500. "
                f"Value: '{drill.instructions[:80]}...'"
            )
