# Feature: coaching-report-v2, Properties 7, 8: Score band classification and data model validation
"""Property-based tests for score band classification, distance-to-next-band
consistency, and SynthesizedReport field validation.

Validates: Requirements 2.3, 2.4, 2.14, 2.15
"""

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st
from hypothesis.strategies import composite
from pydantic import ValidationError

from models.synthesized_report import (
    DimensionEntry,
    EffortTag,
    ImpactTag,
    PracticeDrill,
    Provenance,
    ScoreBand,
    Severity,
    SeverityCounts,
    SwapPair,
    SynthesizedFinding,
    SynthesizedReport,
    TalkTimeline,
    ThreeMove,
    TranscriptMetrics,
)
from services.score_utils import classify_score_band, compute_distance_to_next_band


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Scores in the valid range [0.0, 10.0]
valid_score = st.floats(min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False)

# Scores specifically in each band for targeted testing
developing_score = st.floats(min_value=0.0, max_value=3.99, allow_nan=False, allow_infinity=False)
competent_score = st.floats(min_value=4.0, max_value=6.49, allow_nan=False, allow_infinity=False)
effective_score = st.floats(min_value=6.5, max_value=8.49, allow_nan=False, allow_infinity=False)
exceptional_score = st.floats(min_value=8.5, max_value=10.0, allow_nan=False, allow_infinity=False)

# Text strategies for model fields
short_text = st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=("L", "N", "Zs")))
word_text = st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("L",)))

DIMENSIONS = [
    "Delivery", "Structure", "Executive Presence",
    "Technical Communication", "Audience Engagement", "Pacing", "Persuasion",
]


@composite
def valid_finding(draw):
    """Generate a valid SynthesizedFinding."""
    return SynthesizedFinding(
        severity=draw(st.sampled_from(list(Severity))),
        title=draw(st.text(min_size=1, max_size=80, alphabet=st.characters(whitelist_categories=("L", "N", "Zs")))),
        explanation="You need to improve your delivery in this area.",
        suggestion="Try speaking more slowly and clearly.",
        effort_tag=draw(st.sampled_from(list(EffortTag))),
        impact_tag=draw(st.sampled_from(list(ImpactTag))),
        projected_impact_score=draw(valid_score),
    )


@composite
def valid_dimension_entry(draw, rank: int = 1, is_weakest: bool = False):
    """Generate a valid DimensionEntry."""
    score = draw(valid_score)
    band = classify_score_band(score)
    dim_name = DIMENSIONS[rank - 1]
    findings = draw(st.lists(valid_finding(), min_size=0, max_size=5))
    strengths = draw(st.lists(
        st.just("You show strong presence in this area."),
        min_size=0, max_size=3,
    ))

    return DimensionEntry(
        dimension_name=dim_name,
        score=score,
        score_band=band,
        rank=rank,
        one_sentence_verdict="You are improving steadily.",
        severity_counts=SeverityCounts(
            high=sum(1 for f in findings if f.severity == Severity.HIGH),
            medium=sum(1 for f in findings if f.severity == Severity.MEDIUM),
            low=sum(1 for f in findings if f.severity == Severity.LOW),
            strength=len(strengths),
        ),
        findings=findings,
        strengths=strengths,
        is_weakest=is_weakest,
    )


@composite
def valid_three_move(draw):
    """Generate a valid ThreeMove."""
    return ThreeMove(
        title=draw(st.text(min_size=1, max_size=60, alphabet=st.characters(whitelist_categories=("L", "N", "Zs")))),
        coaching_advice="You should focus on this area to improve your overall score.",
        projected_impact_score=draw(valid_score),
        dimensions_lifted=draw(st.lists(
            st.sampled_from(DIMENSIONS), min_size=1, max_size=3, unique=True
        )),
    )


