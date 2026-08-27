"""Jinja2 template filters and helper functions for the coaching report.

Provides pure functions for formatting, SVG generation, and visual
rendering logic used by the Jinja2 coaching report template.

All functions are pure (no side effects) and designed to be registered
as Jinja2 filters on the template environment.

Requirements covered: 5.4, 5.7, 5.8, 10.5
"""

import math
from datetime import datetime


# ---------------------------------------------------------------------------
# Score Band Color Mapping
# ---------------------------------------------------------------------------

_SCORE_BAND_COLORS: dict[str, str] = {
    "Developing": "#d32f2f",   # Red
    "Competent": "#f57c00",    # Orange
    "Effective": "#388e3c",    # Green
    "Exceptional": "#1565c0",  # Blue
}


# ---------------------------------------------------------------------------
# Jinja2 Filter Functions
# ---------------------------------------------------------------------------


def format_duration(seconds: float) -> str:
    """Format a duration in seconds to "M min SS sec".

    Args:
        seconds: Duration in seconds (>= 0).

    Returns:
        Formatted string like "2 min 05 sec".

    Examples:
        >>> format_duration(125.5)
        '2 min 05 sec'
        >>> format_duration(60.0)
        '1 min 00 sec'
        >>> format_duration(5.0)
        '0 min 05 sec'
    """
    total_seconds = max(0.0, float(seconds))
    minutes = int(total_seconds // 60)
    remaining_seconds = int(total_seconds % 60)
    return f"{minutes} min {remaining_seconds:02d} sec"


def format_date(iso_string: str) -> str:
    """Format an ISO 8601 date string to "MONTH DAY, YEAR" in uppercase.

    Args:
        iso_string: ISO 8601 date string (e.g., "2025-01-15T10:30:00Z").

    Returns:
        Formatted date string in uppercase (e.g., "JANUARY 15, 2025").
        Returns the original string if parsing fails.

    Examples:
        >>> format_date("2025-01-15T10:30:00Z")
        'JANUARY 15, 2025'
        >>> format_date("2026-08-05T16:00:00+00:00")
        'AUGUST 5, 2026'
    """
    try:
        dt = datetime.fromisoformat(iso_string.replace("Z", "+00:00"))
        month_name = dt.strftime("%B").upper()
        day = dt.day
        year = dt.year
        return f"{month_name} {day}, {year}"
    except (ValueError, AttributeError):
        return iso_string


def score_band_color(band: str) -> str:
    """Return the CSS color string for a given score band.

    Args:
        band: Score band name (Developing, Competent, Effective, Exceptional).

    Returns:
        CSS hex color string for the band. Defaults to gray if band
        is not recognized.

    Examples:
        >>> score_band_color("Developing")
        '#D32F2F'
        >>> score_band_color("Exceptional")
        '#1565C0'
    """
    return _SCORE_BAND_COLORS.get(band, "#757575")


def score_to_arc_degrees(score: float) -> float:
    """Convert a score (0–10) to arc degrees (0–180) for a semi-circular gauge.

    The gauge spans 180 degrees (a semicircle). Score 0 maps to 0 degrees,
    score 10 maps to 180 degrees, linearly.

    Args:
        score: Numeric score in the range 0.0 to 10.0.

    Returns:
        Arc angle in degrees (0.0 to 180.0).

    Examples:
        >>> score_to_arc_degrees(0.0)
        0.0
        >>> score_to_arc_degrees(5.0)
        90.0
        >>> score_to_arc_degrees(10.0)
        180.0
    """
    clamped = max(0.0, min(10.0, float(score)))
    return clamped * 18.0


# ---------------------------------------------------------------------------
# SVG Path Generation for Gauge Arc
# ---------------------------------------------------------------------------


def gauge_arc_path(
    score: float,
    cx: float = 100.0,
    cy: float = 100.0,
    radius: float = 80.0,
) -> str:
    """Generate SVG path data for a semi-circular gauge arc.

    The arc starts at the left (9 o'clock position) and sweeps clockwise
    to represent the score. A score of 0 produces no arc, a score of 10
    produces a full semicircle.

    Args:
        score: Numeric score in the range 0.0 to 10.0.
        cx: X-coordinate of the arc center.
        cy: Y-coordinate of the arc center.
        radius: Radius of the arc.

    Returns:
        SVG path 'd' attribute string for the arc.
        Returns empty string if score is 0 or effectively zero.

    Examples:
        >>> gauge_arc_path(5.0)  # 90 degrees = quarter circle
        'M 20.0 100.0 A 80.0 80.0 0 0 1 100.0 20.0'
    """
    degrees = score_to_arc_degrees(score)
    if degrees < 0.01:
        return ""

    # The arc starts at the left side of the semicircle (180 degrees in
    # standard math coordinates). We sweep clockwise.
    # Start angle: 180 degrees (left of center)
    # End angle: 180 - degrees (sweeping clockwise = reducing angle in math coords)
    start_angle_rad = math.pi  # 180 degrees
    end_angle_rad = math.pi - math.radians(degrees)

    start_x = cx + radius * math.cos(start_angle_rad)
    start_y = cy - radius * math.sin(start_angle_rad)

    end_x = cx + radius * math.cos(end_angle_rad)
    end_y = cy - radius * math.sin(end_angle_rad)

    # Large arc flag: 1 if angle > 180, else 0
    large_arc_flag = 1 if degrees > 180.0 else 0
    # Sweep flag: 1 for clockwise
    sweep_flag = 1

    # Round coordinates to 1 decimal for clean SVG output
    sx = round(start_x, 1)
    sy = round(start_y, 1)
    ex = round(end_x, 1)
    ey = round(end_y, 1)
    r = round(radius, 1)

    return f"M {sx} {sy} A {r} {r} 0 {large_arc_flag} {sweep_flag} {ex} {ey}"


def gauge_tick_path(
    score_value: float,
    cx: float = 100.0,
    cy: float = 100.0,
    inner_radius: float = 72.0,
    outer_radius: float = 88.0,
) -> str:
    """Generate SVG path data for a tick mark on the gauge at a given score.

    Used to mark band boundaries (4.0, 6.5, 8.5) on the gauge arc.

    Args:
        score_value: Score position for the tick (0.0 to 10.0).
        cx: X-coordinate of the gauge center.
        cy: Y-coordinate of the gauge center.
        inner_radius: Inner end of the tick line.
        outer_radius: Outer end of the tick line.

    Returns:
        SVG path 'd' attribute string for the tick line.
    """
    degrees = score_to_arc_degrees(score_value)
    angle_rad = math.pi - math.radians(degrees)

    inner_x = cx + inner_radius * math.cos(angle_rad)
    inner_y = cy - inner_radius * math.sin(angle_rad)

    outer_x = cx + outer_radius * math.cos(angle_rad)
    outer_y = cy - outer_radius * math.sin(angle_rad)

    ix = round(inner_x, 1)
    iy = round(inner_y, 1)
    ox = round(outer_x, 1)
    oy = round(outer_y, 1)

    return f"M {ix} {iy} L {ox} {oy}"


# ---------------------------------------------------------------------------
# Dimension Bar Scaling
# ---------------------------------------------------------------------------


def dimension_bar_width(score: float, max_width: float = 300.0) -> float:
    """Compute the width of a dimension bar for a given score.

    Scales a score in the range 0–10 to a pixel width for the bar.

    Args:
        score: Dimension score (0.0 to 10.0).
        max_width: Maximum bar width in pixels at score 10.

    Returns:
        Bar width in pixels.

    Examples:
        >>> dimension_bar_width(6.5)
        195.0
        >>> dimension_bar_width(10.0)
        300.0
        >>> dimension_bar_width(0.0)
        0.0
    """
    clamped = max(0.0, min(10.0, float(score)))
    return round(clamped * (max_width / 10.0), 1)


def dimension_target_x(target_score: float = 6.5, max_width: float = 300.0) -> float:
    """Compute the X position of the target line on a dimension bar.

    The target line marks where the "Effective" band starts (default 6.5).

    Args:
        target_score: The target score value (default 6.5).
        max_width: Maximum bar width in pixels.

    Returns:
        X position of the target line in pixels.

    Examples:
        >>> dimension_target_x(6.5)
        195.0
    """
    return round(target_score * (max_width / 10.0), 1)


# ---------------------------------------------------------------------------
# Talk Timeline Rendering
# ---------------------------------------------------------------------------


def timeline_segment_widths(
    open_percent: float,
    body_percent: float,
    close_percent: float,
    total_width: float = 600.0,
) -> dict[str, float]:
    """Compute pixel widths for talk timeline segments.

    Args:
        open_percent: Percentage of duration for the open segment (0–100).
        body_percent: Percentage of duration for the body segment (0–100).
        close_percent: Percentage of duration for the close segment (0–100).
        total_width: Total available width in pixels.

    Returns:
        Dictionary with 'open', 'body', 'close' keys mapped to pixel widths.

    Examples:
        >>> timeline_segment_widths(10.0, 75.0, 15.0)
        {'open': 60.0, 'body': 450.0, 'close': 90.0}
    """
    return {
        "open": round(open_percent / 100.0 * total_width, 1),
        "body": round(body_percent / 100.0 * total_width, 1),
        "close": round(close_percent / 100.0 * total_width, 1),
    }


def timeline_pin_x(
    timestamp_seconds: float,
    total_duration_seconds: float,
    total_width: float = 600.0,
) -> float:
    """Compute the X position of a finding pin on the talk timeline.

    Pins are placed proportionally along the timeline based on their
    timestamp relative to the total audio duration.

    Args:
        timestamp_seconds: The finding's timestamp in seconds.
        total_duration_seconds: Total audio duration in seconds.
        total_width: Total timeline width in pixels.

    Returns:
        X position in pixels for the pin. Returns 0.0 if duration is zero.

    Examples:
        >>> timeline_pin_x(60.0, 120.0)
        300.0
        >>> timeline_pin_x(0.0, 120.0)
        0.0
    """
    if total_duration_seconds <= 0.0:
        return 0.0
    ratio = max(0.0, min(1.0, timestamp_seconds / total_duration_seconds))
    return round(ratio * total_width, 1)


# ---------------------------------------------------------------------------
# Filter Registration
# ---------------------------------------------------------------------------


def register_filters(env: "jinja2.Environment") -> None:
    """Register all custom filters on a Jinja2 Environment.

    This function is called during ReportGeneratorV2 initialization
    to make all template filters available.

    Args:
        env: The Jinja2 Environment to register filters on.
    """
    env.filters["format_duration"] = format_duration
    env.filters["format_date"] = format_date
    env.filters["score_band_color"] = score_band_color
    env.filters["score_to_arc_degrees"] = score_to_arc_degrees
    env.filters["cos_val"] = _cos_val
    env.filters["sin_val"] = _sin_val
    env.filters["score_to_arc_path"] = _score_to_arc_path
    env.filters["severity_color"] = _severity_color
    env.filters["sort_by_severity"] = _sort_by_severity
    env.globals["gauge_arc_path"] = gauge_arc_path
    env.globals["gauge_tick_path"] = gauge_tick_path
    env.globals["dimension_bar_width"] = dimension_bar_width
    env.globals["dimension_target_x"] = dimension_target_x
    env.globals["timeline_segment_widths"] = timeline_segment_widths
    env.globals["timeline_pin_x"] = timeline_pin_x


# ---------------------------------------------------------------------------
# Additional Template Filters (used inline by the HTML template)
# ---------------------------------------------------------------------------


def _cos_val(radians: float) -> float:
    """Return the cosine of a value in radians (Jinja2 filter).

    Args:
        radians: Angle in radians.

    Returns:
        Cosine value.
    """
    return math.cos(float(radians))


def _sin_val(radians: float) -> float:
    """Return the sine of a value in radians (Jinja2 filter).

    Args:
        radians: Angle in radians.

    Returns:
        Sine value.
    """
    return math.sin(float(radians))


def _score_to_arc_path(score: float) -> str:
    """Generate SVG arc path data for the score gauge indicator.

    Wraps gauge_arc_path with the default parameters used in the template.

    Args:
        score: Numeric score in the range 0.0 to 10.0.

    Returns:
        SVG path 'd' attribute string.
    """
    return gauge_arc_path(score, cx=120.0, cy=130.0, radius=100.0)


_SEVERITY_COLORS: dict[str, str] = {
    "high": "#D32F2F",
    "medium": "#F9A825",
    "low": "#757575",
}


def _severity_color(severity: str) -> str:
    """Return the CSS color for a severity level.

    Args:
        severity: Severity string (high, medium, low).

    Returns:
        CSS hex color string.
    """
    return _SEVERITY_COLORS.get(severity, "#757575")


_SEVERITY_ORDER: dict[str, int] = {"high": 0, "medium": 1, "low": 2}


def _sort_by_severity(findings: list) -> list:
    """Sort findings by severity (high first, then medium, then low).

    Args:
        findings: List of finding dicts or objects with a 'severity' field.

    Returns:
        Sorted list of findings.
    """
    def _get_severity_key(finding):
        if isinstance(finding, dict):
            sev = finding.get("severity", "low")
            if hasattr(sev, "value"):
                sev = sev.value
        else:
            sev = getattr(finding, "severity", "low")
            if hasattr(sev, "value"):
                sev = sev.value
        return _SEVERITY_ORDER.get(sev, 3)

    return sorted(findings, key=_get_severity_key)
