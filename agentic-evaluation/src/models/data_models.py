"""Core data models for the Agentic Evaluation module.

Defines Pydantic v2 models for handoff messages, evaluation results,
agent descriptors, error notifications, session lifecycle, and retry
configuration. Also provides S3 path construction helpers.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ProcessingStatus(str, Enum):
    """Valid processing status values for DynamoDB."""

    PENDING = "Pending"
    PROCESSING = "Processing"
    EVALUATING = "Evaluating"
    REPORT_GENERATING = "Report_Generating"
    COMPLETED = "Completed"
    FAILED = "Failed"


# ---------------------------------------------------------------------------
# Handoff Message (consumed from SQS FIFO queue)
# ---------------------------------------------------------------------------


class HandoffMessage(BaseModel):
    """Message received from the Preparation Workflow handoff queue.

    All string fields are required and non-empty. chunk_count must be >= 1.
    """

    submission_id: str = Field(..., min_length=1)
    user_id: str = Field(..., min_length=1)
    s3_file_key: str = Field(..., min_length=1)
    vector_store_location: str = Field(..., min_length=1)
    chunk_count: int = Field(..., ge=1)
    presentation_title: str = Field(..., min_length=1)


# ---------------------------------------------------------------------------
# Evaluation Models
# ---------------------------------------------------------------------------


class Finding(BaseModel):
    """A single observation from an evaluation agent."""

    category: str = Field(..., min_length=1)
    detail: str = Field(..., min_length=1)
    severity: str = Field(..., pattern=r"^(low|medium|high)$")
    suggestion: str = Field(..., min_length=1)


class EvaluationResult(BaseModel):
    """Structured evaluation result from a single agent.

    Scores are constrained to the range 0.0-10.0.
    """

    dimension: str = Field(..., min_length=1)
    score: float = Field(..., ge=0.0, le=10.0)
    findings: list[Finding] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    agent_id: str = Field(..., min_length=1)
    timestamp: str = Field(..., min_length=1)

    @field_validator("timestamp")
    @classmethod
    def validate_iso8601_timestamp(cls, v: str) -> str:
        """Validate that timestamp is in ISO 8601 format."""
        try:
            datetime.fromisoformat(v.replace("Z", "+00:00"))
        except (ValueError, AttributeError) as e:
            raise ValueError(
                f"timestamp must be a valid ISO 8601 string, got: {v!r}"
            ) from e
        return v


class EvaluationInput(BaseModel):
    """Standard input for all evaluation agents."""

    submission_id: str = Field(..., min_length=1)
    s3_bucket: str = Field(..., min_length=1)
    s3_key: str = Field(..., min_length=1)
    dimension: str = Field(..., min_length=1)
    user_id: str = Field(..., min_length=1)


# ---------------------------------------------------------------------------
# Agent Registry
# ---------------------------------------------------------------------------


class AgentDescriptor(BaseModel):
    """Describes a registered evaluation agent."""

    agent_id: str = Field(..., min_length=1)
    dimension: str = Field(..., min_length=1)
    display_name: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    version: str = Field(..., min_length=1)
    enabled: bool = True
    tool_module: str = Field(..., min_length=1)


# ---------------------------------------------------------------------------
# Error Notification
# ---------------------------------------------------------------------------


class ErrorNotification(BaseModel):
    """Structured error notification published to SNS.

    Contains all context needed for operational visibility.
    """

    submission_id: str = Field(..., min_length=1)
    component_name: str = Field(..., min_length=1)
    error_type: str = Field(..., min_length=1)
    error_message: str = Field(..., min_length=1)
    retry_count_exhausted: int = Field(..., ge=0)
    timestamp: str = Field(..., min_length=1)

    @field_validator("timestamp")
    @classmethod
    def validate_iso8601_timestamp(cls, v: str) -> str:
        """Validate that timestamp is in ISO 8601 format."""
        try:
            datetime.fromisoformat(v.replace("Z", "+00:00"))
        except (ValueError, AttributeError) as e:
            raise ValueError(
                f"timestamp must be a valid ISO 8601 string, got: {v!r}"
            ) from e
        return v


# ---------------------------------------------------------------------------
# Session Result
# ---------------------------------------------------------------------------


class AgentFailure(BaseModel):
    """Records a failure that occurred during agent invocation.

    Captures the dimension being evaluated, the agent identifier,
    and the error details for partial failure reporting.
    """

    dimension: str = Field(..., min_length=1)
    agent_id: str = Field(..., min_length=1)
    error: str = Field(..., min_length=1)


class SessionResult(BaseModel):
    """Result of a complete evaluation session."""

    submission_id: str = Field(..., min_length=1)
    status: ProcessingStatus
    evaluation_results: list[EvaluationResult] = Field(default_factory=list)
    report_path: str | None = None
    failure_reason: str | None = None
    agent_failures: list[AgentFailure] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Retry Configuration
# ---------------------------------------------------------------------------


class RetryConfig(BaseModel):
    """Configuration for retry behavior with exponential backoff."""

    max_attempts: int = Field(default=3, ge=1)
    base_delay_seconds: float = Field(default=1.0, gt=0.0)
    backoff_multiplier: float = Field(default=2.0, ge=1.0)
    max_delay_seconds: float = Field(default=30.0, gt=0.0)
    jitter: bool = True


# ---------------------------------------------------------------------------
# S3 Path Construction Helpers
# ---------------------------------------------------------------------------


def get_evaluation_result_path(submission_id: str, dimension_name: str) -> str:
    """Construct the S3 path for storing an evaluation result.

    Args:
        submission_id: Unique identifier for the submission.
        dimension_name: Name of the evaluation dimension.

    Returns:
        S3 key in the format: evaluations/{submission_id}/{dimension_name}/result.json
    """
    return f"evaluations/{submission_id}/{dimension_name}/result.json"


def get_report_path(user_id: str, submission_id: str) -> str:
    """Construct the S3 path for storing a coaching report PDF.

    Args:
        user_id: Unique identifier for the user.
        submission_id: Unique identifier for the submission.

    Returns:
        S3 key in the format: reports/{user_id}/{submission_id}/coaching_report.pdf
    """
    return f"reports/{user_id}/{submission_id}/coaching_report.pdf"
