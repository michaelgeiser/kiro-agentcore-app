# Feature: agentic-evaluation, Property 9: Report contains all required sections
"""Property-based tests for report generation.

Validates: Requirements 6.2, 6.4
"""

import io

import pypdf
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.strategies import composite

from models.data_models import EvaluationResult, Finding
from services.report_generator import ReportGenerator

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Text strategy that avoids XML-special characters which break ReportLab's
# paragraph parser (<, >, &)
safe_text = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "Zs"),
        blacklist_characters="<>&",
    ),
    min_size=1,
    max_size=30,
).filter(lambda s: s.strip() != "")

score_float = st.floats(min_value=0.0, max_value=10.0, allow_nan=False)
severity_st = st.sampled_from(["low", "medium", "high"])
iso_timestamp = st.datetimes().map(lambda dt: dt.isoformat())

DIMENSIONS = [
    "delivery",
    "structure",
    "executive_presence",
    "technical_communication",
    "audience_engagement",
    "pacing",
    "persuasion",
]


@composite
def valid_finding(draw):
    """Generate a valid Finding instance with safe text."""
    return Finding(
        category=draw(safe_text),
        detail=draw(safe_text),
        severity=draw(severity_st),
        suggestion=draw(safe_text),
    )


@composite
def valid_evaluation_result(draw):
    """Generate a valid EvaluationResult with at least one strength and improvement."""
    findings = draw(st.lists(valid_finding(), min_size=1, max_size=3))
    strengths = draw(st.lists(safe_text, min_size=1, max_size=3))
    improvements = draw(st.lists(safe_text, min_size=1, max_size=3))

    return EvaluationResult(
        dimension=draw(st.sampled_from(DIMENSIONS)),
        score=draw(score_float),
        findings=findings,
        strengths=strengths,
        improvements=improvements,
        agent_id=draw(safe_text),
        timestamp=draw(iso_timestamp),
    )


@composite
def valid_evaluation_results_list(draw):
    """Generate a non-empty list of EvaluationResults (1-7 items)."""
    return draw(st.lists(valid_evaluation_result(), min_size=1, max_size=7))


def extract_pdf_text(pdf_buffer: io.BytesIO) -> str:
    """Extract all text from a PDF buffer using pypdf."""
    pdf_buffer.seek(0)
    reader = pypdf.PdfReader(pdf_buffer)
    text_parts = []
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            text_parts.append(page_text)
    return "\n".join(text_parts)


# ---------------------------------------------------------------------------
# Property 9: Report contains all required sections
# ---------------------------------------------------------------------------


@pytest.mark.property
@settings(max_examples=100, deadline=10000)
@given(results=valid_evaluation_results_list())
def test_report_contains_all_required_sections(
    results: list[EvaluationResult],
) -> None:
    """For any non-empty set of EvaluationResult instances covering one or more
    dimensions, the generated report content SHALL contain an executive summary
    section, a detailed feedback section for each dimension present in the input,
    at least one strength, at least one improvement suggestion, and an overall
    coaching assessment.

    **Validates: Requirements 6.2, 6.4**
    """
    # Create the ReportGenerator with a dummy bucket (we won't upload to S3)
    generator = ReportGenerator(bucket_name="test-bucket")

    # Generate the PDF in memory using the internal _build_pdf method
    pdf_buffer = generator._build_pdf("test-submission-id", results)

    # The PDF must be non-empty
    assert pdf_buffer.getvalue(), "Generated PDF is empty"

    # Extract text from the PDF
    pdf_text = extract_pdf_text(pdf_buffer)

    # 1. Executive Summary section
    assert "Executive Summary" in pdf_text, (
        "PDF missing 'Executive Summary' section"
    )

    # 2. Per-Dimension Detailed Feedback section heading
    assert "Per-Dimension Detailed Feedback" in pdf_text, (
        "PDF missing 'Per-Dimension Detailed Feedback' section"
    )

    # 3. Each dimension present in the input should appear in the report
    #    Dimensions are displayed with formatted names (e.g. 'executive_presence' -> 'Executive Presence')
    from services.report_generator import _get_dimension_display_name
    dimensions_in_input = {r.dimension for r in results}
    for dimension in dimensions_in_input:
        display_name = _get_dimension_display_name(dimension)
        assert display_name in pdf_text, (
            f"PDF missing dimension '{display_name}' feedback section"
        )

    # 4. Strengths section present
    assert "Strengths" in pdf_text, (
        "PDF missing 'Strengths' section"
    )

    # 5. Improvements section (Areas for Improvement or Priority Improvements)
    has_improvements = (
        "Areas for Improvement" in pdf_text
        or "Priority Improvements" in pdf_text
    )
    assert has_improvements, (
        "PDF missing improvements section "
        "('Areas for Improvement' or 'Priority Improvements')"
    )

    # 6. Overall Coaching Assessment section
    assert "Overall Coaching Assessment" in pdf_text, (
        "PDF missing 'Overall Coaching Assessment' section"
    )
