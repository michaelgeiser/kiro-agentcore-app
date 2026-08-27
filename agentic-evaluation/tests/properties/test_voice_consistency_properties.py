# Feature: coaching-report-v2, Property 18: Voice consistency
"""Property-based test for coaching prose voice consistency.

Property 18: Coaching prose uses second-person voice and excludes speaker identity
— For any SynthesizedReport with a known user_name, the coaching prose fields
(two_sentence_verdict, lede_paragraph, diagnosis_paragraph, all finding
explanations, suggestions, drill instructions, and swap pair try_instead fields)
SHALL contain at least one second-person pronoun ("you" or "your") in aggregate,
and SHALL NOT contain the user_name string.

**Validates: Requirements 15.1, 15.2**
"""

import json
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st
from hypothesis.strategies import composite

from agents.coaching_supervisor import CoachingSupervisor, SubmissionMetadata
from agents.registry import AgentRegistry
from models.data_models import EvaluationResult, Finding
from models.synthesized_report import SynthesizedReport
from services.transcript_metrics import TranscriptData, WordTiming


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

# Strategy for user names: single-word and multi-word names.
# We filter to avoid very short names (<2 chars) since _strip_name_from_text
# only processes names of 2+ chars, and avoid whitespace-only names.
single_word_name = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll")),
    min_size=2,
    max_size=20,
)

multi_word_name = st.builds(
    lambda parts: " ".join(parts),
    st.lists(
        st.text(
            alphabet=st.characters(whitelist_categories=("Lu", "Ll")),
            min_size=2,
            max_size=15,
        ),
        min_size=2,
        max_size=4,
    ),
)

# Generate varied user names including single word, multi-word, and realistic names
user_name_strategy = st.one_of(
    single_word_name,
    multi_word_name,
    # Realistic names
    st.sampled_from([
        "John",
        "Maria Garcia",
        "Jean-Pierre Dupont",
        "Dr Sarah Thompson",
        "Li Wei",
        "Mohammed Al-Hassan",
        "Björk Guðmundsdóttir",
        "Anna Marie Johnson",
        "Bob",
        "Valentina Rossi",
    ]),
)


@composite
def valid_finding_model(draw):
    """Generate a valid Finding (from data_models) for EvaluationResult."""
    return Finding(
        category=draw(
            st.text(
                alphabet=st.characters(whitelist_categories=("L",)),
                min_size=3,
                max_size=20,
            )
        ),
        detail=draw(
            st.text(
                alphabet=st.characters(whitelist_categories=("L", "N", "Zs")),
                min_size=5,
                max_size=60,
            )
        ),
        severity=draw(severity_st),
        suggestion=draw(
            st.text(
                alphabet=st.characters(whitelist_categories=("L", "N", "Zs")),
                min_size=5,
                max_size=60,
            )
        ),
    )


