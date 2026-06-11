# Feature: upload-and-storage, Property 2: Metadata validation correctness
"""
Property-based tests for the metadata validator.

**Validates: Requirements 1.2, 1.6**

For any metadata input object, validate_metadata should return
MetadataValidationResult(valid=True) if and only if presentation_title is a
non-empty, non-whitespace string AND original_file_name is present (non-None,
non-empty after stripping). For any input missing a required field or containing
only whitespace for the title, it should return MetadataValidationResult(valid=False)
with errors identifying each invalid field.
"""

from hypothesis import given, settings
from hypothesis import strategies as st

from src.validation.metadata_validator import MetadataInput, validate_metadata


# --- Strategies ---

# Valid title: at least one non-whitespace character
valid_titles = st.text(min_size=1).filter(lambda s: s.strip() != "")

# Invalid titles: None, empty string, or whitespace-only
invalid_titles = st.one_of(
    st.none(),
    st.just(""),
    st.text(alphabet=" \t\n\r", min_size=1),  # whitespace-only strings
)

# Valid file name: non-None, non-empty after stripping
valid_file_names = st.text(min_size=1).filter(lambda s: s.strip() != "")

# Invalid file names: None, empty string, or whitespace-only
invalid_file_names = st.one_of(
    st.none(),
    st.just(""),
    st.text(alphabet=" \t\n\r", min_size=1),  # whitespace-only strings
)

# Description is optional - can be anything
descriptions = st.one_of(st.none(), st.text())


@settings(max_examples=100)
@given(
    title=valid_titles,
    file_name=valid_file_names,
    description=descriptions,
)
def test_valid_metadata_returns_valid_true(
    title: str, file_name: str, description: str | None
) -> None:
    """valid=True iff presentation_title is non-empty/non-whitespace AND
    original_file_name is present."""
    input_data = MetadataInput(
        presentation_title=title,
        description=description,
        original_file_name=file_name,
    )
    result = validate_metadata(input_data)

    assert result.valid is True
    assert result.errors == []


@settings(max_examples=100)
@given(
    title=invalid_titles,
    file_name=valid_file_names,
    description=descriptions,
)
def test_invalid_title_returns_valid_false_with_title_error(
    title: str | None, file_name: str, description: str | None
) -> None:
    """valid=False with error identifying presentation_title when title is invalid."""
    input_data = MetadataInput(
        presentation_title=title,
        description=description,
        original_file_name=file_name,
    )
    result = validate_metadata(input_data)

    assert result.valid is False
    error_fields = [e.field for e in result.errors]
    assert "presentation_title" in error_fields


@settings(max_examples=100)
@given(
    title=valid_titles,
    file_name=invalid_file_names,
    description=descriptions,
)
def test_invalid_file_name_returns_valid_false_with_file_name_error(
    title: str, file_name: str | None, description: str | None
) -> None:
    """valid=False with error identifying original_file_name when file name is invalid."""
    input_data = MetadataInput(
        presentation_title=title,
        description=description,
        original_file_name=file_name,
    )
    result = validate_metadata(input_data)

    assert result.valid is False
    error_fields = [e.field for e in result.errors]
    assert "original_file_name" in error_fields


@settings(max_examples=100)
@given(
    title=invalid_titles,
    file_name=invalid_file_names,
    description=descriptions,
)
def test_both_invalid_returns_errors_for_both_fields(
    title: str | None, file_name: str | None, description: str | None
) -> None:
    """valid=False with errors identifying both fields when both are invalid."""
    input_data = MetadataInput(
        presentation_title=title,
        description=description,
        original_file_name=file_name,
    )
    result = validate_metadata(input_data)

    assert result.valid is False
    error_fields = [e.field for e in result.errors]
    assert "presentation_title" in error_fields
    assert "original_file_name" in error_fields
    assert len(result.errors) == 2