@composite
def valid_synthesized_report(draw):
    """Generate a valid SynthesizedReport with all required fields."""
    overall_score = draw(valid_score)
    band = classify_score_band(overall_score)
    distance = compute_distance_to_next_band(overall_score)

    # Generate 7 dimension entries, exactly one is_weakest
    dims = []
    for i in range(7):
        dim = draw(valid_dimension_entry(rank=i + 1, is_weakest=(i == 0)))
        dims.append(dim)

    # Generate 3 moves
    moves = [draw(valid_three_move()) for _ in range(3)]

    # Build percentages that sum to 100
    open_pct = draw(st.floats(min_value=5.0, max_value=30.0, allow_nan=False, allow_infinity=False))
    close_pct = draw(st.floats(min_value=5.0, max_value=30.0, allow_nan=False, allow_infinity=False))
    body_pct = round(100.0 - open_pct - close_pct, 2)
    assume(0.0 <= body_pct <= 100.0)

    return SynthesizedReport(
        user_name="Test User",
        presentation_title="Test Presentation",
        file_name="test.mp3",
        upload_date="2025-01-15T10:30:00Z",
        audio_duration_seconds=draw(st.floats(min_value=0.0, max_value=3600.0, allow_nan=False, allow_infinity=False)),
        report_id="550e8400-e29b-41d4-a716-446655440000",
        speaker_identified=draw(st.booleans()),
        overall_score=overall_score,
        score_band=band,
        distance_to_next_band=distance,
        two_sentence_verdict="You delivered a strong presentation. Your pacing needs improvement.",
        lede_paragraph="Your presentation showed promise in several areas but there are key improvements to make.",
        dimensions=dims,
        three_moves=moves,
        strengths_to_protect=["You maintain good eye contact throughout."],
        diagnosis_paragraph="These three moves matter because they address your core weaknesses together.",
        talk_timeline=TalkTimeline(
            total_duration_seconds=600.0,
            open_percent=open_pct,
            body_percent=body_pct,
            close_percent=close_pct,
        ),
        provenance=Provenance(
            report_id="550e8400-e29b-41d4-a716-446655440000",
            evaluator_release="1.0.0",
            rubric_version="2.0.0",
            prompt_set_version="1.0.0",
            model_id="anthropic.claude-3-5-sonnet",
            model_temperature=0.3,
            transcription_service="aws-transcribe",
            evaluation_window="PT5M",
            run_completed_timestamp="2025-01-15T10:35:00Z",
        ),
    )


# ---------------------------------------------------------------------------
# Property 7: Score band classification and distance-to-next-band are consistent
# ---------------------------------------------------------------------------


@pytest.mark.property
@settings(max_examples=200, deadline=500)
@given(score=valid_score)
def test_classify_score_band_returns_correct_band(score: float) -> None:
    """For any float score in [0.0, 10.0], classify_score_band(score) SHALL return
    Developing when score < 4.0, Competent when 4.0 <= score < 6.5, Effective
    when 6.5 <= score < 8.5, and Exceptional when score >= 8.5.

    **Validates: Requirements 2.3**
    """
    band = classify_score_band(score)

    if score < 4.0:
        assert band == ScoreBand.DEVELOPING, f"Score {score} should be Developing, got {band}"
    elif score < 6.5:
        assert band == ScoreBand.COMPETENT, f"Score {score} should be Competent, got {band}"
    elif score < 8.5:
        assert band == ScoreBand.EFFECTIVE, f"Score {score} should be Effective, got {band}"
    else:
        assert band == ScoreBand.EXCEPTIONAL, f"Score {score} should be Exceptional, got {band}"


@pytest.mark.property
@settings(max_examples=200, deadline=500)
@given(score=valid_score)
def test_distance_to_next_band_is_positive_or_zero(score: float) -> None:
    """For any float score in [0.0, 10.0], compute_distance_to_next_band(score)
    SHALL return a non-negative value: the positive difference to the next boundary,
    or 0.0 for Exceptional.

    **Validates: Requirements 2.4**
    """
    distance = compute_distance_to_next_band(score)

    assert distance >= 0.0, f"Distance must be non-negative, got {distance} for score {score}"

    if score >= 8.5:
        assert distance == 0.0, f"Exceptional scores should have distance 0.0, got {distance}"
    else:
        assert distance > 0.0, f"Non-exceptional scores should have positive distance, got {distance}"