@composite
def valid_evaluation_result(draw, dimension: str):
    """Generate a valid EvaluationResult for a given dimension."""
    score = draw(valid_score)
    findings = draw(st.lists(valid_finding_model(), min_size=1, max_size=3))
    strengths = draw(
        st.lists(
            st.text(
                alphabet=st.characters(whitelist_categories=("L", "N", "Zs")),
                min_size=5,
                max_size=40,
            ),
            min_size=0,
            max_size=3,
        )
    )
    return EvaluationResult(
        dimension=dimension,
        score=score,
        findings=findings,
        strengths=strengths,
        improvements=[],
        agent_id=f"{dimension.lower().replace(' ', '_')}-evaluator-v1",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@composite
def evaluation_results_all_7(draw):
    """Generate EvaluationResults for all 7 dimensions with at least some findings."""
    results = []
    for dim in ALL_DIMENSIONS:
        result = draw(valid_evaluation_result(dimension=dim))
        results.append(result)
    return results


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
    """Create a CoachingSupervisor with a mocked agent."""
    manifest_path = _create_manifest()
    registry = AgentRegistry(manifest_path=manifest_path)
    mock_agent = MagicMock()
    supervisor = CoachingSupervisor(registry=registry, agent=mock_agent)
    return supervisor


def _make_transcript_data() -> TranscriptData:
    """Create minimal valid TranscriptData for synthesis_pass."""
    words = [
        WordTiming(word="Hello", start_seconds=0.0, end_seconds=0.5, confidence=0.95),
        WordTiming(word="world", start_seconds=0.6, end_seconds=1.0, confidence=0.90),
        WordTiming(word="this", start_seconds=1.1, end_seconds=1.4, confidence=0.88),
        WordTiming(word="is", start_seconds=1.5, end_seconds=1.7, confidence=0.92),
        WordTiming(word="a", start_seconds=1.8, end_seconds=1.9, confidence=0.95),
        WordTiming(word="test", start_seconds=2.0, end_seconds=2.4, confidence=0.91),
    ]
    return TranscriptData(words=words, close_start_seconds=2.0)


def _collect_coaching_prose(report: SynthesizedReport) -> str:
    """Collect all coaching prose fields from a SynthesizedReport into one string.

    Coaching prose fields per the requirement:
    - two_sentence_verdict
    - lede_paragraph
    - diagnosis_paragraph
    - All finding explanations and suggestions (across all dimensions)
    - All swap pair try_instead fields
    - All drill instructions
    """
    prose_parts = [
        report.two_sentence_verdict,
        report.lede_paragraph,
        report.diagnosis_paragraph,
    ]

    for dim_entry in report.dimensions:
        for finding in dim_entry.findings:
            prose_parts.append(finding.explanation)
            prose_parts.append(finding.suggestion)
        if dim_entry.swap_pair is not None:
            prose_parts.append(dim_entry.swap_pair.try_instead)
        if dim_entry.practice_drill is not None:
            prose_parts.append(dim_entry.practice_drill.instructions)

    return " ".join(prose_parts)


def _contains_second_person(text: str) -> bool:
    """Check if text contains at least one second-person pronoun ('you' or 'your')."""
    return bool(re.search(r"\b(you|your)\b", text, re.IGNORECASE))


def _contains_user_name(text: str, user_name: str) -> bool:
    """Check if text contains the user_name (case-insensitive word boundary match)."""
    if not user_name or len(user_name.strip()) < 2:
        return False
    # Use word boundary matching consistent with the implementation
    pattern = re.compile(r"\b" + re.escape(user_name.strip()) + r"\b", re.IGNORECASE)
    return bool(pattern.search(text))


# ---------------------------------------------------------------------------
# Property 18: Coaching prose uses second-person voice and excludes speaker identity
# ---------------------------------------------------------------------------


@pytest.mark.property
@settings(max_examples=50, deadline=15000)
@given(
    user_name=user_name_strategy,
    results=evaluation_results_all_7(),
)
def test_coaching_prose_contains_second_person_pronoun(
    user_name: str,
    results: list[EvaluationResult],
) -> None:
    """For any SynthesizedReport with a known user_name, the coaching prose fields
    SHALL contain at least one second-person pronoun ("you" or "your") in aggregate.

    **Validates: Requirements 15.1**
    """
    # Filter out degenerate names
    assume(len(user_name.strip()) >= 2)

    supervisor = _make_supervisor()
    transcript = _make_transcript_data()
    metadata = SubmissionMetadata(
        user_name=user_name,
        presentation_title="Test Presentation",
        file_name="test_recording.mp3",
        upload_date=datetime.now(timezone.utc).isoformat(),
        audio_duration_seconds=120.0,
        speaker_identified=False,
        user_id="user-123",
        submission_id="sub-456",
    )

    report = supervisor.synthesis_pass(results, transcript, metadata)

    # Collect all coaching prose
    all_prose = _collect_coaching_prose(report)

    # Assert: at least one second-person pronoun in aggregate
    assert _contains_second_person(all_prose), (
        f"No second-person pronoun ('you' or 'your') found in coaching prose "
        f"for user_name='{user_name}'. "
        f"Prose sample (first 200 chars): '{all_prose[:200]}...'"
    )


@pytest.mark.property
@settings(max_examples=50, deadline=15000)
@given(
    user_name=user_name_strategy,
    results=evaluation_results_all_7(),
)
def test_coaching_prose_excludes_user_name(
    user_name: str,
    results: list[EvaluationResult],
) -> None:
    """For any SynthesizedReport with a known user_name, the coaching prose fields
    SHALL NOT contain the user_name string.

    **Validates: Requirements 15.2**
    """
    # Filter out degenerate names
    assume(len(user_name.strip()) >= 2)

    supervisor = _make_supervisor()
    transcript = _make_transcript_data()
    metadata = SubmissionMetadata(
        user_name=user_name,
        presentation_title="Test Presentation",
        file_name="test_recording.mp3",
        upload_date=datetime.now(timezone.utc).isoformat(),
        audio_duration_seconds=120.0,
        speaker_identified=False,
        user_id="user-123",
        submission_id="sub-456",
    )

    report = supervisor.synthesis_pass(results, transcript, metadata)

    # Collect all coaching prose
    all_prose = _collect_coaching_prose(report)

    # Assert: user_name does NOT appear in coaching prose
    assert not _contains_user_name(all_prose, user_name), (
        f"user_name='{user_name}' was found in coaching prose. "
        f"The coaching prose must use second-person voice only. "
        f"Prose sample (first 300 chars): '{all_prose[:300]}...'"
    )
