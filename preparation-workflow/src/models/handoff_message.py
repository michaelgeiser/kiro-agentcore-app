"""Handoff message model published to the FIFO Handoff Queue."""

from pydantic import BaseModel, Field


class HandoffMessage(BaseModel):
    """Represents the message published to the Agentic Processing handoff queue.

    All string fields are required and non-empty. chunk_count must be >= 1.
    """

    submission_id: str = Field(..., min_length=1)
    user_id: str = Field(..., min_length=1)
    s3_file_key: str = Field(..., min_length=1)
    vector_store_location: str = Field(..., min_length=1)
    chunk_count: int = Field(..., ge=1)
    presentation_title: str = Field(..., min_length=1)
