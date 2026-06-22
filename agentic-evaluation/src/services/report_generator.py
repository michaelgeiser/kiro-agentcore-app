"""Report Generator service for the Agentic Evaluation module.

Produces comprehensive PDF coaching reports from aggregated evaluation
results using ReportLab, and stores them in S3.
"""

import io
import logging
from datetime import datetime, timezone, timedelta
from typing import Any

import boto3
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)

from models.data_models import EvaluationResult, get_report_path

logger = logging.getLogger(__name__)

# US Eastern Time offset (ET = UTC-5, EDT = UTC-4)
# We use Eastern Time as a display convention per requirements.
_ET_OFFSET = timedelta(hours=-5)
_EDT_OFFSET = timedelta(hours=-4)

# ---------------------------------------------------------------------------
# Dimension Display Name Mapping
# ---------------------------------------------------------------------------

DIMENSION_DISPLAY_NAMES: dict[str, str] = {
    "delivery": "Delivery",
    "structure": "Structure",
    "executive_presence": "Executive Presence",
    "technical_communication": "Technical Communication",
    "audience_engagement": "Audience Engagement",
    "pacing": "Pacing",
    "persuasion": "Persuasion",
}


def _get_dimension_display_name(dimension: str) -> str:
    """Get the human-readable display name for a dimension.

    Args:
        dimension: The raw dimension key (e.g. 'executive_presence').

    Returns:
        The formatted display name (e.g. 'Executive Presence').
    """
    return DIMENSION_DISPLAY_NAMES.get(
        dimension, dimension.replace("_", " ").title()
    )


def _format_upload_date(iso_date: str) -> str:
    """Format an ISO 8601 date string to a human-readable ET format.

    Converts a UTC ISO 8601 timestamp to Eastern Time and formats it
    as "Month Day, Year HH:MM ET" (e.g. "June 22, 2026 12:15 ET").

    Args:
        iso_date: ISO 8601 date string (e.g. '2026-06-22T16:15:00Z').

    Returns:
        Formatted date string in ET, or the original string if parsing fails.
    """
    try:
        # Parse ISO 8601 timestamp
        dt = datetime.fromisoformat(iso_date.replace("Z", "+00:00"))

        # Convert to Eastern Time (use EDT offset: UTC-4 for simplicity,
        # as most US business activity falls in EDT months)
        # For a more accurate approach, pytz/zoneinfo would be needed,
        # but requirements state "setting the time to ET will be fine"
        et_dt = dt.astimezone(timezone(_EDT_OFFSET))

        # Format as "June 22, 2026 12:15 ET"
        # Use manual day formatting to avoid platform-specific strftime issues
        month_name = et_dt.strftime("%B")
        day = et_dt.day
        year = et_dt.year
        time_str = et_dt.strftime("%H:%M")
        return f"{month_name} {day}, {year} {time_str} ET"
    except (ValueError, AttributeError):
        # If parsing fails, return as-is
        return iso_date


# ---------------------------------------------------------------------------
# Submission Metadata (passed to report generator)
# ---------------------------------------------------------------------------


class SubmissionMetadata:
    """Holds submission metadata for inclusion in the coaching report header.

    Attributes:
        user_name: Display name of the user (from Cognito or fallback).
        presentation_title: Title of the presentation.
        description: Optional description of the presentation.
        file_name: Original uploaded file name.
        upload_date: ISO 8601 date string of when the file was uploaded.
    """

    def __init__(
        self,
        user_name: str,
        presentation_title: str,
        description: str | None = None,
        file_name: str | None = None,
        upload_date: str | None = None,
    ) -> None:
        self.user_name = user_name
        self.presentation_title = presentation_title
        self.description = description
        self.file_name = file_name
        self.upload_date = upload_date


