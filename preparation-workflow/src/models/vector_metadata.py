"""Vector metadata model stored alongside embeddings in the vector store."""

from pydantic import BaseModel, Field, model_validator


class VectorMetadata(BaseModel):
    """Metadata stored alongside each embedding vector in the vector store.

    Links each embedding back to its source submission, chunk position,
    and the model version used to generate it.
    """

    submission_id: str = Field(..., min_length=1)
    user_id: str = Field(..., min_length=1)
    chunk_index: int = Field(..., ge=0)
    chunk_timestamp_start: float = Field(..., ge=0.0)
    chunk_timestamp_end: float = Field(..., ge=0.0)
    embedding_model_version: str = Field(..., min_length=1)

    @model_validator(mode="after")
    def end_must_be_after_start(self) -> "VectorMetadata":
        if self.chunk_timestamp_end <= self.chunk_timestamp_start:
            raise ValueError(
                "chunk_timestamp_end must be greater than chunk_timestamp_start"
            )
        return self
