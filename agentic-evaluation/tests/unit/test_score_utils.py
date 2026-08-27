"""Unit tests for score band classification utilities."""

import pytest

from models.synthesized_report import ScoreBand
from services.score_utils import classify_score_band, compute_distance_to_next_band


class TestClassifyScoreBand:
    """Tests for classify_score_band()."""

    @pytest.mark.parametrize(
        "score,expected_band",
        [
            (0.0, ScoreBand.DEVELOPING),
            (2.0, ScoreBand.DEVELOPING),
            (3.99, ScoreBand.DEVELOPING),
            (4.0, ScoreBand.COMPETENT),
            (5.0, ScoreBand.COMPETENT),
            (6.49, ScoreBand.COMPETENT),
            (6.5, ScoreBand.EFFECTIVE),
            (7.5, ScoreBand.EFFECTIVE),
            (8.49, ScoreBand.EFFECTIVE),
            (8.5, ScoreBand.EXCEPTIONAL),
            (9.0, ScoreBand.EXCEPTIONAL),
            (10.0, ScoreBand.EXCEPTIONAL),
        ],
    )
    def test_classifies_score_into_correct_band(self, score, expected_band):
        assert classify_score_band(score) == expected_band

    def test_boundary_at_4_0_is_competent(self):
        """Exact boundary: 4.0 is Competent, not Developing."""
        assert classify_score_band(4.0) == ScoreBand.COMPETENT

    def test_boundary_at_6_5_is_effective(self):
        """Exact boundary: 6.5 is Effective, not Competent."""
        assert classify_score_band(6.5) == ScoreBand.EFFECTIVE

    def test_boundary_at_8_5_is_exceptional(self):
        """Exact boundary: 8.5 is Exceptional, not Effective."""
        assert classify_score_band(8.5) == ScoreBand.EXCEPTIONAL


class TestComputeDistanceToNextBand:
    """Tests for compute_distance_to_next_band()."""

    @pytest.mark.parametrize(
        "score,expected_distance",
        [
            (0.0, 4.0),
            (2.0, 2.0),
            (3.5, 0.5),
            (4.0, 2.5),
            (5.5, 1.0),
            (6.5, 2.0),
            (7.5, 1.0),
            (8.5, 0.0),
            (9.5, 0.0),
            (10.0, 0.0),
        ],
    )
    def test_distance_to_next_band(self, score, expected_distance):
        assert compute_distance_to_next_band(score) == expected_distance

    def test_exceptional_returns_zero(self):
        """Exceptional band has no higher band to reach."""
        assert compute_distance_to_next_band(8.5) == 0.0
        assert compute_distance_to_next_band(10.0) == 0.0

    def test_distance_is_non_negative(self):
        """Distance should never be negative for valid scores."""
        for score in [0.0, 1.5, 4.0, 6.5, 8.5, 10.0]:
            assert compute_distance_to_next_band(score) >= 0.0

    def test_rounding_to_two_decimals(self):
        """Verify distances are rounded to 2 decimal places."""
        # 4.0 - 3.33 = 0.67
        assert compute_distance_to_next_band(3.33) == 0.67
        # 6.5 - 4.17 = 2.33
        assert compute_distance_to_next_band(4.17) == 2.33
