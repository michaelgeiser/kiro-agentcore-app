"""Embedding result model returned from Bedrock invocation."""

from typing import List

from pydantic import BaseModel, Field, field_validator, model_validator


class EmbeddingResult(BaseModel):
    """Represents the result of invoking an embedding model on an audio chunk.

    Contains the embedding vector along with metadata linking it back to
    the source submission, chunk position, and model version used.
    """

    submission_id: str = Field(..., min_length=1)
    user_id: str = Field(..., min_length=1)
    chunk_index: int = Field(..., ge=0)
    chunk_timestamp_start: float = Field(..., ge=0.0)
    chunk_timestamp_end: float = Field(..., ge=0.0)
    embedding_vector: List[float] = Field(...)
    embedding_model_version: str = Field(..., min_length=1)

    @field_validator("embedding_vector")
    @classmethod
    def embedding_vector_must_be_non_empty(cls, v: List[float]) -> List[float]:
        if len(v) == 0:
            raise ValueError("embedding_vector must be a non-empty list")
        return v

    @model_validator(mode="after")
    def end_must_be_after_start(self) -> "EmbeddingResult":
        if self.chunk_timestamp_end <= self.chunk_timestamp_start:
            raise ValueError(
                "chunk_timestamp_end must be greater than chunk_timestamp_start"
            )
        return self
