"""Unit tests for template filters and helper functions.

Tests cover the Jinja2 filters and SVG/layout helper functions
used by the coaching report template.

Requirements covered: 5.4, 5.7, 5.8, 10.5
"""

import math

import pytest

from services.template_filters import (
    dimension_bar_width,
    dimension_target_x,
    format_date,
    format_duration,
    gauge_arc_path,
    gauge_tick_path,
    register_filters,
    score_band_color,
    score_to_arc_degrees,
    timeline_pin_x,
    timeline_segment_widths,
)


# ---------------------------------------------------------------------------
# format_duration tests
# ---------------------------------------------------------------------------


class TestFormatDuration:
    """Tests for format_duration filter."""

    def test_basic_conversion(self) -> None:
        assert format_duration(125.5) == "2 min 05 sec"

    def test_exact_minute(self) -> None:
        assert format_duration(60.0) == "1 min 00 sec"

    def test_less_than_a_minute(self) -> None:
        assert format_duration(5.0) == "0 min 05 sec"

    def test_zero_seconds(self) -> None:
        assert format_duration(0.0) == "0 min 00 sec"

    def test_large_duration(self) -> None:
        assert format_duration(3661.0) == "61 min 01 sec"

    def test_negative_treated_as_zero(self) -> None:
        assert format_duration(-10.0) == "0 min 00 sec"

    def test_fractional_seconds_truncated(self) -> None:
        # 90.9 seconds = 1 min 30 sec (int truncation of 30.9)
        assert format_duration(90.9) == "1 min 30 sec"

    def test_59_seconds(self) -> None:
        assert format_duration(59.0) == "0 min 59 sec"


# ---------------------------------------------------------------------------
# format_date tests
# ---------------------------------------------------------------------------


class TestFormatDate:
    """Tests for format_date filter."""

    def test_basic_iso_with_z(self) -> None:
        assert format_date("2025-01-15T10:30:00Z") == "JANUARY 15, 2025"

    def test_iso_with_offset(self) -> None:
        assert format_date("2026-08-05T16:00:00+00:00") == "AUGUST 5, 2026"

    def test_different_month(self) -> None:
        assert format_date("2024-12-25T00:00:00Z") == "DECEMBER 25, 2024"

    def test_single_digit_day(self) -> None:
        assert format_date("2025-03-01T12:00:00Z") == "MARCH 1, 2025"

    def test_invalid_string_returns_original(self) -> None:
        assert format_date("not-a-date") == "not-a-date"

    def test_empty_string_returns_original(self) -> None:
        assert format_date("") == ""

    def test_uppercase_month_names(self) -> None:
        # Verify all month names are uppercase
        result = format_date("2025-06-15T00:00:00Z")
        assert result == "JUNE 15, 2025"
        assert result == result.upper() or result[0:4] == result[0:4].upper()


# ---------------------------------------------------------------------------
# score_band_color tests
# ---------------------------------------------------------------------------


class TestScoreBandColor:
    """Tests for score_band_color filter."""

    def test_developing(self) -> None:
        assert score_band_color("Developing") == "#d32f2f"

    def test_competent(self) -> None:
        assert score_band_color("Competent") == "#f57c00"

    def test_effective(self) -> None:
        assert score_band_color("Effective") == "#388e3c"

    def test_exceptional(self) -> None:
        assert score_band_color("Exceptional") == "#1565c0"

    def test_unknown_band_returns_gray(self) -> None:
        assert score_band_color("Unknown") == "#757575"

    def test_empty_string_returns_gray(self) -> None:
        assert score_band_color("") == "#757575"


# ---------------------------------------------------------------------------
# score_to_arc_degrees tests
# ---------------------------------------------------------------------------


class TestScoreToArcDegrees:
    """Tests for score_to_arc_degrees filter."""

    def test_zero_score(self) -> None:
        assert score_to_arc_degrees(0.0) == 0.0

    def test_max_score(self) -> None:
        assert score_to_arc_degrees(10.0) == 180.0

    def test_midpoint_score(self) -> None:
        assert score_to_arc_degrees(5.0) == 90.0

    def test_score_below_zero_clamped(self) -> None:
        assert score_to_arc_degrees(-1.0) == 0.0

    def test_score_above_ten_clamped(self) -> None:
        assert score_to_arc_degrees(12.0) == 180.0

    def test_linear_scaling(self) -> None:
        # Each unit of score = 18 degrees
        assert score_to_arc_degrees(1.0) == 18.0
        assert score_to_arc_degrees(2.5) == 45.0


