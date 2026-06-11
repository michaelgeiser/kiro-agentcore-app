# Feature: upload-and-storage, Property 1: File validation correctness
"""Property-based tests for file validation.

Validates: Requirements 1.3, 1.4, 1.5
"""

from hypothesis import given, settings
from hypothesis import strategies as st

from src.types import ACCEPTED_CONTENT_TYPES, MAX_FILE_SIZE_BYTES
from src.validation.file_validator import FileValidationInput, ValidationResult, validate_file

# Build the flat list of accepted MIME types
ACCEPTED_MIME_TYPES: list[str] = []
for types in ACCEPTED_CONTENT_TYPES.values():
    ACCEPTED_MIME_TYPES.extend(types)

# Strategies
valid_content_types = st.sampled_from(ACCEPTED_MIME_TYPES)

invalid_content_types = st.sampled_from([
    "text/plain",
    "application/pdf",
    "image/png",
    "image/jpeg",
    "application/octet-stream",
    "audio/flac",
    "video/avi",
    "application/json",
])

file_sizes = st.integers(min_value=0, max_value=1_073_741_824)


@settings(max_examples=100)
@given(
    content_type=valid_content_types,
    file_size=st.integers(min_value=0, max_value=MAX_FILE_SIZE_BYTES),
)
def test_valid_file_returns_valid_true(content_type: str, file_size: int) -> None:
    """Files with accepted content type AND size <= 500 MB must be valid.

    **Validates: Requirements 1.3, 1.4, 1.5**
    """
    input_data = FileValidationInput(
        file_name="test_file.mp3",
        content_type=content_type,
        file_size_bytes=file_size,
    )
    result = validate_file(input_data)

    assert result.valid is True
    assert result.error is None


@settings(max_examples=100)
@given(
    content_type=invalid_content_types,
    file_size=file_sizes,
)
def test_invalid_content_type_returns_valid_false(content_type: str, file_size: int) -> None:
    """Files with unsupported content type must be invalid with descriptive error.

    **Validates: Requirements 1.3, 1.4, 1.5**
    """
    input_data = FileValidationInput(
        file_name="test_file.txt",
        content_type=content_type,
        file_size_bytes=file_size,
    )
    result = validate_file(input_data)

    assert result.valid is False
    assert result.error is not None
    assert "Unsupported file type" in result.error


@settings(max_examples=100)
@given(
    content_type=valid_content_types,
    file_size=st.integers(min_value=MAX_FILE_SIZE_BYTES + 1, max_value=1_073_741_824),
)
def test_oversized_file_returns_valid_false(content_type: str, file_size: int) -> None:
    """Files exceeding 500 MB must be invalid with descriptive error.

    **Validates: Requirements 1.3, 1.4, 1.5**
    """
    input_data = FileValidationInput(
        file_name="test_file.mp4",
        content_type=content_type,
        file_size_bytes=file_size,
    )
    result = validate_file(input_data)

    assert result.valid is False
    assert result.error is not None
    assert "size" in result.error.lower()


@settings(max_examples=100)
@given(
    content_type=st.sampled_from(ACCEPTED_MIME_TYPES + [
        "text/plain", "application/pdf", "image/png", "audio/flac",
    ]),
    file_size=file_sizes,
)
def test_validation_biconditional(content_type: str, file_size: int) -> None:
    """valid=True iff content_type in accepted types AND file_size <= 500 MB.

    **Validates: Requirements 1.3, 1.4, 1.5**
    """
    input_data = FileValidationInput(
        file_name="test_file.dat",
        content_type=content_type,
        file_size_bytes=file_size,
    )
    result = validate_file(input_data)

    should_be_valid = (content_type in ACCEPTED_MIME_TYPES) and (file_size <= MAX_FILE_SIZE_BYTES)

    assert result.valid is should_be_valid
    if result.valid:
        assert result.error is None
    else:
        assert result.error is not None
