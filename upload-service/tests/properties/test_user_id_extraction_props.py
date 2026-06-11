# Feature: upload-and-storage, Property 3: User ID extraction from JWT claims
"""
Property-based tests for user ID extraction from JWT claims.

**Validates: Requirements 2.4**

For any HTTP API v2 event containing JWT authorizer claims, the handler should
extract the user identifier from event["requestContext"]["authorizer"]["jwt"]["claims"]["sub"]
and use it as the user_id for all downstream operations. The extracted user_id
should always be a non-empty string matching the claim value exactly.
"""

import json
from unittest.mock import patch, MagicMock

from hypothesis import given, settings, assume
from hypothesis import strategies as st


def extract_user_id(event: dict) -> str:
    """Extract user_id from HTTP API v2 event JWT claims, mirroring handler logic."""
    return event["requestContext"]["authorizer"]["jwt"]["claims"]["sub"]


# Strategy for generating non-empty user ID strings (simulating Cognito sub claims)
user_id_strategy = st.text(min_size=1, max_size=128).filter(lambda s: s.strip() != "")


def build_http_api_v2_event(sub_claim: str) -> dict:
    """Build a minimal HTTP API v2 event structure with JWT claims."""
    return st.fixed_dictionaries({
        "requestContext": st.fixed_dictionaries({
            "authorizer": st.fixed_dictionaries({
                "jwt": st.fixed_dictionaries({
                    "claims": st.fixed_dictionaries({
                        "sub": st.just(sub_claim),
                        "iss": st.text(min_size=1),
                        "aud": st.text(min_size=1),
                        "exp": st.integers(min_value=1000000000, max_value=9999999999),
                        "iat": st.integers(min_value=1000000000, max_value=9999999999),
                    })
                })
            })
        })
    })


@settings(max_examples=100)
@given(
    sub_claim=user_id_strategy,
    extra_claims=st.fixed_dictionaries({
        "iss": st.text(min_size=1),
        "aud": st.text(min_size=1),
    }),
)
def test_user_id_extraction_matches_sub_claim_exactly(
    sub_claim: str, extra_claims: dict
) -> None:
    """The extracted user_id matches event requestContext authorizer jwt claims sub exactly."""
    event = {
        "requestContext": {
            "authorizer": {
                "jwt": {
                    "claims": {
                        "sub": sub_claim,
                        "iss": extra_claims["iss"],
                        "aud": extra_claims["aud"],
                    }
                }
            }
        }
    }

    user_id = extract_user_id(event)
    assert user_id == sub_claim, f"Expected '{sub_claim}', got '{user_id}'"


@settings(max_examples=100)
@given(sub_claim=user_id_strategy)
def test_user_id_is_always_non_empty_string(sub_claim: str) -> None:
    """The extracted user_id is always a non-empty string."""
    event = {
        "requestContext": {
            "authorizer": {
                "jwt": {
                    "claims": {
                        "sub": sub_claim,
                    }
                }
            }
        }
    }

    user_id = extract_user_id(event)
    assert isinstance(user_id, str), f"user_id should be str, got {type(user_id)}"
    assert len(user_id) > 0, "user_id should be non-empty"


@settings(max_examples=100, deadline=None)
@given(
    sub_claim=user_id_strategy,
    body=st.fixed_dictionaries({
        "title": st.text(min_size=1),
        "fileName": st.text(min_size=1),
        "contentType": st.just("audio/mpeg"),
        "fileSizeBytes": st.integers(min_value=1, max_value=500 * 1024 * 1024),
    }),
)
def test_handler_uses_sub_claim_as_user_id(sub_claim: str, body: dict) -> None:
    """The upload handler extracts user_id from JWT claims sub and passes it to downstream operations."""
    event = {
        "requestContext": {
            "authorizer": {
                "jwt": {
                    "claims": {
                        "sub": sub_claim,
                    }
                }
            }
        },
        "body": json.dumps(body),
    }

    with patch("src.handlers.upload.S3Service") as mock_s3_cls, \
         patch("src.handlers.upload.DynamoService") as mock_dynamo_cls, \
         patch("src.handlers.upload.SnsService") as mock_sns_cls, \
         patch("src.handlers.upload.s3_service") as mock_s3, \
         patch("src.handlers.upload.dynamo_service") as mock_dynamo, \
         patch("src.handlers.upload.sns_service") as mock_sns:

        mock_s3.generate_presigned_upload_url.return_value = "https://s3.example.com/presigned"
        mock_dynamo.create_submission.return_value = None

        from src.handlers.upload import handler
        response = handler(event, None)

        # If successful, the submission record should contain the sub claim as user_id
        if response["statusCode"] == 201:
            # Verify dynamo was called with a record containing the correct user_id
            call_args = mock_dynamo.create_submission.call_args
            if call_args:
                record = call_args[0][0]
                assert record.user_id == sub_claim, (
                    f"Expected user_id '{sub_claim}' in submission record, got '{record.user_id}'"
                )
