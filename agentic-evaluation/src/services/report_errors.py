"""Custom exception hierarchy for report generation.

Defines structured exceptions for the Report Generator pipeline. Each exception
carries a report_id for traceability and a descriptive message.

Error classification follows the workspace error handling standards:
- Unrecoverable (fail immediately): ReportValidationError, ReportRenderError
- Recoverable (retry with backoff): transient S3 failures
- ReportUploadError is raised only after all retries are exhausted for
  recoverable errors, or immediately for unrecoverable S3 errors.
"""


class ReportError(Exception):
    """Base exception for report generation errors.

    All report-related exceptions inherit from this class, enabling
    broad except clauses when needed while preserving specific handling.

    Attributes:
        report_id: The UUID string identifying the report that failed.
        message: A human-readable description of the error.
    """

    def __init__(self, report_id: str, message: str) -> None:
        self.report_id = report_id
        self.message = message
        super().__init__(f"[{report_id}] {message}")


class ReportValidationError(ReportError):
    """Raised when SynthesizedReport fails validation.

    Triggered when required fields are missing, scores are outside the
    valid range (0.0–10.0), word counts exceed limits, or dimension
    count is not exactly 7.

    Unrecoverable — do not retry.

    Attributes:
        invalid_fields: List of dicts identifying each invalid field and
            the reason it failed validation. Each entry has keys
            "field" (str) and "reason" (str).
    """

    def __init__(
        self,
        report_id: str,
        message: str,
        invalid_fields: list[dict[str, str]] | None = None,
    ) -> None:
        self.invalid_fields = invalid_fields or []
        super().__init__(report_id, message)


class ReportRenderError(ReportError):
    """Raised when Jinja2 template rendering or WeasyPrint PDF generation fails.

    This covers template-not-found, template syntax errors, and any
    WeasyPrint exception during HTML-to-PDF conversion.

    Unrecoverable — do not retry.

    Attributes:
        template_path: Path to the Jinja2 template that was being rendered.
        details: Additional error context (e.g., exception message, error
            location within the template).
    """

    def __init__(
        self,
        report_id: str,
        message: str,
        template_path: str | None = None,
        details: str | None = None,
    ) -> None:
        self.template_path = template_path
        self.details = details
        super().__init__(report_id, message)


class ReportUploadError(ReportError):
    """Raised when S3 upload fails after retries are exhausted.

    For recoverable errors (throttling, timeout, service unavailable),
    this is raised only after all retry attempts with exponential backoff
    have been exhausted.

    For unrecoverable S3 errors (access denied, bucket not found, invalid
    credentials), this is raised immediately without retrying.

    Unrecoverable at this point — the caller should treat this as a
    terminal failure and update submission status accordingly.
    """

    pass
