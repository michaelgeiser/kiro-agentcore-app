"""Input message model for SQS messages from the Upload Service."""

from pydantic import BaseModel, Field


class InputMessage(BaseModel):
    """Represents the SQS message body received from the Upload Service.

    All fields are required non-empty strings.
    """

    submission_id: str = Field(..., min_length=1)
    user_id: str = Field(..., min_length=1)
    s3_bucket: str = Field(..., min_length=1)
    s3_file_key: str = Field(..., min_length=1)
    original_file_name: str = Field(..., min_length=1)
    presentation_title: str = Field(..., min_length=1)
