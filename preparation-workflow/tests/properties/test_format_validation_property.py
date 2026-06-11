"""Property test for file format validation.

Property 3: File Format Validation Biconditional
Validates: Requirements 2.1

For any filename string, validate_format returns valid=True if and only if
the file extension (case-insensitive) is one of the accepted extensions.
When valid, file_type is "audio" for audio extensions and "video" for video extensions.
"""

import pytest
from hypothesis import given, settings, assume
from hypothesis.strategies import text, sampled_from, composite

from src.validation.format_validator import validate_format

AUDIO_EXTENSIONS = [".mp3", ".wav", ".m4a", ".aac"]
VIDEO_EXTENSIONS = [".mp4", ".mov", ".webm"]
ALL_VALID_EXTENSIONS = AUDIO_EXTENSIONS + VIDEO_EXTENSIONS

# Strategy for generating base filenames (non-empty, no dots to avoid accidental extensions)
base_name = text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_- ",
    min_size=1,
    max_size=50,
)


@composite
def mixed_case_extension(draw, extensions):
    """Generate an extension with randomized casing."""
    ext = draw(sampled_from(extensions))
    # Apply mixed case: randomly upper/lower each character
    case_text = draw(text(alphabet="01", min_size=len(ext), max_size=len(ext)))
    mixed = "".join(
        c.upper() if bit == "1" else c.lower()
        for c, bit in zip(ext, case_text)
    )
    return mixed


@pytest.mark.property
@settings(max_examples=100, deadline=500)
@given(
    name=base_name,
    ext=sampled_from(AUDIO_EXTENSIONS),
)
def test_valid_audio_extensions(name: str, ext: str) -> None:
    """**Validates: Requirements 2.1**

    For any base filename with an accepted audio extension,
    validate_format SHALL return valid=True with file_type="audio".
    """
    filename = name + ext
    result = validate_format(filename)

    assert result.valid is True
    assert result.file_type == "audio"
    assert result.error is None


@pytest.mark.property
@settings(max_examples=100, deadline=500)
@given(
    name=base_name,
    ext=sampled_from(VIDEO_EXTENSIONS),
)
def test_valid_video_extensions(name: str, ext: str) -> None:
    """**Validates: Requirements 2.1**

    For any base filename with an accepted video extension,
    validate_format SHALL return valid=True with file_type="video".
    """
    filename = name + ext
    result = validate_format(filename)

    assert result.valid is True
    assert result.file_type == "video"
    assert result.error is None


@pytest.mark.property
@settings(max_examples=100, deadline=500)
@given(
    name=base_name,
    ext=text(
        alphabet="abcdefghijklmnopqrstuvwxyz0123456789",
        min_size=1,
        max_size=5,
    ),
)
def test_invalid_extensions_rejected(name: str, ext: str) -> None:
    """**Validates: Requirements 2.1**

    For any filename with an extension NOT in the accepted set,
    validate_format SHALL return valid=False.
    """
    # Prepend dot to make it an extension
    full_ext = "." + ext
    # Ensure the generated extension is not accidentally a valid one
    assume(full_ext.lower() not in ALL_VALID_EXTENSIONS)

    filename = name + full_ext
    result = validate_format(filename)

    assert result.valid is False
    assert result.file_type is None
    assert result.error is not None


@pytest.mark.property
@settings(max_examples=100, deadline=500)
@given(
    name=base_name,
    ext=mixed_case_extension(ALL_VALID_EXTENSIONS),
)
def test_case_insensitive_validation(name: str, ext: str) -> None:
    """**Validates: Requirements 2.1**

    For any valid extension with arbitrary mixed casing,
    validate_format SHALL still return valid=True with correct file_type.
    """
    filename = name + ext
    result = validate_format(filename)

    ext_lower = ext.lower()
    assert result.valid is True
    if ext_lower in AUDIO_EXTENSIONS:
        assert result.file_type == "audio"
    else:
        assert result.file_type == "video"
