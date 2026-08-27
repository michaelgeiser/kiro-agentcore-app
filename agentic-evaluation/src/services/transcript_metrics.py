"""Transcript metrics extraction module.

Pure-function module that computes objective, reproducible metrics from
word-level transcript timings. All functions are deterministic with no
side effects — same input always produces identical output.

Requirements: 3.1–3.11
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from models.synthesized_report import TranscriptMetrics


@dataclass(frozen=True)
class WordTiming:
    """A single word with its timing and confidence data from transcription."""

    word: str
    start_seconds: float
    end_seconds: float
    confidence: float | None


@dataclass(frozen=True)
class TranscriptData:
    """Transcript input data for metrics computation."""

    words: list[WordTiming]
    close_start_seconds: float  # from Talk_Timeline segmentation


# Core filler words that are always counted
_ALWAYS_FILLERS = frozenset({"uh", "um", "ah", "er"})

# Common words that indicate "like" is being used as a verb/preposition/conjunction
# rather than a filler. These approximate noun/adj/verb followers without a POS tagger.
_NON_FILLER_LIKE_FOLLOWERS = frozenset({
    "a", "an", "the", "this", "that", "these", "those",
    "my", "your", "his", "her", "its", "our", "their",
    "i", "you", "he", "she", "it", "we", "they",
    "what", "which", "who", "how",
})


def compute_metrics(transcript: TranscriptData) -> TranscriptMetrics | None:
    """Compute all transcript metrics from word-level timings.

    Returns None if transcript has fewer than 2 words with timing data.
    Pure function — deterministic, no side effects.

    Requirements: 3.8, 3.9
    """
    if len(transcript.words) < 2:
        return None

    words = transcript.words
    pauses = _get_pause_durations(words, threshold=1.0)

    speaking_rate = _compute_speaking_rate_wpm(words, pauses)
    filler_count = _count_filler_words(words)
    so_count = _count_so_openers(words)
    pause_count = _count_pauses(words)
    longest_run = _compute_longest_unbroken_run(words)
    close_share = _compute_close_share(transcript)
    enunciation = _compute_enunciation_confidence(words)

    return TranscriptMetrics(
        speaking_rate_wpm=speaking_rate,
        target_range_wpm=(130, 170),
        filler_word_count=filler_count,
        so_opener_count=so_count,
        pauses_over_one_second=pause_count,
        longest_unbroken_run_seconds=longest_run,
        close_share_percent=close_share,
        enunciation_confidence=enunciation,
    )


def _get_pause_durations(words: list[WordTiming], threshold: float) -> list[float]:
    """Get all inter-word gap durations that exceed the threshold.

    Returns the list of pause durations (not indices) exceeding threshold.
    """
    pauses: list[float] = []
    for i in range(len(words) - 1):
        gap = words[i + 1].start_seconds - words[i].end_seconds
        if gap > threshold:
            pauses.append(gap)
    return pauses


def _compute_speaking_rate_wpm(words: list[WordTiming], pauses: list[float]) -> int:
    """Compute speaking rate as total words / net speaking minutes.

    Net speaking duration = elapsed time from first word start to last word end,
    minus the sum of all pause durations exceeding 1.0 second.
    Result is rounded to the nearest integer.

    Requirements: 3.1, 3.10
    """
    total_elapsed = words[-1].end_seconds - words[0].start_seconds
    total_pause_time = sum(pauses)
    net_speaking_seconds = total_elapsed - total_pause_time

    if net_speaking_seconds <= 0:
        return 0

    net_speaking_minutes = net_speaking_seconds / 60.0
    wpm = len(words) / net_speaking_minutes
    return round(wpm)


def _count_filler_words(words: list[WordTiming]) -> int:
    """Count filler words: uh, um, ah, er, and contextual 'like'.

    'like' is counted as filler when:
    - It is immediately followed by a pause ≥ 0.2s, OR
    - It is NOT followed by a noun/adj/verb within the next 2 words
      (approximated via heuristic since no POS tagger is available)

    Requirements: 3.2
    """
    count = 0
    for i, wt in enumerate(words):
        normalized = wt.word.lower().strip(".,!?;:\"'()-")
        if normalized in _ALWAYS_FILLERS:
            count += 1
        elif normalized == "like":
            if _is_filler_like(i, words):
                count += 1
    return count


def _is_filler_like(word_index: int, words: list[WordTiming]) -> bool:
    """Determine if 'like' at word_index is a filler.

    'like' is a filler when:
    - It is the last word (end of transcript)
    - Followed by a pause ≥ 0.2s before the next word
    - NOT followed by a content word (noun/adj/verb) within next 2 words

    The heuristic approximates POS detection: if the following 1-2 words are
    common determiners, pronouns, or function words, then 'like' is likely filler.
    If the following words appear to be content words (not in our function-word set),
    then 'like' is probably being used as a verb/preposition.
    """
    # End of transcript — it's filler
    if word_index + 1 >= len(words):
        return True

    current = words[word_index]
    next_word = words[word_index + 1]

    # Check pause condition: pause ≥ 0.2s after "like"
    gap = next_word.start_seconds - current.end_seconds
    if gap >= 0.2:
        return True

    # Check next-2-word heuristic:
    # If ANY of the next 2 words is a content word (not in our function-word set),
    # then "like" is probably a verb/preposition (not filler).
    for offset in range(1, 3):
        idx = word_index + offset
        if idx >= len(words):
            break
        follower = words[idx].word.lower().strip(".,!?;:\"'()-")
        if follower and follower not in _NON_FILLER_LIKE_FOLLOWERS:
            # Looks like a content word follows — "like" is not filler
            return False

    # Only function words follow — "like" is filler
    return True


def _count_so_openers(words: list[WordTiming], pause_threshold: float = 1.0) -> int:
    """Count 'So' appearing after >1s pause or as first word of transcript.

    Case-insensitive matching for 'so'.

    Requirements: 3.3
    """
    count = 0
    for i, wt in enumerate(words):
        normalized = wt.word.lower().strip(".,!?;:\"'()-")
        if normalized != "so":
            continue

        if i == 0:
            # First word of transcript
            count += 1
        else:
            # Check if preceded by a pause > threshold
            gap = wt.start_seconds - words[i - 1].end_seconds
            if gap > pause_threshold:
                count += 1

    return count


def _count_pauses(words: list[WordTiming], threshold: float = 1.0) -> int:
    """Count inter-word gaps exceeding the threshold (default 1.0s).

    Requirements: 3.4
    """
    count = 0
    for i in range(len(words) - 1):
        gap = words[i + 1].start_seconds - words[i].end_seconds
        if gap > threshold:
            count += 1
    return count


def _compute_longest_unbroken_run(
    words: list[WordTiming], threshold: float = 1.0
) -> float:
    """Compute the maximum segment duration between >1s pauses.

    Transcript start and end are implicit boundaries. The duration of a segment
    is measured from the start of the first word in that segment to the end of
    the last word in that segment.

    Result is rounded to 1 decimal place.

    Requirements: 3.5, 3.11
    """
    # Find indices where pauses > threshold occur
    pause_indices: list[int] = []
    for i in range(len(words) - 1):
        gap = words[i + 1].start_seconds - words[i].end_seconds
        if gap > threshold:
            pause_indices.append(i)

    # Build segments: each segment runs from segment_start_word to segment_end_word
    # Boundaries: transcript start, each pause, transcript end
    longest = 0.0

    if not pause_indices:
        # No pauses — entire transcript is one segment
        duration = words[-1].end_seconds - words[0].start_seconds
        return round(duration, 1)

    # Segment from start to first pause
    first_seg_end = pause_indices[0]
    duration = words[first_seg_end].end_seconds - words[0].start_seconds
    longest = max(longest, duration)

    # Segments between consecutive pauses
    for j in range(len(pause_indices) - 1):
        seg_start = pause_indices[j] + 1
        seg_end = pause_indices[j + 1]
        if seg_start <= seg_end:
            duration = words[seg_end].end_seconds - words[seg_start].start_seconds
            longest = max(longest, duration)

    # Segment from last pause to end
    last_seg_start = pause_indices[-1] + 1
    if last_seg_start < len(words):
        duration = words[-1].end_seconds - words[last_seg_start].start_seconds
        longest = max(longest, duration)

    return round(longest, 1)


def _compute_close_share(transcript: TranscriptData) -> float:
    """Compute percentage of total audio in closing segment.

    Total audio duration = first word start to last word end.
    Closing segment = close_start_seconds to last word end.

    Requirements: 3.6
    """
    words = transcript.words
    total_duration = words[-1].end_seconds - words[0].start_seconds

    if total_duration <= 0:
        return 0.0

    close_duration = words[-1].end_seconds - transcript.close_start_seconds

    if close_duration <= 0:
        return 0.0

    return (close_duration / total_duration) * 100.0


def _compute_enunciation_confidence(words: list[WordTiming]) -> float:
    """Compute median of word-level confidence scores, excluding None.

    Returns 0.0 if no words have confidence scores.

    Requirements: 3.7
    """
    scores = [w.confidence for w in words if w.confidence is not None]

    if not scores:
        return 0.0

    return statistics.median(scores)
