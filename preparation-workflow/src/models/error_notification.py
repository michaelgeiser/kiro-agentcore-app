"""Workflow error notification model for the Preparation Workflow."""

from datetime import datetime

from pydantic import BaseModel, field_validator, Field


class WorkflowErrorNotification(BaseModel):
    """Error notification published to SNS when a workflow step fails.

    Contains all context needed for operational visibility: which submission
    failed, at what step, why, and when.
    """

    submission_id: str = Field(min_length=1)
    step_name: str = Field(min_length=1)
    error_type: str = Field(min_length=1)
    error_message: str = Field(min_length=1)
    retry_count_exhausted: int = Field(ge=0)
    timestamp: str = Field(min_length=1)
    queue_name: str | None = None

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
