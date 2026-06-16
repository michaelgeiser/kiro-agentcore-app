"""Report Generator service for the Agentic Evaluation module.

Produces comprehensive PDF coaching reports from aggregated evaluation
results using ReportLab, and stores them in S3.
"""

import io
import logging
from typing import Any

import boto3
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)

from models.data_models import EvaluationResult, get_report_path

logger = logging.getLogger(__name__)


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
    ) -> str:
        """Generate a PDF coaching report and upload it to S3.

        Args:
            submission_id: Unique identifier for the submission.
            user_id: Unique identifier for the user.
            results: Pre-loaded EvaluationResult objects from all agents.

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

        pdf_buffer = self._build_pdf(submission_id, results)

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
    ) -> io.BytesIO:
        """Build the PDF document in memory.

        Args:
            submission_id: Submission identifier for the report title.
            results: Evaluation results to include in the report.

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
        title_style = styles["Title"]
        heading_style = styles["Heading1"]
        subheading_style = styles["Heading2"]
        body_style = styles["BodyText"]
        bullet_style = ParagraphStyle(
            "BulletItem",
            parent=body_style,
            leftIndent=20,
            bulletIndent=10,
            spaceBefore=2,
            spaceAfter=2,
        )

        story: list[Any] = []

        # --- Title ---
        story.append(Paragraph("Presentation Coaching Report", title_style))
        story.append(Spacer(1, 0.2 * inch))
        story.append(
            Paragraph(f"Submission: {submission_id}", body_style)
        )
        story.append(Spacer(1, 0.3 * inch))

        # --- Executive Summary ---
        story.extend(
            self._build_executive_summary(results, heading_style, body_style)
        )

        # --- Per-Dimension Detailed Feedback ---
        story.extend(
            self._build_dimension_sections(
                results, heading_style, subheading_style, body_style, bullet_style
            )
        )

        # --- Overall Coaching Assessment ---
        story.extend(
            self._build_coaching_assessment(
                results, heading_style, body_style, bullet_style
            )
        )

        doc.build(story)
        buffer.seek(0)
        return buffer

    def _build_executive_summary(
        self,
        results: list[EvaluationResult],
        heading_style: ParagraphStyle,
        body_style: ParagraphStyle,
    ) -> list[Any]:
        """Build the Executive Summary section.

        Args:
            results: All evaluation results.
            heading_style: Style for the section heading.
            body_style: Style for body text.

        Returns:
            List of flowable elements for the executive summary.
        """
        elements: list[Any] = []
        elements.append(Paragraph("Executive Summary", heading_style))
        elements.append(Spacer(1, 0.1 * inch))

        if results:
            avg_score = sum(r.score for r in results) / len(results)
        else:
            avg_score = 0.0

        dimension_count = len(results)

        elements.append(
            Paragraph(
                f"This report covers <b>{dimension_count}</b> evaluation "
                f"dimension{'s' if dimension_count != 1 else ''} with an "
                f"overall average score of <b>{avg_score:.1f}/10.0</b>.",
                body_style,
            )
        )
        elements.append(Spacer(1, 0.1 * inch))

        if results:
            dimension_summary = ", ".join(
                f"{r.dimension} ({r.score:.1f})" for r in results
            )
            elements.append(
                Paragraph(
                    f"Dimensions evaluated: {dimension_summary}",
                    body_style,
                )
            )

        elements.append(Spacer(1, 0.3 * inch))
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
        elements.append(Spacer(1, 0.1 * inch))

        for result in results:
            elements.append(
                Paragraph(
                    f"{result.dimension} (Score: {result.score:.1f}/10.0)",
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
        elements.append(Spacer(1, 0.1 * inch))

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
