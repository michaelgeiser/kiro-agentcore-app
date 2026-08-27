"""Score band classification utilities.

Provides functions for classifying numeric scores into performance bands
and computing the distance to the next band boundary.

Band boundaries:
    - Developing:  score < 4.0
    - Competent:   4.0 <= score < 6.5
    - Effective:   6.5 <= score < 8.5
    - Exceptional: score >= 8.5
"""

from models.synthesized_report import ScoreBand


def classify_score_band(score: float) -> ScoreBand:
    """Classify a numeric score into a ScoreBand.

    Args:
        score: A numeric score, typically in the range 0.0 to 10.0.

    Returns:
        The ScoreBand corresponding to the score value.
    """
    if score >= 8.5:
        return ScoreBand.EXCEPTIONAL
    elif score >= 6.5:
        return ScoreBand.EFFECTIVE
    elif score >= 4.0:
        return ScoreBand.COMPETENT
    else:
        return ScoreBand.DEVELOPING


def compute_distance_to_next_band(score: float) -> float:
    """Compute points needed to reach the next band boundary.

    Args:
        score: A numeric score, typically in the range 0.0 to 10.0.

    Returns:
        The positive difference to the next band boundary, or 0.0 if
        the score is already in the Exceptional band. For non-exceptional
        scores, always returns a positive value (minimum 0.01).
    """
    if score >= 8.5:
        return 0.0
    elif score >= 6.5:
        distance = round(8.5 - score, 2)
        return max(distance, 0.01)
    elif score >= 4.0:
        distance = round(6.5 - score, 2)
        return max(distance, 0.01)
    else:
        distance = round(4.0 - score, 2)
        return max(distance, 0.01)
