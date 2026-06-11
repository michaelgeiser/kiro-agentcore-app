"""Property test for audio output path construction.

Property 5: Audio Output Path Construction
Validates: Requirements 3.2

For any valid user_id and submission_id strings, the constructed audio output
S3 key SHALL match the pattern processed/{user_id}/{submission_id}/audio.{format}
where the user_id and submission_id values in the path are exactly the input values.
"""

import pytest
from hypothesis import given, settings
from hypothesis.strategies import text, sampled_from

from src.services.audio_extraction import construct_output_key

# Strategy for generating non-empty user_id and submission_id strings
id_strategy = text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-",
    min_size=1,
    max_size=50,
)

# Supported audio output formats
AUDIO_FORMATS = ["mp3", "wav", "m4a"]


@pytest.mark.property
@settings(max_examples=100, deadline=500)
@given(
    user_id=id_strategy,
    submission_id=id_strategy,
    output_format=sampled_from(AUDIO_FORMATS),
)
def test_output_key_matches_expected_pattern(
    user_id: str, submission_id: str, output_format: str
) -> None:
    """**Validates: Requirements 3.2**

    For any valid user_id, submission_id, and output format, construct_output_key
    SHALL return a string matching processed/{user_id}/{submission_id}/audio.{format}.
    """
    result = construct_output_key(user_id, submission_id, output_format)
    expected = f"processed/{user_id}/{submission_id}/audio.{output_format}"

    assert result == expected


@pytest.mark.property
@settings(max_examples=100, deadline=500)
@given(
    user_id=id_strategy,
    submission_id=id_strategy,
    output_format=sampled_from(AUDIO_FORMATS),
)
def test_output_key_contains_exact_user_id(
    user_id: str, submission_id: str, output_format: str
) -> None:
    """**Validates: Requirements 3.2**

    The user_id value embedded in the constructed path SHALL match the input exactly.
    """
    result = construct_output_key(user_id, submission_id, output_format)

    # Extract user_id from path: processed/{user_id}/{submission_id}/audio.{format}
    parts = result.split("/")
    assert parts[1] == user_id


@pytest.mark.property
@settings(max_examples=100, deadline=500)
@given(
    user_id=id_strategy,
    submission_id=id_strategy,
    output_format=sampled_from(AUDIO_FORMATS),
)
def test_output_key_contains_exact_submission_id(
    user_id: str, submission_id: str, output_format: str
) -> None:
    """**Validates: Requirements 3.2**

    The submission_id value embedded in the constructed path SHALL match the input exactly.
    """
    result = construct_output_key(user_id, submission_id, output_format)

    # Extract submission_id from path: processed/{user_id}/{submission_id}/audio.{format}
    parts = result.split("/")
    assert parts[2] == submission_id
