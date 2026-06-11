"""File validation result model for the Preparation Workflow."""

from pydantic import BaseModel, model_validator


class FileValidationResult(BaseModel):
    """Result of validating an uploaded file's format.

    When valid=True, file_type must be "audio" or "video".
    When valid=False, error should be present describing the validation failure.
    """

    valid: bool
    file_type: str | None = None
    error: str | None = None

    @model_validator(mode="after")
    def check_consistency(self) -> "FileValidationResult":
        if self.valid:
            if self.file_type not in ("audio", "video"):
                raise ValueError(
                    'file_type must be "audio" or "video" when valid=True'
                )
        else:
            if not self.error:
                raise ValueError("error must be present when valid=False")
        return self