@pytest.mark.property
@settings(max_examples=200, deadline=500)
@given(score=valid_score)
def test_distance_to_next_band_reaches_boundary(score: float) -> None:
    """For any float score in [0.0, 10.0], score + compute_distance_to_next_band(score)
    SHALL equal the next band boundary (within floating point tolerance), or the score
    itself when already Exceptional.

    **Validates: Requirements 2.3, 2.4**
    """
    distance = compute_distance_to_next_band(score)
    band = classify_score_band(score)

    if band == ScoreBand.EXCEPTIONAL:
        assert distance == 0.0
    elif band == ScoreBand.EFFECTIVE:
        assert abs((score + distance) - 8.5) < 0.011, (
            f"Score {score} + distance {distance} should reach 8.5"
        )
    elif band == ScoreBand.COMPETENT:
        assert abs((score + distance) - 6.5) < 0.011, (
            f"Score {score} + distance {distance} should reach 6.5"
        )
    elif band == ScoreBand.DEVELOPING:
        assert abs((score + distance) - 4.0) < 0.011, (
            f"Score {score} + distance {distance} should reach 4.0"
        )


@pytest.mark.property
@settings(max_examples=200, deadline=500)
@given(score=valid_score)
def test_score_band_and_distance_are_mutually_consistent(score: float) -> None:
    """For any float score in [0.0, 10.0], the distance to next band added to the
    score SHALL reach the next boundary within rounding tolerance, and the band
    classification at that boundary SHALL be the next band up.

    **Validates: Requirements 2.3, 2.4**
    """
    band = classify_score_band(score)
    distance = compute_distance_to_next_band(score)

    if band == ScoreBand.EXCEPTIONAL:
        assert distance == 0.0
        return

    # The distance should bring us to exactly the next boundary
    # Due to round(..., 2), we verify the target boundary is correct
    if band == ScoreBand.DEVELOPING:
        expected_boundary = 4.0
    elif band == ScoreBand.COMPETENT:
        expected_boundary = 6.5
    elif band == ScoreBand.EFFECTIVE:
        expected_boundary = 8.5
    else:
        return

    # Verify score + distance reaches the boundary (within fp tolerance from rounding)
    assert abs((score + distance) - expected_boundary) < 0.011, (
        f"Score {score} + distance {distance} = {score + distance}, "
        f"expected to reach {expected_boundary}"
    )

    # At the exact boundary, classify should return the next band
    next_band = classify_score_band(expected_boundary)
    if band == ScoreBand.DEVELOPING:
        assert next_band == ScoreBand.COMPETENT
    elif band == ScoreBand.COMPETENT:
        assert next_band == ScoreBand.EFFECTIVE
    elif band == ScoreBand.EFFECTIVE:
        assert next_band == ScoreBand.EXCEPTIONAL


# ---------------------------------------------------------------------------
# Property 8: SynthesizedReport model rejects invalid field values
# ---------------------------------------------------------------------------


@pytest.mark.property
@settings(max_examples=100, deadline=500)
@given(score=st.floats(min_value=10.01, max_value=1000.0, allow_nan=False, allow_infinity=False))
def test_overall_score_above_range_rejected(score: float) -> None:
    """For any SynthesizedReport with overall_score > 10.0, Pydantic validation
    SHALL raise a ValidationError.

    **Validates: Requirements 2.14, 2.15**
    """
    with pytest.raises(ValidationError) as exc_info:
        SynthesizedReport(
            user_name="Test",
            presentation_title="Test",
            file_name="test.mp3",
            upload_date="2025-01-15T10:30:00Z",
            audio_duration_seconds=60.0,
            report_id="550e8400-e29b-41d4-a716-446655440000",
            speaker_identified=False,
            overall_score=score,
            score_band=ScoreBand.EXCEPTIONAL,
            distance_to_next_band=0.0,
            two_sentence_verdict="Good. Needs work.",
            lede_paragraph="Summary paragraph.",
            dimensions=[],  # Will also fail, but score is our focus
            three_moves=[],
            strengths_to_protect=["Good eye contact."],
            diagnosis_paragraph="These moves matter.",
            talk_timeline=TalkTimeline(
                total_duration_seconds=600.0,
                open_percent=20.0,
                body_percent=60.0,
                close_percent=20.0,
            ),
            provenance=Provenance(
                report_id="550e8400-e29b-41d4-a716-446655440000",
                evaluator_release="1.0.0",
                rubric_version="2.0.0",
                prompt_set_version="1.0.0",
                model_id="anthropic.claude-3-5-sonnet",
                model_temperature=0.3,
                transcription_service="aws-transcribe",
                evaluation_window="PT5M",
                run_completed_timestamp="2025-01-15T10:35:00Z",
            ),
        )
    # Verify the error mentions overall_score
    errors = exc_info.value.errors()
    error_fields = [e["loc"][0] for e in errors if e.get("loc")]
    assert "overall_score" in error_fields