class ReportGenerator:
    """Produces PDF coaching reports from aggregated evaluation results.

    Uses ReportLab to build a structured PDF document with executive summary,
    per-dimension detailed feedback, and overall coaching assessment. The
    generated PDF is uploaded to S3.
    """

    def __init__(self, bucket_name: str, s3_client: Any | None = None) -> None:
        """Initialize the ReportGenerator.

        Args:
            bucket_name: Name of the S3 bucket for storing reports.
            s3_client: Optional boto3 S3 client. If not provided, a default
                client is created.
        """
        self._bucket_name = bucket_name
        self._s3_client = s3_client or boto3.client("s3")

    def generate(
        self,
        submission_id: str,
        user_id: str,
        results: list[EvaluationResult],
        metadata: SubmissionMetadata | None = None,
    ) -> str:
        """Generate a PDF coaching report and upload it to S3.

        Args:
            submission_id: Unique identifier for the submission.
            user_id: Unique identifier for the user.
            results: Pre-loaded EvaluationResult objects from all agents.
            metadata: Optional submission metadata for the report header.

        Returns:
            The S3 key path where the report was stored.
        """
        logger.info(
            "Generating coaching report for submission_id=%s, user_id=%s, "
            "dimensions=%d",
            submission_id,
            user_id,
            len(results),
        )

        pdf_buffer = self._build_pdf(submission_id, results, metadata)

        s3_key = get_report_path(user_id, submission_id)
        self._upload_to_s3(pdf_buffer, s3_key)

        logger.info(
            "Coaching report uploaded to s3://%s/%s",
            self._bucket_name,
            s3_key,
        )
        return s3_key

    def _build_pdf(
        self,
        submission_id: str,
        results: list[EvaluationResult],
        metadata: SubmissionMetadata | None = None,
    ) -> io.BytesIO:
        """Build the PDF document in memory.

        Args:
            submission_id: Submission identifier for the report title.
            results: Evaluation results to include in the report.
            metadata: Optional submission metadata for the report header.

        Returns:
            BytesIO buffer containing the generated PDF.
        """
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=LETTER,
            rightMargin=0.75 * inch,
            leftMargin=0.75 * inch,
            topMargin=0.75 * inch,
            bottomMargin=0.75 * inch,
        )

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "ReportTitle",
            parent=styles["Title"],
            spaceAfter=6,
        )
        heading_style = ParagraphStyle(
            "ReportHeading",
            parent=styles["Heading1"],
            spaceBefore=6,
            spaceAfter=4,
        )
        subheading_style = ParagraphStyle(
            "ReportSubheading",
            parent=styles["Heading2"],
            spaceBefore=6,
            spaceAfter=3,
        )
        body_style = styles["BodyText"]
        bullet_style = ParagraphStyle(
            "BulletItem",
            parent=body_style,
            leftIndent=20,
            bulletIndent=10,
            spaceBefore=2,
            spaceAfter=2,
        )
        # Style for metadata info lines
        info_style = ParagraphStyle(
            "InfoItem",
            parent=body_style,
            spaceBefore=1,
            spaceAfter=1,
        )

        story: list[Any] = []

        # --- Title ---
        story.append(Paragraph("Presentation Coaching Report", title_style))
        story.append(Spacer(1, 0.1 * inch))

        # --- Submission Info (replaces old "Submission: {id}") ---
        if metadata:
            story.append(
                Paragraph(
                    f"<b>User:</b> {metadata.user_name}", info_style
                )
            )
            story.append(
                Paragraph(
                    f"<b>Presentation Title:</b> {metadata.presentation_title}",
                    info_style,
                )
            )
            if metadata.description:
                story.append(
                    Paragraph(
                        f"<b>Description:</b> {metadata.description}",
                        info_style,
                    )
                )
            if metadata.file_name:
                story.append(
                    Paragraph(
                        f"<b>Presentation File:</b> {metadata.file_name}",
                        info_style,
                    )
                )
            if metadata.upload_date:
                formatted_date = _format_upload_date(metadata.upload_date)
                story.append(
                    Paragraph(
                        f"<b>Uploaded:</b> {formatted_date}",
                        info_style,
                    )
                )
        else:
            # Fallback when no metadata is provided (backward compat)
            story.append(
                Paragraph(f"Submission: {submission_id}", body_style)
            )

        story.append(Spacer(1, 0.15 * inch))

        # --- Executive Summary ---
        story.extend(
            self._build_executive_summary(results, heading_style, body_style, bullet_style)
        )

        # --- Per-Dimension Detailed Feedback (starts on new page) ---
        story.append(PageBreak())
        story.extend(
            self._build_dimension_sections(
                results, heading_style, subheading_style, body_style, bullet_style
            )
        )

        # --- Overall Coaching Assessment (starts on new page) ---
        story.append(PageBreak())
        story.extend(
            self._build_coaching_assessment(
                results, heading_style, body_style, bullet_style
            )
        )

        doc.build(story, onFirstPage=self._add_page_number, onLaterPages=self._add_page_number)
        buffer.seek(0)
        return buffer

    @staticmethod
    def _add_page_number(canvas, doc):
        """Add page number to the footer of each page.

        Args:
            canvas: ReportLab canvas.
            doc: The document template.
        """
        page_num = canvas.getPageNumber()
        text = f"Page {page_num}"
        canvas.saveState()
        canvas.setFont("Helvetica", 9)
        canvas.drawCentredString(
            LETTER[0] / 2.0,
            0.5 * inch,
            text,
        )
        canvas.restoreState()

    def _build_executive_summary(
        self,
        results: list[EvaluationResult],
        heading_style: ParagraphStyle,
        body_style: ParagraphStyle,
        bullet_style: ParagraphStyle,
    ) -> list[Any]:
        """Build the Executive Summary section.

        Creates a concise summary designed to fit on the first page, including
        the overall score, per-dimension scores, top strengths, and key
        improvement areas.

        Args:
            results: All evaluation results.
            heading_style: Style for the section heading.
            body_style: Style for body text.
            bullet_style: Style for bullet items.

        Returns:
            List of flowable elements for the executive summary.
        """
        elements: list[Any] = []
        elements.append(Paragraph("Executive Summary", heading_style))

        if results:
            avg_score = sum(r.score for r in results) / len(results)
        else:
            avg_score = 0.0

        dimension_count = len(results)

        # Overall score summary
        elements.append(
            Paragraph(
                f"This report evaluates <b>{dimension_count}</b> "
                f"dimension{'s' if dimension_count != 1 else ''} with an "
                f"overall average score of <b>{avg_score:.1f}/10.0</b>.",
                body_style,
            )
        )
        elements.append(Spacer(1, 0.08 * inch))

        # Per-dimension score table
        if results:
            # Build a compact score summary
            score_lines = []
            for r in results:
                display_name = _get_dimension_display_name(r.dimension)
                score_lines.append(f"{display_name}: <b>{r.score:.1f}</b>/10.0")

            dimension_summary = " &nbsp;|&nbsp; ".join(score_lines)
            elements.append(
                Paragraph(dimension_summary, body_style)
            )
            elements.append(Spacer(1, 0.1 * inch))

        # Top strengths (limit to keep on first page)
        all_strengths: list[str] = []
        all_improvements: list[str] = []
        for r in results:
            all_strengths.extend(r.strengths)
            all_improvements.extend(r.improvements)

        if all_strengths:
            elements.append(
                Paragraph("<b>Key Strengths:</b>", body_style)
            )
            for strength in all_strengths[:5]:
                elements.append(
                    Paragraph(f"\u2022 {strength}", bullet_style)
                )
            if len(all_strengths) > 5:
                elements.append(
                    Paragraph(
                        f"<i>... and {len(all_strengths) - 5} more (see detailed sections)</i>",
                        bullet_style,
                    )
                )
            elements.append(Spacer(1, 0.08 * inch))

        # Priority improvements (limit to keep on first page)
        if all_improvements:
            elements.append(
                Paragraph("<b>Priority Improvements:</b>", body_style)
            )
            for improvement in all_improvements[:5]:
                elements.append(
                    Paragraph(f"\u2022 {improvement}", bullet_style)
                )
            if len(all_improvements) > 5:
                elements.append(
                    Paragraph(
                        f"<i>... and {len(all_improvements) - 5} more (see detailed sections)</i>",
                        bullet_style,
                    )
                )

        return elements

    def _build_dimension_sections(
        self,
        results: list[EvaluationResult],
        heading_style: ParagraphStyle,
        subheading_style: ParagraphStyle,
        body_style: ParagraphStyle,
        bullet_style: ParagraphStyle,
    ) -> list[Any]:
        """Build per-dimension detailed feedback sections.

        Args:
            results: All evaluation results.
            heading_style: Style for the main section heading.
            subheading_style: Style for dimension sub-headings.
            body_style: Style for body text.
            bullet_style: Style for bullet items.

        Returns:
            List of flowable elements for dimension feedback.
        """
        elements: list[Any] = []
        elements.append(
            Paragraph("Per-Dimension Detailed Feedback", heading_style)
        )

        for result in results:
            display_name = _get_dimension_display_name(result.dimension)
            elements.append(
                Paragraph(
                    f"{display_name} (Score: {result.score:.1f}/10.0)",
                    subheading_style,
                )
            )
            elements.append(Spacer(1, 0.05 * inch))

            # Findings
            if result.findings:
                elements.append(
                    Paragraph("<b>Findings:</b>", body_style)
                )
                for finding in result.findings:
                    elements.append(
                        Paragraph(
                            f"\u2022 [{finding.severity.upper()}] "
                            f"{finding.category}: {finding.detail}",
                            bullet_style,
                        )
                    )
                    if finding.suggestion:
                        elements.append(
                            Paragraph(
                                f"  \u2192 Suggestion: {finding.suggestion}",
                                bullet_style,
                            )
                        )
                elements.append(Spacer(1, 0.05 * inch))

            # Strengths
            if result.strengths:
                elements.append(
                    Paragraph("<b>Strengths:</b>", body_style)
                )
                for strength in result.strengths:
                    elements.append(
                        Paragraph(f"\u2022 {strength}", bullet_style)
                    )
                elements.append(Spacer(1, 0.05 * inch))

            # Improvements
            if result.improvements:
                elements.append(
                    Paragraph("<b>Areas for Improvement:</b>", body_style)
                )
                for improvement in result.improvements:
                    elements.append(
                        Paragraph(f"\u2022 {improvement}", bullet_style)
                    )

            elements.append(Spacer(1, 0.2 * inch))

        return elements

    def _build_coaching_assessment(
        self,
        results: list[EvaluationResult],
        heading_style: ParagraphStyle,
        body_style: ParagraphStyle,
        bullet_style: ParagraphStyle,
    ) -> list[Any]:
        """Build the Overall Coaching Assessment section.

        Aggregates strengths and improvements across all dimensions to
        provide a holistic coaching perspective.

        Args:
            results: All evaluation results.
            heading_style: Style for the section heading.
            body_style: Style for body text.
            bullet_style: Style for bullet items.

        Returns:
            List of flowable elements for the coaching assessment.
        """
        elements: list[Any] = []
        elements.append(
            Paragraph("Overall Coaching Assessment", heading_style)
        )

        # Aggregate all strengths and improvements
        all_strengths: list[str] = []
        all_improvements: list[str] = []
        for result in results:
            all_strengths.extend(result.strengths)
            all_improvements.extend(result.improvements)

        if results:
            avg_score = sum(r.score for r in results) / len(results)
        else:
            avg_score = 0.0

        # Overall assessment narrative
        if avg_score >= 8.0:
            assessment = (
                "Excellent presentation overall. The speaker demonstrates "
                "strong command across multiple dimensions. Focus on refining "
                "the few areas noted below to achieve mastery."
            )
        elif avg_score >= 6.0:
            assessment = (
                "Good presentation with solid fundamentals. There are clear "
                "strengths to build on, along with specific areas where "
                "targeted practice will yield significant improvement."
            )
        elif avg_score >= 4.0:
            assessment = (
                "The presentation shows promise but has several areas that "
                "would benefit from focused development. Prioritize the "
                "improvement areas listed below for the greatest impact."
            )
        else:
            assessment = (
                "The presentation has fundamental areas that need attention. "
                "Consider working with a coach or mentor to develop the core "
                "skills identified in the improvement areas below."
            )

        elements.append(Paragraph(assessment, body_style))
        elements.append(Spacer(1, 0.15 * inch))

        # Top strengths
        if all_strengths:
            elements.append(
                Paragraph("<b>Key Strengths:</b>", body_style)
            )
            for strength in all_strengths:
                elements.append(
                    Paragraph(f"\u2022 {strength}", bullet_style)
                )
            elements.append(Spacer(1, 0.1 * inch))

        # Top improvements
        if all_improvements:
            elements.append(
                Paragraph("<b>Priority Improvements:</b>", body_style)
            )
            for improvement in all_improvements:
                elements.append(
                    Paragraph(f"\u2022 {improvement}", bullet_style)
                )
            elements.append(Spacer(1, 0.1 * inch))

        return elements

    def _upload_to_s3(self, pdf_buffer: io.BytesIO, s3_key: str) -> None:
        """Upload the PDF buffer to S3.

        Args:
            pdf_buffer: In-memory PDF content.
            s3_key: Destination S3 key.
        """
        logger.debug(
            "Uploading report to s3://%s/%s", self._bucket_name, s3_key
        )
        self._s3_client.put_object(
            Bucket=self._bucket_name,
            Key=s3_key,
            Body=pdf_buffer.getvalue(),
            ContentType="application/pdf",
        )
