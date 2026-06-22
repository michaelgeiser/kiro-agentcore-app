"""Report Generator service for the Agentic Evaluation module.

Produces comprehensive PDF coaching reports from aggregated evaluation
results using ReportLab, and stores them in S3.
"""

import io
import logging
import os
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

# Model used for generating executive summary narrative
_REPORT_MODEL_ID = os.environ.get(
    "REPORT_MODEL_ID",
    os.environ.get("EVALUATION_MODEL_ID", "us.anthropic.claude-sonnet-4-6"),
)

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
# Executive Summary System Prompt
# ---------------------------------------------------------------------------

_EXECUTIVE_SUMMARY_SYSTEM_PROMPT = """You are a presentation coaching expert writing the executive summary \
section of a coaching report. Your job is to synthesize evaluation data into a \
concise, insightful narrative that helps the presenter understand their \
performance and what to focus on next.

Write in plain prose paragraphs. Do NOT use bullet points, numbered lists, \
headers, or markdown formatting. Do NOT use bold or italic markup. Write \
flowing, natural paragraphs that read like expert coaching feedback.

Your executive summary MUST include these elements in 3-4 short paragraphs:

1. COACHING DIAGNOSIS AND SCORE INTERPRETATION (first paragraph):
   - Open with a one-sentence coaching diagnosis that captures the overall \
character of the presentation (e.g., "This was a technically clear and \
conversational presentation, but it needs stronger audience engagement and a \
more memorable close.")
   - Include the overall average score and interpret what it means in plain \
language. A 5.9 might be "solid but unpolished" or "technically credible but \
not yet persuasive." A 7.5 might be "strong fundamentals with room to sharpen \
impact." Do not just restate the number.

2. STRENGTHS AS NARRATIVE (second paragraph):
   - Combine the strongest points into one flowing paragraph. Do not list \
them. Weave them into a narrative about what the presenter does well. Focus on \
the pattern, not individual items. For example: "The real strength here is \
clean delivery combined with strong technical command and a conversational \
tone that makes complex concepts accessible."

3. HIGHEST-LEVERAGE IMPROVEMENTS (third paragraph):
   - Identify the 2-3 changes most likely to move the overall score. Do not \
list every issue. Pick the improvements that cut across multiple dimensions. \
Explain WHY these matter more than other issues. Frame them as opportunities, \
not failures.

4. NEXT-PRACTICE TARGET (end of third or fourth paragraph):
   - End with a concrete coaching assignment for the next recording or \
presentation. Be specific and actionable. Example: "For the next recording, \
focus on a stronger opening hook, one moment of audience interaction, and a \
30-second close that recaps value and gives a clear next step."

CONSTRAINTS:
- Keep the total summary to 3-4 paragraphs that fit on approximately one page.
- Use dimension display names (Delivery, Structure, Executive Presence, etc.) \
when referencing specific areas.
- Be direct and confident in your coaching voice. You are an expert.
- Do not hedge excessively or use filler phrases like "overall" repeatedly.
- Do not start sentences with "The presenter" or "The speaker" more than once.
- Write at a professional coaching level, not an academic assessment level.
- Do not include any XML tags, markdown, or formatting in your response.
- Output ONLY the executive summary text, nothing else.
"""


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
        """Build the Executive Summary section using LLM-generated narrative.

        Calls an LLM to synthesize a coaching-style narrative executive summary
        from the evaluation results. Falls back to a basic score summary if the
        LLM call fails.

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

        if not results:
            elements.append(
                Paragraph("No evaluation results available.", body_style)
            )
            return elements

        avg_score = sum(r.score for r in results) / len(results)

        # Try to generate a narrative executive summary via LLM
        narrative = self._generate_executive_summary_narrative(results, avg_score)

        if narrative:
            # Split narrative into paragraphs and render
            paragraphs = [p.strip() for p in narrative.split("\n\n") if p.strip()]
            for para in paragraphs:
                elements.append(Paragraph(para, body_style))
                elements.append(Spacer(1, 0.08 * inch))
        else:
            # Fallback: basic static summary if LLM fails
            elements.extend(
                self._build_fallback_executive_summary(
                    results, avg_score, body_style, bullet_style
                )
            )

        return elements

    def _generate_executive_summary_narrative(
        self,
        results: list[EvaluationResult],
        avg_score: float,
    ) -> str | None:
        """Generate a narrative executive summary using an LLM.

        Provides structured evaluation data to the LLM and asks it to
        produce a coaching-style narrative summary.

        Args:
            results: All evaluation results.
            avg_score: The overall average score.

        Returns:
            The generated narrative text, or None if the call fails.
        """
        try:
            from strands import Agent

            logger.info(
                "Generating LLM executive summary narrative using model=%s",
                _REPORT_MODEL_ID,
            )

            # Build structured data for the LLM
            dimension_data = []
            for r in results:
                display_name = _get_dimension_display_name(r.dimension)
                dimension_data.append({
                    "dimension": display_name,
                    "score": r.score,
                    "strengths": r.strengths,
                    "improvements": r.improvements,
                    "findings": [
                        {
                            "category": f.category,
                            "detail": f.detail,
                            "severity": f.severity,
                            "suggestion": f.suggestion,
                        }
                        for f in r.findings
                    ],
                })

            prompt = (
                f"Generate an executive summary for a presentation coaching report.\n\n"
                f"Overall average score: {avg_score:.1f}/10.0\n"
                f"Number of dimensions evaluated: {len(results)}\n\n"
                f"Per-dimension evaluation data:\n"
            )
            for d in dimension_data:
                prompt += (
                    f"\n--- {d['dimension']} (Score: {d['score']:.1f}/10.0) ---\n"
                    f"Strengths: {', '.join(d['strengths']) if d['strengths'] else 'None noted'}\n"
                    f"Improvements: {', '.join(d['improvements']) if d['improvements'] else 'None noted'}\n"
                )
                if d["findings"]:
                    prompt += "Key findings:\n"
                    for f in d["findings"][:3]:
                        prompt += f"  - [{f['severity'].upper()}] {f['category']}: {f['detail']}\n"

            prompt += (
                f"\nWrite the executive summary now. "
                f"Remember: narrative prose, no bullet points, no headers, "
                f"3-4 paragraphs maximum, and end with a concrete next-practice target."
            )

            agent = Agent(
                system_prompt=_EXECUTIVE_SUMMARY_SYSTEM_PROMPT,
                model=_REPORT_MODEL_ID,
            )

            response = agent(prompt)
            narrative = str(response).strip()

            if len(narrative) < 50:
                logger.error(
                    "Executive summary narrative too short (%d chars). "
                    "Response was: %s. Using fallback.",
                    len(narrative),
                    narrative[:200],
                )
                return None

            logger.info(
                "LLM executive summary generated successfully (%d chars)",
                len(narrative),
            )
            return narrative

        except Exception as exc:
            logger.error(
                "Failed to generate LLM executive summary: %s. "
                "Model=%s. Using fallback summary.",
                exc,
                _REPORT_MODEL_ID,
                exc_info=True,
            )
            return None

    def _build_fallback_executive_summary(
        self,
        results: list[EvaluationResult],
        avg_score: float,
        body_style: ParagraphStyle,
        bullet_style: ParagraphStyle,
    ) -> list[Any]:
        """Build a narrative fallback executive summary without LLM.

        Produces a coaching-style narrative summary programmatically when
        the LLM call fails. Follows the same structure: diagnosis, score
        interpretation, strengths narrative, top improvements, next target.

        Args:
            results: All evaluation results.
            avg_score: The overall average score.
            body_style: Style for body text.
            bullet_style: Style for bullet items.

        Returns:
            List of flowable elements.
        """
        elements: list[Any] = []

        # Sort dimensions by score for identifying strengths and weaknesses
        sorted_results = sorted(results, key=lambda r: r.score, reverse=True)
        top_dims = sorted_results[:3]
        bottom_dims = sorted_results[-3:] if len(sorted_results) >= 3 else sorted_results

        # Score interpretation
        if avg_score >= 8.0:
            interpretation = "strong and polished"
        elif avg_score >= 7.0:
            interpretation = "solid with room to sharpen impact"
        elif avg_score >= 6.0:
            interpretation = "competent but not yet commanding"
        elif avg_score >= 5.0:
            interpretation = "technically adequate but lacking audience impact"
        elif avg_score >= 4.0:
            interpretation = "showing potential but needing focused development"
        else:
            interpretation = "at an early stage requiring foundational work"

        # Paragraph 1: Diagnosis and score
        top_strength_names = [_get_dimension_display_name(r.dimension) for r in top_dims[:2]]
        bottom_weakness_names = [
            _get_dimension_display_name(r.dimension)
            for r in bottom_dims
            if r.score < avg_score
        ][:2]

        diagnosis = (
            f"With an overall score of {avg_score:.1f}/10.0, this presentation is "
            f"{interpretation}."
        )
        if top_strength_names and bottom_weakness_names:
            diagnosis += (
                f" The strongest areas are {' and '.join(top_strength_names)}, "
                f"while {' and '.join(bottom_weakness_names)} "
                f"represent the clearest opportunities for growth."
            )
        elements.append(Paragraph(diagnosis, body_style))
        elements.append(Spacer(1, 0.08 * inch))

        # Paragraph 2: Strengths as narrative
        all_strengths: list[str] = []
        for r in top_dims:
            all_strengths.extend(r.strengths[:2])
        if all_strengths:
            strengths_text = (
                f"The presentation's core strengths center on "
                f"{', '.join(all_strengths[:3]).lower()}"
            )
            if len(all_strengths) > 3:
                strengths_text += f", and {all_strengths[3].lower()}"
            strengths_text += (
                ". These create a foundation to build on as other areas develop."
            )
            elements.append(Paragraph(strengths_text, body_style))
            elements.append(Spacer(1, 0.08 * inch))

        # Paragraph 3: Highest-leverage improvements + next target
        improvement_dims = [
            r for r in sorted_results if r.score < avg_score and r.improvements
        ]
        if improvement_dims:
            top_improvements = []
            for r in improvement_dims[:3]:
                if r.improvements:
                    top_improvements.append(r.improvements[0].lower())

            if top_improvements:
                improvements_text = (
                    f"The highest-leverage improvements are: "
                    f"{'; '.join(top_improvements)}. "
                    f"For the next presentation, focus on addressing these areas "
                    f"specifically, as they cut across multiple dimensions and "
                    f"would have the greatest impact on overall effectiveness."
                )
                elements.append(Paragraph(improvements_text, body_style))

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

        Provides a narrative coaching perspective that synthesizes findings
        across all dimensions into actionable guidance.

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

        if results:
            avg_score = sum(r.score for r in results) / len(results)
        else:
            avg_score = 0.0

        # Overall assessment narrative
        if avg_score >= 8.0:
            assessment = (
                "This is an excellent presentation that demonstrates strong command "
                "across multiple dimensions. The presenter has a solid foundation "
                "and should focus on refining the specific areas noted in the detailed "
                "feedback to move from very good to exceptional. At this level, small "
                "adjustments in the weakest dimensions can create outsized impact."
            )
        elif avg_score >= 6.0:
            assessment = (
                "This presentation shows solid fundamentals and clear strengths to "
                "build on. The gap between current performance and high impact is not "
                "about fixing major deficiencies — it is about sharpening specific "
                "skills that multiply the effectiveness of what already works well. "
                "The detailed feedback identifies exactly where targeted practice "
                "will yield the most improvement."
            )
        elif avg_score >= 4.0:
            assessment = (
                "This presentation shows promise and has identifiable strengths, but "
                "several dimensions need focused development to achieve the desired "
                "impact. The key is prioritization — not everything needs to improve "
                "at once. The two or three lowest-scoring dimensions represent the "
                "areas where improvement will be most noticeable to the audience."
            )
        else:
            assessment = (
                "This presentation has fundamental areas that need attention before "
                "the higher-level dimensions can shine. Working with a coach or "
                "practicing with structured feedback on the core skills identified "
                "below will build the foundation needed for more advanced development."
            )

        elements.append(Paragraph(assessment, body_style))
        elements.append(Spacer(1, 0.15 * inch))

        # Strengths as narrative paragraph (not bullets)
        all_strengths: list[str] = []
        for result in results:
            all_strengths.extend(result.strengths)

        if all_strengths:
            # Take top strengths and weave into a sentence
            unique_strengths = list(dict.fromkeys(all_strengths))[:6]
            strengths_narrative = (
                f"<b>Core strengths demonstrated:</b> "
                f"{', '.join(s.lower() for s in unique_strengths[:4])}"
            )
            if len(unique_strengths) > 4:
                strengths_narrative += (
                    f", and {', '.join(s.lower() for s in unique_strengths[4:])}"
                )
            strengths_narrative += "."
            elements.append(Paragraph(strengths_narrative, body_style))
            elements.append(Spacer(1, 0.1 * inch))

        # Improvements as prioritized narrative (not bullets)
        all_improvements: list[str] = []
        for result in results:
            all_improvements.extend(result.improvements)

        if all_improvements:
            unique_improvements = list(dict.fromkeys(all_improvements))[:5]
            improvements_narrative = (
                f"<b>Priority focus areas:</b> "
                f"{'; '.join(s.lower() for s in unique_improvements[:3])}"
            )
            if len(unique_improvements) > 3:
                improvements_narrative += (
                    f". Additional areas to develop: "
                    f"{'; '.join(s.lower() for s in unique_improvements[3:])}"
                )
            improvements_narrative += "."
            elements.append(Paragraph(improvements_narrative, body_style))
            elements.append(Spacer(1, 0.1 * inch))

        # Coaching next step
        sorted_results = sorted(results, key=lambda r: r.score)
        if sorted_results:
            weakest = sorted_results[0]
            weakest_name = _get_dimension_display_name(weakest.dimension)
            next_step = (
                f"<b>Recommended next step:</b> For the next presentation or recording, "
                f"make {weakest_name} the primary focus area. "
            )
            if weakest.improvements:
                next_step += (
                    f"Specifically: {weakest.improvements[0].lower()}. "
                )
            next_step += (
                "Concentrating on one dimension at a time produces faster, "
                "more sustainable improvement than trying to fix everything at once."
            )
            elements.append(Paragraph(next_step, body_style))
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
