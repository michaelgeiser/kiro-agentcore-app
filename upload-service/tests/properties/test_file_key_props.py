# Feature: upload-and-storage, Property 4: File key generation follows naming convention
"""Property-based tests for file key generation.

Validates: Requirements 3.2, 3.3
"""
import os

from hypothesis import given, settings
from hypothesis import strategies as st

from src.utils.file_key_generator import generate_file_key

# Strategies
alphanumeric_text = st.text(
    min_size=1, alphabet=st.characters(whitelist_categories=("L", "N"))
)

extensions = st.sampled_from([".mp3", ".wav", ".m4a", ".aac", ".mp4", ".mov", ".webm"])

base_file_names = st.text(
    min_size=1, alphabet=st.characters(whitelist_categories=("L", "N"))
)


@settings(max_examples=100)
@given(
    user_id=alphanumeric_text,
    submission_id=alphanumeric_text,
    base_name=base_file_names,
    ext=extensions,
)
def test_file_key_matches_naming_convention(
    user_id: str, submission_id: str, base_name: str, ext: str
) -> None:
    """Generated file key must match uploads/{user_id}/{submission_id}/{original_file_name} exactly.

    **Validates: Requirements 3.2, 3.3**
    """
    original_file_name = base_name + ext
    result = generate_file_key(user_id, submission_id, original_file_name)

    expected = f"uploads/{user_id}/{submission_id}/{original_file_name}"
    assert result == expected


@settings(max_examples=100)
@given(
    user_id=alphanumeric_text,
    submission_id=alphanumeric_text,
    base_name=base_file_names,
    ext=extensions,
)
def test_file_key_preserves_extension(
    user_id: str, submission_id: str, base_name: str, ext: str
) -> None:
    """Generated file key must preserve the original file extension.

    **Validates: Requirements 3.2, 3.3**
    """
    original_file_name = base_name + ext
    result = generate_file_key(user_id, submission_id, original_file_name)

    _, result_ext = os.path.splitext(result)
    assert result_ext == ext