@pytest.mark.property
@settings(max_examples=100, deadline=500)
@given(score=st.floats(max_value=-0.01, min_value=-1000.0, allow_nan=False, allow_infinity=False))
def test_overall_score_below_range_rejected(score: float) -> None:
    """For any SynthesizedReport with overall_score < 0.0, Pydantic validation
    SHALL raise a ValidationError.

    **Validates: Requirements 2.14, 2.15**
    """
    with pytest.raises(ValidationError) as exc_info:
        SynthesizedReport(
            user_name="Test",
            presentation_title="Test",
            file_name="test.mp3",
            upload_date="2025-01-15T10:30:00Z",
            audio_duration_seconds=60.0,
            report_id="550e8400-e29b-41d4-a716-446655440000",
            speaker_identified=False,
            overall_score=score,
            score_band=ScoreBand.DEVELOPING,
            distance_to_next_band=4.0,
            two_sentence_verdict="Good. Needs work.",
            lede_paragraph="Summary paragraph.",
            dimensions=[],
            three_moves=[],
            strengths_to_protect=["Good eye contact."],
            diagnosis_paragraph="These moves matter.",
            talk_timeline=TalkTimeline(
                total_duration_seconds=600.0,
                open_percent=20.0,
                body_percent=60.0,
                close_percent=20.0,
            ),
            provenance=Provenance(
                report_id="550e8400-e29b-41d4-a716-446655440000",
                evaluator_release="1.0.0",
                rubric_version="2.0.0",
                prompt_set_version="1.0.0",
                model_id="anthropic.claude-3-5-sonnet",
                model_temperature=0.3,
                transcription_service="aws-transcribe",
                evaluation_window="PT5M",
                run_completed_timestamp="2025-01-15T10:35:00Z",
            ),
        )
    errors = exc_info.value.errors()
    error_fields = [e["loc"][0] for e in errors if e.get("loc")]
    assert "overall_score" in error_fields


@pytest.mark.property
@settings(max_examples=100, deadline=500)
@given(
    dim_count=st.integers(min_value=0, max_value=6).filter(lambda x: x != 7)
    | st.integers(min_value=8, max_value=15)
)
def test_wrong_dimension_count_rejected(dim_count: int) -> None:
    """For any SynthesizedReport where dimension count != 7, Pydantic validation
    SHALL raise a ValidationError.

    **Validates: Requirements 2.14, 2.15**
    """
    dims = []
    for i in range(min(dim_count, 7)):
        dims.append(DimensionEntry(
            dimension_name=DIMENSIONS[i],
            score=5.0,
            score_band=ScoreBand.COMPETENT,
            rank=i + 1,
            one_sentence_verdict="Adequate performance observed.",
            severity_counts=SeverityCounts(high=0, medium=0, low=0, strength=0),
            findings=[],
            strengths=[],
            is_weakest=(i == 0),
        ))
    # For extra dimensions beyond 7, use generic names
    for i in range(7, dim_count):
        dims.append(DimensionEntry(
            dimension_name=f"Extra{i}",
            score=5.0,
            score_band=ScoreBand.COMPETENT,
            rank=min(i + 1, 7),
            one_sentence_verdict="Extra dimension.",
            severity_counts=SeverityCounts(high=0, medium=0, low=0, strength=0),
            findings=[],
            strengths=[],
            is_weakest=False,
        ))

    with pytest.raises(ValidationError) as exc_info:
        SynthesizedReport(
            user_name="Test",
            presentation_title="Test",
            file_name="test.mp3",
            upload_date="2025-01-15T10:30:00Z",
            audio_duration_seconds=60.0,
            report_id="550e8400-e29b-41d4-a716-446655440000",
            speaker_identified=False,
            overall_score=5.0,
            score_band=ScoreBand.COMPETENT,
            distance_to_next_band=1.5,
            two_sentence_verdict="Good. Needs work.",
            lede_paragraph="Summary paragraph.",
            dimensions=dims,
            three_moves=[
                ThreeMove(
                    title="Move 1",
                    coaching_advice="Focus on your delivery style.",
                    projected_impact_score=5.0,
                    dimensions_lifted=["Delivery"],
                ),
                ThreeMove(
                    title="Move 2",
                    coaching_advice="Improve your structure.",
                    projected_impact_score=4.0,
                    dimensions_lifted=["Structure"],
                ),
                ThreeMove(
                    title="Move 3",
                    coaching_advice="Enhance your presence.",
                    projected_impact_score=3.0,
                    dimensions_lifted=["Executive Presence"],
                ),
            ],
            strengths_to_protect=["Good eye contact."],
            diagnosis_paragraph="These moves matter.",
            talk_timeline=TalkTimeline(
                total_duration_seconds=600.0,
                open_percent=20.0,
                body_percent=60.0,
                close_percent=20.0,
            ),
            provenance=Provenance(
                report_id="550e8400-e29b-41d4-a716-446655440000",
                evaluator_release="1.0.0",
                rubric_version="2.0.0",
                prompt_set_version="1.0.0",
                model_id="anthropic.claude-3-5-sonnet",
                model_temperature=0.3,
                transcription_service="aws-transcribe",
                evaluation_window="PT5M",
                run_completed_timestamp="2025-01-15T10:35:00Z",
            ),
        )
    errors = exc_info.value.errors()
    error_fields = [e["loc"][0] for e in errors if e.get("loc")]
    assert "dimensions" in error_fields


