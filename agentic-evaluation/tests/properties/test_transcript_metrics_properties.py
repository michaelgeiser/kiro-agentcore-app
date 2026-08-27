# Feature: coaching-report-v2, Properties 9, 10, 11, 12, 13: Transcript metrics correctness
"""Property-based tests for transcript metrics extraction module.

Tests verify that speaking rate, pause counting, longest unbroken run,
enunciation confidence, and determinism properties hold across all valid inputs.

Validates: Requirements 3.1, 3.4, 3.5, 3.7, 3.8, 3.10, 3.11
"""

import statistics

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st
from hypothesis.strategies import composite

from services.transcript_metrics import (
    TranscriptData,
    WordTiming,
    _compute_enunciation_confidence,
    _compute_longest_unbroken_run,
    _compute_speaking_rate_wpm,
    _count_pauses,
    _get_pause_durations,
    compute_metrics,
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


@composite
def word_timing(draw, min_start: float = 0.0, max_start: float = 600.0):
    """Generate a single WordTiming with valid timing constraints.

    Ensures end_seconds > start_seconds (words have positive duration).
    """
    start = draw(st.floats(
        min_value=min_start,
        max_value=max_start,
        allow_nan=False,
        allow_infinity=False,
    ))
    # Word duration between 0.05s and 2.0s
    duration = draw(st.floats(
        min_value=0.05,
        max_value=2.0,
        allow_nan=False,
        allow_infinity=False,
    ))
    end = start + duration

    confidence = draw(st.one_of(
        st.none(),
        st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    ))

    word = draw(st.text(
        min_size=1,
        max_size=20,
        alphabet=st.characters(whitelist_categories=("L",)),
    ))

    return WordTiming(
        word=word,
        start_seconds=start,
        end_seconds=end,
        confidence=confidence,
    )


@composite
def word_timing_sequence(draw, min_size: int = 2, max_size: int = 50):
    """Generate a chronologically ordered sequence of WordTimings.

    Words are ordered in time with variable gaps between them (some > 1s for pauses).
    """
    n = draw(st.integers(min_value=min_size, max_value=max_size))

    words: list[WordTiming] = []
    current_time = draw(st.floats(
        min_value=0.0, max_value=10.0,
        allow_nan=False, allow_infinity=False,
    ))

    for _ in range(n):
        # Word duration between 0.1s and 1.5s
        word_duration = draw(st.floats(
            min_value=0.1, max_value=1.5,
            allow_nan=False, allow_infinity=False,
        ))
        # Gap to next word: mix of short gaps and potential pauses
        gap = draw(st.floats(
            min_value=0.0, max_value=5.0,
            allow_nan=False, allow_infinity=False,
        ))

        confidence = draw(st.one_of(
            st.none(),
            st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        ))

        word_text = draw(st.text(
            min_size=1, max_size=15,
            alphabet=st.characters(whitelist_categories=("L",)),
        ))

        start = current_time
        end = start + word_duration

        words.append(WordTiming(
            word=word_text,
            start_seconds=start,
            end_seconds=end,
            confidence=confidence,
        ))

        current_time = end + gap

    return words


@composite
def word_timing_sequence_with_pauses(draw, min_size: int = 2, max_size: int = 30):
    """Generate a sequence that is guaranteed to contain at least one pause > 1s.

    Useful for testing pause-related properties.
    """
    n = draw(st.integers(min_value=min_size, max_value=max_size))
    # Ensure at least one pause > 1s by choosing a random position
    pause_position = draw(st.integers(min_value=0, max_value=max(0, n - 2)))

    words: list[WordTiming] = []
    current_time = draw(st.floats(
        min_value=0.0, max_value=5.0,
        allow_nan=False, allow_infinity=False,
    ))

    for i in range(n):
        word_duration = draw(st.floats(
            min_value=0.1, max_value=1.0,
            allow_nan=False, allow_infinity=False,
        ))

        confidence = draw(st.one_of(
            st.none(),
            st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        ))

        word_text = draw(st.text(
            min_size=1, max_size=10,
            alphabet=st.characters(whitelist_categories=("L",)),
        ))

        start = current_time
        end = start + word_duration

        words.append(WordTiming(
            word=word_text,
            start_seconds=start,
            end_seconds=end,
            confidence=confidence,
        ))

        # Add gap: force a pause > 1s at the designated position
        if i == pause_position and i < n - 1:
            gap = draw(st.floats(
                min_value=1.01, max_value=5.0,
                allow_nan=False, allow_infinity=False,
            ))
        else:
            gap = draw(st.floats(
                min_value=0.0, max_value=3.0,
                allow_nan=False, allow_infinity=False,
            ))

        current_time = end + gap

    return words


@composite
def word_timing_sequence_with_confidence(draw, min_size: int = 2, max_size: int = 30):
    """Generate a word sequence where at least one word has non-null confidence."""
    words = draw(word_timing_sequence(min_size=min_size, max_size=max_size))

    # Ensure at least one has confidence
    has_confidence = any(w.confidence is not None for w in words)
    if not has_confidence:
        # Replace the first word's confidence with a valid value
        conf_value = draw(st.floats(
            min_value=0.0, max_value=1.0,
            allow_nan=False, allow_infinity=False,
        ))
        old = words[0]
        words[0] = WordTiming(
            word=old.word,
            start_seconds=old.start_seconds,
            end_seconds=old.end_seconds,
            confidence=conf_value,
        )

    return words


@composite
def transcript_data(draw, min_words: int = 2, max_words: int = 50):
    """Generate a valid TranscriptData with ordered words."""
    words = draw(word_timing_sequence(min_size=min_words, max_size=max_words))

    # close_start_seconds should be within the transcript duration
    first_start = words[0].start_seconds
    last_end = words[-1].end_seconds
    close_start = draw(st.floats(
        min_value=first_start,
        max_value=last_end,
        allow_nan=False,
        allow_infinity=False,
    ))

    return TranscriptData(words=words, close_start_seconds=close_start)


# ---------------------------------------------------------------------------
# Property 9: Speaking rate WPM computed correctly
# ---------------------------------------------------------------------------


@pytest.mark.property
@settings(max_examples=200, deadline=2000)
@given(words=word_timing_sequence(min_size=2, max_size=40))
def test_speaking_rate_wpm_matches_formula(words: list[WordTiming]) -> None:
    """For any TranscriptData with >= 2 words, _compute_speaking_rate_wpm() SHALL
    return round(total_word_count / net_speaking_minutes) where net_speaking_minutes =
    (elapsed time from first word start to last word end, minus the sum of all pause
    durations exceeding 1.0 second) / 60.

    **Validates: Requirements 3.1, 3.10**
    """
    total_elapsed = words[-1].end_seconds - words[0].start_seconds
    assume(total_elapsed > 0)

    # Compute pauses > 1s manually
    pause_durations: list[float] = []
    for i in range(len(words) - 1):
        gap = words[i + 1].start_seconds - words[i].end_seconds
        if gap > 1.0:
            pause_durations.append(gap)

    net_speaking_seconds = total_elapsed - sum(pause_durations)
    assume(net_speaking_seconds > 0)

    net_speaking_minutes = net_speaking_seconds / 60.0
    expected_wpm = round(len(words) / net_speaking_minutes)

    # Call the implementation
    pauses = _get_pause_durations(words, threshold=1.0)
    actual_wpm = _compute_speaking_rate_wpm(words, pauses)

    assert actual_wpm == expected_wpm, (
        f"Expected WPM {expected_wpm}, got {actual_wpm}. "
        f"Words: {len(words)}, net_minutes: {net_speaking_minutes:.4f}"
    )


@pytest.mark.property
@settings(max_examples=200, deadline=2000)
@given(words=word_timing_sequence(min_size=2, max_size=40))
def test_speaking_rate_wpm_is_non_negative_integer(words: list[WordTiming]) -> None:
    """For any TranscriptData with >= 2 words, _compute_speaking_rate_wpm() SHALL
    return a non-negative integer.

    **Validates: Requirements 3.1, 3.10**
    """
    pauses = _get_pause_durations(words, threshold=1.0)
    result = _compute_speaking_rate_wpm(words, pauses)

    assert isinstance(result, int), f"Expected int, got {type(result)}"
    assert result >= 0, f"WPM must be non-negative, got {result}"


# ---------------------------------------------------------------------------
# Property 10: Pause count equals number of inter-word gaps exceeding 1 second
# ---------------------------------------------------------------------------


@pytest.mark.property
@settings(max_examples=200, deadline=2000)
@given(words=word_timing_sequence(min_size=2, max_size=40))
def test_pause_count_matches_inter_word_gaps(words: list[WordTiming]) -> None:
    """For any TranscriptData with >= 2 words, _count_pauses() SHALL return the
    exact count of consecutive word pairs where
    words[i+1].start_seconds - words[i].end_seconds > 1.0.

    **Validates: Requirements 3.4**
    """
    # Compute expected count manually
    expected_count = 0
    for i in range(len(words) - 1):
        gap = words[i + 1].start_seconds - words[i].end_seconds
        if gap > 1.0:
            expected_count += 1

    actual_count = _count_pauses(words)

    assert actual_count == expected_count, (
        f"Expected {expected_count} pauses, got {actual_count}. "
        f"Gaps: {[words[i+1].start_seconds - words[i].end_seconds for i in range(len(words)-1)]}"
    )


@pytest.mark.property
@settings(max_examples=100, deadline=2000)
@given(words=word_timing_sequence_with_pauses(min_size=2, max_size=30))
def test_pause_count_is_at_least_one_when_pauses_exist(words: list[WordTiming]) -> None:
    """For any TranscriptData with >= 2 words that contains at least one gap > 1s,
    _count_pauses() SHALL return >= 1.

    **Validates: Requirements 3.4**
    """
    # The strategy guarantees at least one pause > 1s
    actual_count = _count_pauses(words)
    assert actual_count >= 1, (
        f"Expected at least 1 pause but got {actual_count}"
    )


# ---------------------------------------------------------------------------
# Property 11: Longest unbroken run is the maximum segment between pauses
# ---------------------------------------------------------------------------


@pytest.mark.property
@settings(max_examples=200, deadline=2000)
@given(words=word_timing_sequence(min_size=2, max_size=40))
def test_longest_unbroken_run_matches_max_segment(words: list[WordTiming]) -> None:
    """For any TranscriptData with >= 2 words, _compute_longest_unbroken_run() SHALL
    return the maximum duration among all segments bounded by >1s pauses (treating
    transcript start and end as boundaries), rounded to 1 decimal place.

    **Validates: Requirements 3.5, 3.11**
    """
    # Find pause indices (where gap > 1s)
    pause_indices: list[int] = []
    for i in range(len(words) - 1):
        gap = words[i + 1].start_seconds - words[i].end_seconds
        if gap > 1.0:
            pause_indices.append(i)

    # Compute segments manually
    if not pause_indices:
        # No pauses: entire transcript is one segment
        expected = round(words[-1].end_seconds - words[0].start_seconds, 1)
    else:
        longest = 0.0

        # Segment from start to first pause
        seg_end_idx = pause_indices[0]
        duration = words[seg_end_idx].end_seconds - words[0].start_seconds
        longest = max(longest, duration)

        # Segments between consecutive pauses
        for j in range(len(pause_indices) - 1):
            seg_start_idx = pause_indices[j] + 1
            seg_end_idx = pause_indices[j + 1]
            if seg_start_idx <= seg_end_idx:
                duration = words[seg_end_idx].end_seconds - words[seg_start_idx].start_seconds
                longest = max(longest, duration)

        # Segment from last pause to end
        last_seg_start_idx = pause_indices[-1] + 1
        if last_seg_start_idx < len(words):
            duration = words[-1].end_seconds - words[last_seg_start_idx].start_seconds
            longest = max(longest, duration)

        expected = round(longest, 1)

    actual = _compute_longest_unbroken_run(words)

    assert actual == expected, (
        f"Expected longest run {expected}, got {actual}. "
        f"Pause indices: {pause_indices}"
    )


@pytest.mark.property
@settings(max_examples=200, deadline=2000)
@given(words=word_timing_sequence(min_size=2, max_size=40))
def test_longest_unbroken_run_is_non_negative_and_rounded(words: list[WordTiming]) -> None:
    """For any TranscriptData with >= 2 words, _compute_longest_unbroken_run() SHALL
    return a non-negative float rounded to 1 decimal place.

    **Validates: Requirements 3.5, 3.11**
    """
    result = _compute_longest_unbroken_run(words)

    assert result >= 0.0, f"Longest run must be non-negative, got {result}"
    # Check rounded to 1 decimal place
    assert result == round(result, 1), (
        f"Result {result} is not rounded to 1 decimal place"
    )


# ---------------------------------------------------------------------------
# Property 12: Enunciation confidence is the median of word confidence scores
# ---------------------------------------------------------------------------


@pytest.mark.property
@settings(max_examples=200, deadline=2000)
@given(words=word_timing_sequence_with_confidence(min_size=2, max_size=40))
def test_enunciation_confidence_equals_median(words: list[WordTiming]) -> None:
    """For any TranscriptData where at least one word has a non-null confidence
    value, _compute_enunciation_confidence() SHALL return the statistical median
    of all non-null confidence values.

    **Validates: Requirements 3.7**
    """
    # Compute expected median manually
    non_null_scores = [w.confidence for w in words if w.confidence is not None]
    assume(len(non_null_scores) >= 1)

    expected_median = statistics.median(non_null_scores)

    actual = _compute_enunciation_confidence(words)

    assert actual == expected_median, (
        f"Expected median {expected_median}, got {actual}. "
        f"Non-null scores: {non_null_scores}"
    )


@pytest.mark.property
@settings(max_examples=100, deadline=2000)
@given(words=word_timing_sequence_with_confidence(min_size=2, max_size=40))
def test_enunciation_confidence_in_valid_range(words: list[WordTiming]) -> None:
    """For any TranscriptData with at least one non-null confidence value,
    _compute_enunciation_confidence() SHALL return a value in [0.0, 1.0].

    **Validates: Requirements 3.7**
    """
    non_null_scores = [w.confidence for w in words if w.confidence is not None]
    assume(len(non_null_scores) >= 1)

    result = _compute_enunciation_confidence(words)

    assert 0.0 <= result <= 1.0, (
        f"Enunciation confidence must be in [0.0, 1.0], got {result}"
    )


@pytest.mark.property
@settings(max_examples=100, deadline=2000)
@given(words=word_timing_sequence(min_size=2, max_size=20))
def test_enunciation_confidence_excludes_none_values(words: list[WordTiming]) -> None:
    """For any TranscriptData, _compute_enunciation_confidence() SHALL exclude
    words with null confidence from the median calculation.

    **Validates: Requirements 3.7**
    """
    non_null_scores = [w.confidence for w in words if w.confidence is not None]

    result = _compute_enunciation_confidence(words)

    if not non_null_scores:
        # No confidence values — returns 0.0
        assert result == 0.0
    else:
        expected = statistics.median(non_null_scores)
        assert result == expected


# ---------------------------------------------------------------------------
# Property 13: Transcript metrics computation is deterministic
# ---------------------------------------------------------------------------


@pytest.mark.property
@settings(max_examples=200, deadline=2000)
@given(data=transcript_data(min_words=2, max_words=40))
def test_compute_metrics_is_deterministic(data: TranscriptData) -> None:
    """For any TranscriptData, calling compute_metrics() twice with identical input
    SHALL produce identical TranscriptMetrics output (all fields equal).

    **Validates: Requirements 3.8**
    """
    result1 = compute_metrics(data)
    result2 = compute_metrics(data)

    assert result1 == result2, (
        f"Non-deterministic results:\n"
        f"  First:  {result1}\n"
        f"  Second: {result2}"
    )


@pytest.mark.property
@settings(max_examples=100, deadline=2000)
@given(data=transcript_data(min_words=2, max_words=30))
def test_compute_metrics_fields_are_consistent(data: TranscriptData) -> None:
    """For any TranscriptData with >= 2 words, compute_metrics() SHALL return
    a TranscriptMetrics where all fields are individually deterministic across
    multiple invocations.

    **Validates: Requirements 3.8**
    """
    result1 = compute_metrics(data)
    result2 = compute_metrics(data)

    assert result1 is not None
    assert result2 is not None

    # Each field must be identical
    assert result1.speaking_rate_wpm == result2.speaking_rate_wpm
    assert result1.filler_word_count == result2.filler_word_count
    assert result1.so_opener_count == result2.so_opener_count
    assert result1.pauses_over_one_second == result2.pauses_over_one_second
    assert result1.longest_unbroken_run_seconds == result2.longest_unbroken_run_seconds
    assert result1.close_share_percent == result2.close_share_percent
    assert result1.enunciation_confidence == result2.enunciation_confidence
    assert result1.target_range_wpm == result2.target_range_wpm
