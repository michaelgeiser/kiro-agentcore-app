"""Handoff message model published to the FIFO Handoff Queue."""

from pydantic import BaseModel, Field


class HandoffMessage(BaseModel):
    """Represents the message published to the Agentic Processing handoff queue.

    All string fields are required and non-empty. chunk_count must be >= 0
    (0 when embeddings are disabled).
    """

    submission_id: str = Field(..., min_length=1)
    user_id: str = Field(..., min_length=1)
    s3_file_key: str = Field(..., min_length=1)
    transcript_s3_key: str = Field(..., min_length=1)
    vector_store_location: str = Field(default="")
    chunk_count: int = Field(default=0, ge=0)
    presentation_title: str = Field(..., min_length=1)