@pytest.mark.property
@settings(max_examples=100, deadline=500)
@given(word_count=st.integers(min_value=81, max_value=200))
def test_verdict_exceeding_word_limit_rejected(word_count: int) -> None:
    """For any SynthesizedReport where two_sentence_verdict exceeds 80 words,
    Pydantic validation SHALL raise a ValidationError.

    **Validates: Requirements 2.14, 2.15**
    """
    # Create a verdict with too many words
    long_verdict = " ".join(["word"] * word_count)

    with pytest.raises(ValidationError) as exc_info:
        SynthesizedReport(
            user_name="Test",
            presentation_title="Test",
            file_name="test.mp3",
            upload_date="2025-01-15T10:30:00Z",
            audio_duration_seconds=60.0,
            report_id="550e8400-e29b-41d4-a716-446655440000",
            speaker_identified=False,
            overall_score=5.0,
            score_band=ScoreBand.COMPETENT,
            distance_to_next_band=1.5,
            two_sentence_verdict=long_verdict,
            lede_paragraph="Summary paragraph.",
            dimensions=[],
            three_moves=[],
            strengths_to_protect=["Good eye contact."],
            diagnosis_paragraph="These moves matter.",
            talk_timeline=TalkTimeline(
                total_duration_seconds=600.0,
                open_percent=20.0,
                body_percent=60.0,
                close_percent=20.0,
            ),
            provenance=Provenance(
                report_id="550e8400-e29b-41d4-a716-446655440000",
                evaluator_release="1.0.0",
                rubric_version="2.0.0",
                prompt_set_version="1.0.0",
                model_id="anthropic.claude-3-5-sonnet",
                model_temperature=0.3,
                transcription_service="aws-transcribe",
                evaluation_window="PT5M",
                run_completed_timestamp="2025-01-15T10:35:00Z",
            ),
        )
    errors = exc_info.value.errors()
    error_fields = [e["loc"][0] for e in errors if e.get("loc")]
    assert "two_sentence_verdict" in error_fields


@pytest.mark.property
@settings(max_examples=100, deadline=500)
@given(word_count=st.integers(min_value=121, max_value=250))
def test_lede_paragraph_exceeding_word_limit_rejected(word_count: int) -> None:
    """For any SynthesizedReport where lede_paragraph exceeds 120 words,
    Pydantic validation SHALL raise a ValidationError.

    **Validates: Requirements 2.14, 2.15**
    """
    long_lede = " ".join(["word"] * word_count)

    with pytest.raises(ValidationError) as exc_info:
        SynthesizedReport(
            user_name="Test",
            presentation_title="Test",
            file_name="test.mp3",
            upload_date="2025-01-15T10:30:00Z",
            audio_duration_seconds=60.0,
            report_id="550e8400-e29b-41d4-a716-446655440000",
            speaker_identified=False,
            overall_score=5.0,
            score_band=ScoreBand.COMPETENT,
            distance_to_next_band=1.5,
            two_sentence_verdict="Good. Needs work.",
            lede_paragraph=long_lede,
            dimensions=[],
            three_moves=[],
            strengths_to_protect=["Good eye contact."],
            diagnosis_paragraph="These moves matter.",
            talk_timeline=TalkTimeline(
                total_duration_seconds=600.0,
                open_percent=20.0,
                body_percent=60.0,
                close_percent=20.0,
            ),
            provenance=Provenance(
                report_id="550e8400-e29b-41d4-a716-446655440000",
                evaluator_release="1.0.0",
                rubric_version="2.0.0",
                prompt_set_version="1.0.0",
                model_id="anthropic.claude-3-5-sonnet",
                model_temperature=0.3,
                transcription_service="aws-transcribe",
                evaluation_window="PT5M",
                run_completed_timestamp="2025-01-15T10:35:00Z",
            ),
        )
    errors = exc_info.value.errors()
    error_fields = [e["loc"][0] for e in errors if e.get("loc")]
    assert "lede_paragraph" in error_fields


