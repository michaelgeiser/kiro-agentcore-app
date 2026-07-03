# Feature: admin-panel, Property 8: Non-administrator requests receive 403
"""
Property-based tests for admin authorization verification.

**Validates: Requirements 8.5, 8.6, 9.1, 9.2, 9.3**

For any API request to an administration endpoint where the JWT token's
cognito:groups claim does not contain "administrators", the verify_admin
function shall return (False, None). Conversely, when "administrators"
is present in the cognito:groups claim, verify_admin shall return (True, user_id).
"""

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from src.utils.admin_auth import verify_admin


# Strategy for generating non-empty user ID strings (simulating Cognito sub claims)
user_id_strategy = st.text(min_size=1, max_size=128).filter(lambda s: s.strip() != "")

# Strategy for generating group names that are NOT "administrators"
non_admin_group_strategy = st.text(min_size=1, max_size=64).filter(
    lambda s: s != "administrators" and s.strip() != ""
)


def build_event_with_groups(groups, sub: str) -> dict:
    """Build an API Gateway v2 event with the given cognito:groups and sub claim."""
    return {
        "requestContext": {
            "authorizer": {
                "jwt": {
                    "claims": {
                        "sub": sub,
                        "cognito:groups": groups,
                    }
                }
            }
        }
    }


@settings(max_examples=100)
@given(
    groups=st.lists(non_admin_group_strategy, min_size=0, max_size=10),
    sub=user_id_strategy,
)
def test_non_admin_groups_list_returns_false_none(groups: list, sub: str) -> None:
    """verify_admin returns (False, None) when cognito:groups is a list without 'administrators'."""
    assume("administrators" not in groups)
    event = build_event_with_groups(groups, sub)

    result = verify_admin(event)
    assert result == (False, None), (
        f"Expected (False, None) for non-admin groups {groups}, got {result}"
    )


@settings(max_examples=100)
@given(
    groups=st.lists(non_admin_group_strategy, min_size=0, max_size=10),
    sub=user_id_strategy,
)
def test_non_admin_groups_string_returns_false_none(groups: list, sub: str) -> None:
    """verify_admin returns (False, None) when cognito:groups is a space-separated string without 'administrators'."""
    assume("administrators" not in groups)
    # Join groups as space-separated string (matching Cognito string format)
    groups_str = " ".join(groups)
    # Ensure "administrators" isn't accidentally formed by joining
    assume("administrators" not in groups_str.split())
    event = build_event_with_groups(groups_str, sub)

    result = verify_admin(event)
    assert result == (False, None), (
        f"Expected (False, None) for non-admin groups string '{groups_str}', got {result}"
    )


@settings(max_examples=100)
@given(
    other_groups=st.lists(non_admin_group_strategy, min_size=0, max_size=5),
    sub=user_id_strategy,
)
def test_admin_groups_list_returns_true_user_id(other_groups: list, sub: str) -> None:
    """verify_admin returns (True, user_id) when cognito:groups list contains 'administrators'."""
    groups = other_groups + ["administrators"]
    event = build_event_with_groups(groups, sub)

    result = verify_admin(event)
    assert result == (True, sub), (
        f"Expected (True, '{sub}') for admin groups {groups}, got {result}"
    )


@settings(max_examples=100)
@given(
    other_groups=st.lists(non_admin_group_strategy, min_size=0, max_size=5),
    sub=user_id_strategy,
)
def test_admin_groups_string_returns_true_user_id(other_groups: list, sub: str) -> None:
    """verify_admin returns (True, user_id) when cognito:groups string contains 'administrators'."""
    groups = other_groups + ["administrators"]
    groups_str = " ".join(groups)
    event = build_event_with_groups(groups_str, sub)

    result = verify_admin(event)
    assert result == (True, sub), (
        f"Expected (True, '{sub}') for admin groups string '{groups_str}', got {result}"
    )


@settings(max_examples=100)
@given(sub=user_id_strategy)
def test_missing_groups_claim_returns_false_none(sub: str) -> None:
    """verify_admin returns (False, None) when cognito:groups claim is missing entirely."""
    event = {
        "requestContext": {
            "authorizer": {
                "jwt": {
                    "claims": {
                        "sub": sub,
                    }
                }
            }
        }
    }

    result = verify_admin(event)
    assert result == (False, None), (
        f"Expected (False, None) when groups claim missing, got {result}"
    )


@settings(max_examples=100)
@given(sub=user_id_strategy)
def test_empty_groups_claim_returns_false_none(sub: str) -> None:
    """verify_admin returns (False, None) when cognito:groups is an empty string."""
    event = build_event_with_groups("", sub)

    result = verify_admin(event)
    assert result == (False, None), (
        f"Expected (False, None) for empty groups claim, got {result}"
    )


@settings(max_examples=100)
@given(
    groups=st.lists(non_admin_group_strategy, min_size=0, max_size=5),
)
def test_missing_sub_claim_returns_false_none(groups: list) -> None:
    """verify_admin returns (False, None) when sub claim is missing, even with admin groups."""
    groups_with_admin = groups + ["administrators"]
    event = {
        "requestContext": {
            "authorizer": {
                "jwt": {
                    "claims": {
                        "cognito:groups": groups_with_admin,
                    }
                }
            }
        }
    }

    result = verify_admin(event)
    assert result == (False, None), (
        f"Expected (False, None) when sub claim missing, got {result}"
    )
