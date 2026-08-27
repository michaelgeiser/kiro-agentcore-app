"""Unit tests for transcript metrics edge cases.

Validates: Requirements 3.9, 3.2, 3.3
"""

import pytest

from services.transcript_metrics import (
    TranscriptData,
    WordTiming,
    compute_metrics,
    _count_filler_words,
    _count_so_openers,
)


def _make_word(word: str, start: float, end: float, confidence: float | None = 0.9) -> WordTiming:
    """Helper to create a WordTiming with less boilerplate."""
    return WordTiming(word=word, start_seconds=start, end_seconds=end, confidence=confidence)


class TestFewerThanTwoWordsReturnsNone:
    """Requirement 3.9: < 2 words returns None for all metrics."""

    def test_empty_transcript_returns_none(self):
        transcript = TranscriptData(words=[], close_start_seconds=0.0)
        assert compute_metrics(transcript) is None

    def test_single_word_transcript_returns_none(self):
        transcript = TranscriptData(
            words=[_make_word("hello", 0.0, 0.5)],
            close_start_seconds=0.0,
        )
        assert compute_metrics(transcript) is None


class TestAllPauseTranscript:
    """Test transcript where every inter-word gap exceeds 1 second."""

    def test_all_pauses_over_one_second(self):
        """When every gap > 1s, net speaking time is very short (just word durations).

        3 words, each 0.5s long, with 2.0s gaps between them.
        Total elapsed = 5.5s (0.0 to 5.5)
        Pause time = 2.0 + 2.0 = 4.0s
        Net speaking = 5.5 - 4.0 = 1.5s
        WPM = 3 / (1.5/60) = 120
        """
        words = [
            _make_word("hello", 0.0, 0.5),
            _make_word("world", 2.5, 3.0),
            _make_word("test", 5.0, 5.5),
        ]
        transcript = TranscriptData(words=words, close_start_seconds=5.0)
        result = compute_metrics(transcript)

        assert result is not None
        # Pause count: 2 gaps both > 1s
        assert result.pauses_over_one_second == 2
        # Speaking rate: 3 words / (1.5s / 60) = 120 WPM
        assert result.speaking_rate_wpm == 120

    def test_all_pauses_longest_run_is_single_word_duration(self):
        """With pauses between every word pair, longest run is the longest single word."""
        words = [
            _make_word("one", 0.0, 0.3),
            _make_word("two", 2.0, 2.5),   # gap 1.7s > 1s
            _make_word("three", 4.0, 4.8),  # gap 1.5s > 1s
        ]
        transcript = TranscriptData(words=words, close_start_seconds=4.0)
        result = compute_metrics(transcript)

        assert result is not None
        # Segments: [one: 0.0-0.3] = 0.3s, [two: 2.0-2.5] = 0.5s, [three: 4.0-4.8] = 0.8s
        assert result.longest_unbroken_run_seconds == 0.8