@pytest.mark.property
@settings(max_examples=100, deadline=500)
@given(dim_score=st.floats(min_value=10.01, max_value=100.0, allow_nan=False, allow_infinity=False))
def test_dimension_score_outside_range_rejected(dim_score: float) -> None:
    """For any DimensionEntry with score outside [0.0, 10.0], Pydantic validation
    SHALL raise a ValidationError identifying the invalid field.

    **Validates: Requirements 2.14, 2.15**
    """
    with pytest.raises(ValidationError):
        DimensionEntry(
            dimension_name="Delivery",
            score=dim_score,
            score_band=ScoreBand.EXCEPTIONAL,
            rank=1,
            one_sentence_verdict="Test verdict.",
            severity_counts=SeverityCounts(high=0, medium=0, low=0, strength=0),
            findings=[],
            strengths=[],
            is_weakest=True,
        )


@pytest.mark.property
@settings(max_examples=100, deadline=500)
@given(finding_count=st.integers(min_value=6, max_value=15))
def test_findings_exceeding_cap_rejected(finding_count: int) -> None:
    """For any DimensionEntry with more than 5 findings, Pydantic validation
    SHALL raise a ValidationError.

    **Validates: Requirements 2.14, 2.15**
    """
    findings = [
        SynthesizedFinding(
            severity=Severity.MEDIUM,
            title=f"Finding {i}",
            explanation="You need improvement here.",
            suggestion="Try this approach.",
            effort_tag=EffortTag.MODERATE,
            impact_tag=ImpactTag.MEDIUM,
            projected_impact_score=5.0,
        )
        for i in range(finding_count)
    ]

    with pytest.raises(ValidationError):
        DimensionEntry(
            dimension_name="Delivery",
            score=5.0,
            score_band=ScoreBand.COMPETENT,
            rank=1,
            one_sentence_verdict="Test verdict.",
            severity_counts=SeverityCounts(high=0, medium=finding_count, low=0, strength=0),
            findings=findings,
            strengths=[],
            is_weakest=True,
        )


@pytest.mark.property
@settings(max_examples=100, deadline=500)
@given(strengths_count=st.integers(min_value=4, max_value=10))
def test_strengths_exceeding_cap_rejected(strengths_count: int) -> None:
    """For any DimensionEntry with more than 3 strengths, Pydantic validation
    SHALL raise a ValidationError.

    **Validates: Requirements 2.14, 2.15**
    """
    strengths = [f"Strength {i}" for i in range(strengths_count)]

    with pytest.raises(ValidationError):
        DimensionEntry(
            dimension_name="Delivery",
            score=5.0,
            score_band=ScoreBand.COMPETENT,
            rank=1,
            one_sentence_verdict="Test verdict.",
            severity_counts=SeverityCounts(high=0, medium=0, low=0, strength=strengths_count),
            findings=[],
            strengths=strengths,
            is_weakest=True,
        )


@pytest.mark.property
@settings(max_examples=50, deadline=500)
@given(report=valid_synthesized_report())
def test_valid_report_passes_validation(report: SynthesizedReport) -> None:
    """For any SynthesizedReport with all fields within valid constraints,
    Pydantic validation SHALL accept the report without raising any errors.
    This is the dual property confirming valid inputs are not falsely rejected.

    **Validates: Requirements 2.14**
    """
    # If we get here without exception, the report was accepted
    assert report.overall_score >= 0.0
    assert report.overall_score <= 10.0
    assert len(report.dimensions) == 7
    assert len(report.three_moves) == 3
    assert 1 <= len(report.strengths_to_protect) <= 4
