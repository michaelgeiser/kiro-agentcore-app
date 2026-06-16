# Feature: agentic-evaluation, Properties 1, 2, 5, 6: Data model serialization and validation
"""Property-based tests for data model serialization, validation, and S3 path construction.

Validates: Requirements 1.2, 1.4, 5.1, 5.2, 6.5
"""

import json

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.strategies import composite
from pydantic import ValidationError

from models.data_models import (
    EvaluationResult,
    Finding,
    HandoffMessage,
    get_evaluation_result_path,
    get_report_path,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

non_empty_text = st.text(min_size=1, max_size=100)
positive_int = st.integers(min_value=1, max_value=10_000)
score_float = st.floats(min_value=0.0, max_value=10.0, allow_nan=False)
severity_st = st.sampled_from(["low", "medium", "high"])

# ISO 8601 timestamps strategy
iso_timestamp = st.datetimes().map(lambda dt: dt.isoformat())


@composite
def valid_finding(draw):
    """Generate a valid Finding instance."""
    return Finding(
        category=draw(non_empty_text),
        detail=draw(non_empty_text),
        severity=draw(severity_st),
        suggestion=draw(non_empty_text),
    )


@composite
def valid_handoff_message(draw):
    """Generate a valid HandoffMessage instance."""
    return HandoffMessage(
        submission_id=draw(non_empty_text),
        user_id=draw(non_empty_text),
        s3_file_key=draw(non_empty_text),
        vector_store_location=draw(non_empty_text),
        chunk_count=draw(positive_int),
        presentation_title=draw(non_empty_text),
    )


@composite
def valid_evaluation_result(draw):
    """Generate a valid EvaluationResult instance."""
    findings = draw(st.lists(valid_finding(), min_size=0, max_size=5))
    strengths = draw(st.lists(non_empty_text, min_size=0, max_size=5))
    improvements = draw(st.lists(non_empty_text, min_size=0, max_size=5))

    return EvaluationResult(
        dimension=draw(non_empty_text),
        score=draw(score_float),
        findings=findings,
        strengths=strengths,
        improvements=improvements,
        agent_id=draw(non_empty_text),
        timestamp=draw(iso_timestamp),
    )


# S3 path-safe identifiers: no slashes, non-empty
path_safe_text = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P"),
        blacklist_characters="/\\",
    ),
    min_size=1,
    max_size=100,
).filter(lambda s: s.strip() != "")


# ---------------------------------------------------------------------------
# Property 1: Handoff message parsing round-trip
# ---------------------------------------------------------------------------


@pytest.mark.property
@settings(max_examples=100, deadline=500)
@given(message=valid_handoff_message())
def test_handoff_message_serialization_round_trip(message: HandoffMessage) -> None:
    """For any valid HandoffMessage, serialize to JSON and deserialize back
    SHALL produce an identical HandoffMessage with all fields preserved.

    **Validates: Requirements 1.2**
    """
    # Serialize to JSON
    json_str = message.model_dump_json()

    # Deserialize back
    restored = HandoffMessage.model_validate_json(json_str)

    # Assert equality
    assert restored.submission_id == message.submission_id
    assert restored.user_id == message.user_id
    assert restored.s3_file_key == message.s3_file_key
    assert restored.vector_store_location == message.vector_store_location
    assert restored.chunk_count == message.chunk_count
    assert restored.presentation_title == message.presentation_title
    assert restored == message


# ---------------------------------------------------------------------------
# Property 2: Invalid messages produce DLQ routing (validation rejection)
# ---------------------------------------------------------------------------


