"""Workflow configuration model loaded from SSM Parameter Store."""

from pydantic import BaseModel, field_validator, model_validator


class WorkflowConfig(BaseModel):
    """Configuration for the Preparation Workflow, loaded from SSM at runtime.

    All processing parameters (model selection, chunking strategy, retry counts,
    feature flags) are externalized to AWS Systems Manager Parameter Store.
    """

    embedding_model_id: str
    chunk_size_seconds: int
    chunk_overlap_seconds: int
    max_retry_attempts: int
    video_processing_enabled: bool
    vector_store_endpoint: str
    vector_store_type: str
    batch_size: int
    batch_processing_enabled: bool

    @field_validator("chunk_size_seconds")
    @classmethod
    def chunk_size_must_be_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("chunk_size_seconds must be greater than 0")
        return v

    @field_validator("chunk_overlap_seconds")
    @classmethod
    def chunk_overlap_must_be_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("chunk_overlap_seconds must be >= 0")
        return v

    @field_validator("max_retry_attempts")
    @classmethod
    def max_retry_must_be_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("max_retry_attempts must be >= 0")
        return v

    @field_validator("batch_size")
    @classmethod
    def batch_size_must_be_at_least_one(cls, v: int) -> int:
        if v < 1:
            raise ValueError("batch_size must be >= 1")
        return v

    @model_validator(mode="after")
    def chunk_overlap_less_than_chunk_size(self) -> "WorkflowConfig":
        if self.chunk_overlap_seconds >= self.chunk_size_seconds:
            raise ValueError(
                "chunk_overlap_seconds must be less than chunk_size_seconds"
            )
        return self
