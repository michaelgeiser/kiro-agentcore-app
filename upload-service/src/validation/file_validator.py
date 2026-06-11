from dataclasses import dataclass

from shared_types import ACCEPTED_CONTENT_TYPES, MAX_FILE_SIZE_BYTES


@dataclass
class FileValidationInput:
    file_name: str
    content_type: str
    file_size_bytes: int


@dataclass
class ValidationResult:
    valid: bool
    error: str | None = None


def _get_accepted_mime_types() -> list[str]:
    """Flatten ACCEPTED_CONTENT_TYPES dict values into a single list of MIME types."""
    mime_types: list[str] = []
    for types in ACCEPTED_CONTENT_TYPES.values():
        mime_types.extend(types)
    return mime_types


def validate_file(input_data: FileValidationInput) -> ValidationResult:
    """Validate file type and size constraints."""
    accepted_types = _get_accepted_mime_types()

    if input_data.content_type not in accepted_types:
        accepted_formats = ", ".join(sorted(accepted_types))
        return ValidationResult(
            valid=False,
            error=f"Unsupported file type. Accepted formats: {accepted_formats}",
        )

    max_size_mb = MAX_FILE_SIZE_BYTES // (1024 * 1024)
    if input_data.file_size_bytes > MAX_FILE_SIZE_BYTES:
        return ValidationResult(
            valid=False,
            error=f"File size exceeds maximum of {max_size_mb} MB",
        )

    return ValidationResult(valid=True)