@composite
def invalid_handoff_message_dict(draw):
    """Generate HandoffMessage-like dicts with invalid fields.

    Produces dicts that violate the schema in various ways:
    - Empty strings where min_length=1 is required
    - Negative or zero chunk_count
    - Missing required fields
    """
    # Choose a corruption strategy
    strategy = draw(st.sampled_from([
        "empty_string_field",
        "negative_chunk_count",
        "zero_chunk_count",
        "missing_field",
    ]))

    # Start with a valid-looking dict
    base = {
        "submission_id": draw(non_empty_text),
        "user_id": draw(non_empty_text),
        "s3_file_key": draw(non_empty_text),
        "vector_store_location": draw(non_empty_text),
        "chunk_count": draw(positive_int),
        "presentation_title": draw(non_empty_text),
    }

    if strategy == "empty_string_field":
        # Set one or more string fields to empty string
        field = draw(st.sampled_from([
            "submission_id", "user_id", "s3_file_key",
            "vector_store_location", "presentation_title",
        ]))
        base[field] = ""

    elif strategy == "negative_chunk_count":
        base["chunk_count"] = draw(st.integers(max_value=-1))

    elif strategy == "zero_chunk_count":
        base["chunk_count"] = 0

    elif strategy == "missing_field":
        field = draw(st.sampled_from(list(base.keys())))
        del base[field]

    return base


@pytest.mark.property
@settings(max_examples=100, deadline=500)
@given(invalid_dict=invalid_handoff_message_dict())
def test_invalid_messages_produce_validation_error(invalid_dict: dict) -> None:
    """For any HandoffMessage-like dict with invalid fields (empty strings,
    negative chunk_count, missing fields), ValidationError SHALL be raised.

    **Validates: Requirements 1.4**
    """
    with pytest.raises(ValidationError):
        HandoffMessage(**invalid_dict)


# ---------------------------------------------------------------------------
# Property 5: S3 path construction correctness
# ---------------------------------------------------------------------------


@pytest.mark.property
@settings(max_examples=100, deadline=500)
@given(
    submission_id=path_safe_text,
    dimension_name=path_safe_text,
)
def test_s3_evaluation_path_correctness(
    submission_id: str, dimension_name: str
) -> None:
    """For any valid submission_id and dimension_name, the evaluation result path
    SHALL match the expected format and contain no double-slashes.

    **Validates: Requirements 5.1, 5.2**
    """
    path = get_evaluation_result_path(submission_id, dimension_name)

    # Matches expected format
    expected = f"evaluations/{submission_id}/{dimension_name}/result.json"
    assert path == expected

    # Contains no double-slashes
    assert "//" not in path


@pytest.mark.property
@settings(max_examples=100, deadline=500)
@given(
    user_id=path_safe_text,
    submission_id=path_safe_text,
)
def test_s3_report_path_correctness(user_id: str, submission_id: str) -> None:
    """For any valid user_id and submission_id, the report path
    SHALL match the expected format and contain no double-slashes.

    **Validates: Requirements 5.1, 6.5**
    """
    path = get_report_path(user_id, submission_id)

    # Matches expected format
    expected = f"reports/{user_id}/{submission_id}/coaching_report.pdf"
    assert path == expected

    # Contains no double-slashes
    assert "//" not in path


# ---------------------------------------------------------------------------
# Property 6: Evaluation result serialization round-trip
# ---------------------------------------------------------------------------


@pytest.mark.property
@settings(max_examples=100, deadline=500)
@given(result=valid_evaluation_result())
def test_evaluation_result_serialization_round_trip(
    result: EvaluationResult,
) -> None:
    """For any valid EvaluationResult, serialize to JSON and deserialize back
    SHALL produce an equivalent EvaluationResult with all fields preserved.

    **Validates: Requirements 5.2, 6.5**
    """
    # Serialize to JSON
    json_str = result.model_dump_json()

    # Deserialize back
    restored = EvaluationResult.model_validate_json(json_str)

    # Assert field equality
    assert restored.dimension == result.dimension
    assert restored.score == result.score
    assert restored.findings == result.findings
    assert restored.strengths == result.strengths
    assert restored.improvements == result.improvements
    assert restored.agent_id == result.agent_id
    assert restored.timestamp == result.timestamp
    assert restored == result