class TestLikeDisambiguation:
    """Requirement 3.2: 'like' filler disambiguation heuristic."""

    def test_like_before_long_pause_is_filler(self):
        """'like' followed by a pause >= 0.2s is counted as filler."""
        words = [
            _make_word("I", 0.0, 0.1),
            _make_word("like", 0.2, 0.4),
            _make_word("running", 0.7, 1.0),  # gap 0.3s >= 0.2s
        ]
        count = _count_filler_words(words)
        assert count == 1

    def test_like_before_content_word_not_filler(self):
        """'like' immediately followed by a content word (no pause) is NOT filler."""
        words = [
            _make_word("I", 0.0, 0.1),
            _make_word("like", 0.15, 0.35),
            _make_word("running", 0.36, 0.7),  # gap 0.01s < 0.2s, "running" is content
        ]
        count = _count_filler_words(words)
        assert count == 0

    def test_like_at_end_of_transcript_is_filler(self):
        """'like' as the last word is counted as filler."""
        words = [
            _make_word("it", 0.0, 0.1),
            _make_word("was", 0.15, 0.3),
            _make_word("like", 0.35, 0.55),
        ]
        count = _count_filler_words(words)
        assert count == 1

    def test_like_followed_by_only_function_words_is_filler(self):
        """'like' followed only by determiners/pronouns (function words) is filler."""
        words = [
            _make_word("it", 0.0, 0.1),
            _make_word("like", 0.12, 0.3),   # gap to next = 0.01s
            _make_word("the", 0.31, 0.45),   # "the" is a function word
            _make_word("a", 0.46, 0.55),     # "a" is also a function word
        ]
        count = _count_filler_words(words)
        assert count == 1

    def test_like_followed_by_content_word_second_position_not_filler(self):
        """'like' NOT filler when a content word appears within 2 words."""
        words = [
            _make_word("it", 0.0, 0.1),
            _make_word("like", 0.12, 0.3),     # gap 0.01s
            _make_word("the", 0.31, 0.45),     # function word
            _make_word("sunset", 0.46, 0.8),   # content word (not in function set)
        ]
        count = _count_filler_words(words)
        assert count == 0

    def test_always_filler_words_counted_regardless_of_context(self):
        """'uh', 'um', 'ah', 'er' always count as fillers."""
        words = [
            _make_word("uh", 0.0, 0.2),
            _make_word("um", 0.25, 0.45),
            _make_word("ah", 0.5, 0.7),
            _make_word("er", 0.75, 0.9),
            _make_word("hello", 0.95, 1.2),
        ]
        count = _count_filler_words(words)
        assert count == 4


class TestSoOpener:
    """Requirement 3.3: 'So' as sentence opener detection."""

    def test_so_as_first_word_of_transcript(self):
        """'So' at transcript start counts as opener."""
        words = [
            _make_word("So", 0.0, 0.2),
            _make_word("today", 0.25, 0.6),
            _make_word("we", 0.65, 0.8),
        ]
        count = _count_so_openers(words)
        assert count == 1

    def test_so_after_long_pause_mid_transcript(self):
        """'So' after a pause > 1s mid-transcript counts as opener."""
        words = [
            _make_word("right", 0.0, 0.3),
            _make_word("so", 1.5, 1.7),  # gap = 1.2s > 1.0s
            _make_word("next", 1.75, 2.0),
        ]
        count = _count_so_openers(words)
        assert count == 1

    def test_so_after_short_pause_not_counted(self):
        """'So' after a pause <= 1s is NOT an opener."""
        words = [
            _make_word("and", 0.0, 0.2),
            _make_word("so", 0.5, 0.7),  # gap = 0.3s <= 1.0s
            _make_word("on", 0.75, 0.9),
        ]
        count = _count_so_openers(words)
        assert count == 0

    def test_multiple_so_openers(self):
        """Multiple 'So' openers in one transcript all counted."""
        words = [
            _make_word("So", 0.0, 0.2),       # first word — opener
            _make_word("first", 0.25, 0.6),
            _make_word("so", 2.0, 2.2),        # gap = 1.4s > 1.0s — opener
            _make_word("second", 2.25, 2.6),
            _make_word("so", 2.65, 2.85),      # gap = 0.05s <= 1.0s — NOT opener
            _make_word("third", 2.9, 3.2),
        ]
        count = _count_so_openers(words)
        assert count == 2

    def test_so_case_insensitive(self):
        """'so', 'So', 'SO' all detected as openers."""
        words = [
            _make_word("SO", 0.0, 0.2),
            _make_word("yeah", 0.25, 0.5),
        ]
        count = _count_so_openers(words)
        assert count == 1

    def test_so_with_punctuation_still_detected(self):
        """'So,' (with trailing punctuation) still detected."""
        words = [
            _make_word("right", 0.0, 0.3),
            _make_word("So,", 1.5, 1.7),  # gap = 1.2s > 1.0s
            _make_word("next", 1.75, 2.0),
        ]
        count = _count_so_openers(words)
        assert count == 1
