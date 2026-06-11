"""Metadata field validation for upload submissions."""

from dataclasses import dataclass, field


@dataclass
class MetadataInput:
    """Input data for metadata validation."""

    presentation_title: str | None = None
    description: str | None = None
    original_file_name: str | None = None


@dataclass
class FieldError:
    """A validation error for a specific field."""

    field: str
    message: str


@dataclass
class MetadataValidationResult:
    """Result of metadata validation with field-level errors."""

    valid: bool
    errors: list[FieldError] = field(default_factory=list)


def validate_metadata(input_data: MetadataInput) -> MetadataValidationResult:
    """Validate required and optional metadata fields.

    Validates:
    - presentation_title is non-empty and non-whitespace
    - original_file_name is present (non-None and non-empty)

    Returns a MetadataValidationResult with field-level errors for each invalid field.
    """
    errors: list[FieldError] = []

    # Validate presentation_title: must be non-None and non-whitespace
    if input_data.presentation_title is None or input_data.presentation_title.strip() == "":
        errors.append(
            FieldError(
                field="presentation_title",
                message="Presentation title is required and must not be empty or whitespace only",
            )
        )

    # Validate original_file_name: must be present (non-None and non-empty)
    if input_data.original_file_name is None or input_data.original_file_name.strip() == "":
        errors.append(
            FieldError(
                field="original_file_name",
                message="Original file name is required",
            )
        )

    return MetadataValidationResult(
        valid=len(errors) == 0,
        errors=errors,
    )
