"""Audio chunk model representing a segment of audio content."""

from pydantic import BaseModel, Field, model_validator


class AudioChunk(BaseModel):
    """Represents a chunk of audio content after splitting.

    Each chunk has a sequential index, an S3 key for the stored chunk,
    timestamps marking its position in the original audio, and identifiers
    linking it back to the source submission.
    """

    chunk_index: int = Field(..., ge=0)
    s3_chunk_key: str = Field(..., min_length=1)
    timestamp_start_seconds: float = Field(..., ge=0.0)
    timestamp_end_seconds: float = Field(..., ge=0.0)
    submission_id: str = Field(..., min_length=1)
    user_id: str = Field(..., min_length=1)

    @model_validator(mode="after")
    def end_must_be_after_start(self) -> "AudioChunk":
        if self.timestamp_end_seconds <= self.timestamp_start_seconds:
            raise ValueError(
                "timestamp_end_seconds must be greater than timestamp_start_seconds"
            )
        return self
