"""Unit tests for admin authorization helper."""

from src.utils.admin_auth import verify_admin


def _make_event(groups=None, sub="user-123"):
    """Build a minimal API Gateway v2 event with JWT claims."""
    claims = {"sub": sub}
    if groups is not None:
        claims["cognito:groups"] = groups
    return {
        "requestContext": {
            "authorizer": {
                "jwt": {
                    "claims": claims,
                }
            }
        }
    }


def test_admin_with_administrators_group_string():
    event = _make_event(groups="administrators")
    is_admin, user_id = verify_admin(event)
    assert is_admin is True
    assert user_id == "user-123"


def test_admin_with_administrators_in_multiple_groups_string():
    event = _make_event(groups="users administrators managers")
    is_admin, user_id = verify_admin(event)
    assert is_admin is True
    assert user_id == "user-123"


def test_admin_with_administrators_group_list():
    event = _make_event(groups=["administrators"])
    is_admin, user_id = verify_admin(event)
    assert is_admin is True
    assert user_id == "user-123"


def test_admin_with_administrators_in_multiple_groups_list():
    event = _make_event(groups=["users", "administrators", "managers"])
    is_admin, user_id = verify_admin(event)
    assert is_admin is True
    assert user_id == "user-123"


def test_non_admin_with_other_groups_string():
    event = _make_event(groups="users managers")
    is_admin, user_id = verify_admin(event)
    assert is_admin is False
    assert user_id is None


def test_non_admin_with_other_groups_list():
    event = _make_event(groups=["users", "managers"])
    is_admin, user_id = verify_admin(event)
    assert is_admin is False
    assert user_id is None


def test_non_admin_with_empty_groups_string():
    event = _make_event(groups="")
    is_admin, user_id = verify_admin(event)
    assert is_admin is False
    assert user_id is None


def test_non_admin_with_empty_groups_list():
    event = _make_event(groups=[])
    is_admin, user_id = verify_admin(event)
    assert is_admin is False
    assert user_id is None


def test_non_admin_with_no_groups_claim():
    event = _make_event(groups=None)
    is_admin, user_id = verify_admin(event)
    assert is_admin is False
    assert user_id is None


def test_missing_request_context():
    event = {}
    is_admin, user_id = verify_admin(event)
    assert is_admin is False
    assert user_id is None


def test_missing_authorizer():
    event = {"requestContext": {}}
    is_admin, user_id = verify_admin(event)
    assert is_admin is False
    assert user_id is None


def test_missing_jwt():
    event = {"requestContext": {"authorizer": {}}}
    is_admin, user_id = verify_admin(event)
    assert is_admin is False
    assert user_id is None


def test_missing_claims():
    event = {"requestContext": {"authorizer": {"jwt": {}}}}
    is_admin, user_id = verify_admin(event)
    assert is_admin is False
    assert user_id is None


def test_missing_sub_claim():
    event = {
        "requestContext": {
            "authorizer": {
                "jwt": {
                    "claims": {"cognito:groups": "administrators"}
                }
            }
        }
    }
    is_admin, user_id = verify_admin(event)
    assert is_admin is False
    assert user_id is None


def test_none_event_value_in_request_context():
    event = {"requestContext": None}
    is_admin, user_id = verify_admin(event)
    assert is_admin is False
    assert user_id is None