# ---------------------------------------------------------------------------
# gauge_arc_path tests
# ---------------------------------------------------------------------------


class TestGaugeArcPath:
    """Tests for gauge_arc_path SVG generation."""

    def test_zero_score_returns_empty(self) -> None:
        assert gauge_arc_path(0.0) == ""

    def test_nonzero_score_returns_valid_path(self) -> None:
        path = gauge_arc_path(5.0)
        assert path.startswith("M ")
        assert " A " in path

    def test_full_score_semicircle(self) -> None:
        path = gauge_arc_path(10.0)
        # Full semicircle: starts at left, ends at right
        assert path.startswith("M ")
        assert " A " in path
        # Check it contains arc command with correct radius
        assert "80.0 80.0" in path

    def test_start_point_is_at_left(self) -> None:
        # At score > 0, arc starts from the left side of the semicircle
        # Left side: cx - radius = 100 - 80 = 20
        path = gauge_arc_path(5.0, cx=100.0, cy=100.0, radius=80.0)
        # Start point should be at (20, 100) - left of center
        assert path.startswith("M 20.0 100.0")

    def test_custom_center_and_radius(self) -> None:
        path = gauge_arc_path(5.0, cx=50.0, cy=50.0, radius=40.0)
        assert path.startswith("M 10.0 50.0")
        assert "40.0 40.0" in path

    def test_sweep_flag_is_clockwise(self) -> None:
        path = gauge_arc_path(3.0)
        # Sweep flag should be 1 (clockwise)
        parts = path.split(" A ")[1].split()
        # Format: rx ry x-rotation large-arc sweep ex ey
        sweep_flag = parts[4]
        assert sweep_flag == "1"


# ---------------------------------------------------------------------------
# gauge_tick_path tests
# ---------------------------------------------------------------------------


class TestGaugeTickPath:
    """Tests for gauge_tick_path SVG generation."""

    def test_returns_line_path(self) -> None:
        path = gauge_tick_path(6.5)
        assert path.startswith("M ")
        assert " L " in path

    def test_tick_at_zero(self) -> None:
        path = gauge_tick_path(0.0, cx=100.0, cy=100.0)
        # At 0 degrees, both points should be on the left
        parts = path.replace("M ", "").replace(" L ", " ").split()
        # Both x values should be < cx (on the left side)
        x1 = float(parts[0])
        x2 = float(parts[2])
        assert x1 < 100.0
        assert x2 < 100.0

    def test_tick_at_boundary_values(self) -> None:
        # Band boundaries: 4.0, 6.5, 8.5
        for boundary in [4.0, 6.5, 8.5]:
            path = gauge_tick_path(boundary)
            assert path.startswith("M ")
            assert " L " in path


# ---------------------------------------------------------------------------
# dimension_bar_width tests
# ---------------------------------------------------------------------------


class TestDimensionBarWidth:
    """Tests for dimension_bar_width helper."""

    def test_zero_score(self) -> None:
        assert dimension_bar_width(0.0) == 0.0

    def test_max_score(self) -> None:
        assert dimension_bar_width(10.0) == 300.0

    def test_midpoint(self) -> None:
        assert dimension_bar_width(5.0) == 150.0

    def test_effective_boundary(self) -> None:
        assert dimension_bar_width(6.5) == 195.0

    def test_custom_max_width(self) -> None:
        assert dimension_bar_width(5.0, max_width=200.0) == 100.0

    def test_negative_clamped_to_zero(self) -> None:
        assert dimension_bar_width(-2.0) == 0.0

    def test_above_ten_clamped(self) -> None:
        assert dimension_bar_width(12.0) == 300.0


# ---------------------------------------------------------------------------
# dimension_target_x tests
# ---------------------------------------------------------------------------


class TestDimensionTargetX:
    """Tests for dimension_target_x helper."""

    def test_default_target(self) -> None:
        assert dimension_target_x() == 195.0

    def test_custom_target(self) -> None:
        assert dimension_target_x(5.0) == 150.0

    def test_custom_width(self) -> None:
        assert dimension_target_x(6.5, max_width=200.0) == 130.0


# ---------------------------------------------------------------------------
# timeline_segment_widths tests
# ---------------------------------------------------------------------------


class TestTimelineSegmentWidths:
    """Tests for timeline_segment_widths helper."""

    def test_basic_segments(self) -> None:
        result = timeline_segment_widths(10.0, 75.0, 15.0)
        assert result == {"open": 60.0, "body": 450.0, "close": 90.0}

    def test_equal_segments(self) -> None:
        result = timeline_segment_widths(33.33, 33.34, 33.33)
        assert abs(result["open"] - 200.0) < 1.0
        assert abs(result["body"] - 200.0) < 1.0
        assert abs(result["close"] - 200.0) < 1.0

    def test_custom_total_width(self) -> None:
        result = timeline_segment_widths(50.0, 30.0, 20.0, total_width=100.0)
        assert result == {"open": 50.0, "body": 30.0, "close": 20.0}

    def test_zero_segment(self) -> None:
        result = timeline_segment_widths(0.0, 100.0, 0.0)
        assert result["open"] == 0.0
        assert result["body"] == 600.0
        assert result["close"] == 0.0


# ---------------------------------------------------------------------------
# timeline_pin_x tests
# ---------------------------------------------------------------------------


class TestTimelinePinX:
    """Tests for timeline_pin_x helper."""

    def test_midpoint(self) -> None:
        assert timeline_pin_x(60.0, 120.0) == 300.0

    def test_start(self) -> None:
        assert timeline_pin_x(0.0, 120.0) == 0.0

    def test_end(self) -> None:
        assert timeline_pin_x(120.0, 120.0) == 600.0

    def test_zero_duration_returns_zero(self) -> None:
        assert timeline_pin_x(50.0, 0.0) == 0.0

    def test_custom_width(self) -> None:
        assert timeline_pin_x(50.0, 100.0, total_width=200.0) == 100.0

    def test_timestamp_beyond_duration_clamped(self) -> None:
        # Should be clamped to max width
        assert timeline_pin_x(200.0, 100.0) == 600.0


# ---------------------------------------------------------------------------
# register_filters tests
# ---------------------------------------------------------------------------


class TestRegisterFilters:
    """Tests for register_filters integration."""

    def test_registers_all_filters(self) -> None:
        """Verify all filters and globals are registered on a Jinja2 env."""
        try:
            import jinja2
        except ImportError:
            pytest.skip("jinja2 not installed")

        env = jinja2.Environment()
        register_filters(env)

        # Check filters
        assert "format_duration" in env.filters
        assert "format_date" in env.filters
        assert "score_band_color" in env.filters
        assert "score_to_arc_degrees" in env.filters

        # Check globals (helper functions)
        assert "gauge_arc_path" in env.globals
        assert "gauge_tick_path" in env.globals
        assert "dimension_bar_width" in env.globals
        assert "dimension_target_x" in env.globals
        assert "timeline_segment_widths" in env.globals
        assert "timeline_pin_x" in env.globals

    def test_filters_callable_from_template(self) -> None:
        """Verify filters work when called from a Jinja2 template."""
        try:
            import jinja2
        except ImportError:
            pytest.skip("jinja2 not installed")

        env = jinja2.Environment()
        register_filters(env)

        template = env.from_string("{{ 125.5 | format_duration }}")
        result = template.render()
        assert result == "2 min 05 sec"

    def test_globals_callable_from_template(self) -> None:
        """Verify global helper functions work from a Jinja2 template."""
        try:
            import jinja2
        except ImportError:
            pytest.skip("jinja2 not installed")

        env = jinja2.Environment()
        register_filters(env)

        template = env.from_string("{{ dimension_bar_width(6.5) }}")
        result = template.render()
        assert result == "195.0"
