"""Unit tests for admin feature flags handler.

Validates: Requirements 8.3, 8.4, 8.5, 8.6
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from src.handlers.admin_feature_flags import handler


def _make_admin_event(method="GET", groups="administrators", sub="admin-user-1",
                      path_params=None, body=None):
    """Build an API Gateway v2 event with admin JWT claims."""
    claims = {"sub": sub}
    if groups is not None:
        claims["cognito:groups"] = groups

    event = {
        "requestContext": {
            "authorizer": {
                "jwt": {
                    "claims": claims,
                }
            },
            "http": {
                "method": method,
            },
        },
    }

    if path_params is not None:
        event["pathParameters"] = path_params

    if body is not None:
        event["body"] = body

    return event


def _make_non_admin_event(method="GET", groups="users", sub="regular-user-1",
                          path_params=None, body=None):
    """Build an API Gateway v2 event without admin group."""
    return _make_admin_event(method=method, groups=groups, sub=sub,
                             path_params=path_params, body=body)


class TestGetFeatureFlags:
    """Test GET /admin/feature-flags returns all 4 flags with correct boolean values."""

    @patch("src.handlers.admin_feature_flags.ssm_client")
    def test_get_returns_all_flags_enabled(self, mock_ssm):
        """GET returns all 4 flags with enabled=True when SSM values are 'true'."""
        mock_ssm.get_parameter.return_value = {
            "Parameter": {"Value": "true"}
        }

        event = _make_admin_event(method="GET")
        response = handler(event, None)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert "flags" in body
        assert len(body["flags"]) == 4

        flag_names = [f["name"] for f in body["flags"]]
        assert "video-processing-enabled" in flag_names
        assert "batch-processing-enabled" in flag_names
        assert "embeddings-enabled" in flag_names
        assert "local-mode" in flag_names

        for flag in body["flags"]:
            assert flag["enabled"] is True
            assert "description" in flag
            assert len(flag["description"]) > 0

    @patch("src.handlers.admin_feature_flags.ssm_client")
    def test_get_returns_flags_disabled(self, mock_ssm):
        """GET returns flags with enabled=False when SSM values are 'false'."""
        mock_ssm.get_parameter.return_value = {
            "Parameter": {"Value": "false"}
        }

        event = _make_admin_event(method="GET")
        response = handler(event, None)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert len(body["flags"]) == 4

        for flag in body["flags"]:
            assert flag["enabled"] is False

    @patch("src.handlers.admin_feature_flags.ssm_client")
    def test_get_returns_mixed_flag_states(self, mock_ssm):
        """GET correctly maps 'true'/'false' strings to boolean values."""
        # Return different values based on the parameter name
        def get_parameter_side_effect(**kwargs):
            name = kwargs["Name"]
            if "video-processing" in name or "embeddings" in name:
                return {"Parameter": {"Value": "true"}}
            return {"Parameter": {"Value": "false"}}

        mock_ssm.get_parameter.side_effect = get_parameter_side_effect

        event = _make_admin_event(method="GET")
        response = handler(event, None)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])

        flags_map = {f["name"]: f["enabled"] for f in body["flags"]}
        assert flags_map["video-processing-enabled"] is True
        assert flags_map["batch-processing-enabled"] is False
        assert flags_map["embeddings-enabled"] is True
        assert flags_map["local-mode"] is False


class TestPutFeatureFlag:
    """Test PUT /admin/feature-flags/{flag-name} updates single parameter in SSM."""

    @patch("src.handlers.admin_feature_flags.ssm_client")
    def test_put_updates_flag_to_true(self, mock_ssm):
        """PUT with enabled=true calls SSM put_parameter with correct params."""
        mock_ssm.put_parameter.return_value = {}

        event = _make_admin_event(
            method="PUT",
            path_params={"flag-name": "video-processing-enabled"},
            body=json.dumps({"enabled": True}),
        )
        response = handler(event, None)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["name"] == "video-processing-enabled"
        assert body["enabled"] is True

        mock_ssm.put_parameter.assert_called_once_with(
            Name="/prescoach/dev/feature-flags/video-processing-enabled",
            Value="true",
            Type="String",
            Overwrite=True,
        )

    @patch("src.handlers.admin_feature_flags.ssm_client")
    def test_put_updates_flag_to_false(self, mock_ssm):
        """PUT with enabled=false calls SSM put_parameter with 'false' value."""
        mock_ssm.put_parameter.return_value = {}

        event = _make_admin_event(
            method="PUT",
            path_params={"flag-name": "embeddings-enabled"},
            body=json.dumps({"enabled": False}),
        )
        response = handler(event, None)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["name"] == "embeddings-enabled"
        assert body["enabled"] is False

        mock_ssm.put_parameter.assert_called_once_with(
            Name="/prescoach/dev/feature-flags/embeddings-enabled",
            Value="false",
            Type="String",
            Overwrite=True,
        )

    @patch("src.handlers.admin_feature_flags.ssm_client")
    def test_put_updates_local_mode_flag(self, mock_ssm):
        """PUT correctly handles the local-mode flag."""
        mock_ssm.put_parameter.return_value = {}

        event = _make_admin_event(
            method="PUT",
            path_params={"flag-name": "local-mode"},
            body=json.dumps({"enabled": True}),
        )
        response = handler(event, None)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["name"] == "local-mode"
        assert body["enabled"] is True


class TestNonAdminAccess:
    """Test that non-admin requests return 403."""

    def test_non_admin_get_returns_403(self):
        """GET from non-admin user returns 403 Forbidden."""
        event = _make_non_admin_event(method="GET")
        response = handler(event, None)

        assert response["statusCode"] == 403
        body = json.loads(response["body"])
        assert "Forbidden" in body["message"] or "administrator" in body["message"]

    def test_non_admin_put_returns_403(self):
        """PUT from non-admin user returns 403 Forbidden."""
        event = _make_non_admin_event(
            method="PUT",
            path_params={"flag-name": "video-processing-enabled"},
            body=json.dumps({"enabled": True}),
        )
        response = handler(event, None)

        assert response["statusCode"] == 403
        body = json.loads(response["body"])
        assert "Forbidden" in body["message"] or "administrator" in body["message"]

    def test_empty_groups_returns_403(self):
        """Request with empty groups claim returns 403."""
        event = _make_admin_event(method="GET", groups="")
        response = handler(event, None)

        assert response["statusCode"] == 403

    def test_no_groups_claim_returns_403(self):
        """Request without cognito:groups claim returns 403."""
        event = _make_admin_event(method="GET", groups=None)
        response = handler(event, None)

        assert response["statusCode"] == 403


class TestInvalidFlagName:
    """Test that invalid/unknown flag names return 404."""

    @patch("src.handlers.admin_feature_flags.ssm_client")
    def test_unknown_flag_returns_404(self, mock_ssm):
        """PUT with unknown flag name returns 404 Not Found."""
        event = _make_admin_event(
            method="PUT",
            path_params={"flag-name": "nonexistent-flag"},
            body=json.dumps({"enabled": True}),
        )
        response = handler(event, None)

        assert response["statusCode"] == 404
        body = json.loads(response["body"])
        assert "Unknown feature flag" in body["message"]

        # SSM should never be called for invalid flags
        mock_ssm.put_parameter.assert_not_called()

    @patch("src.handlers.admin_feature_flags.ssm_client")
    def test_empty_flag_name_returns_400(self, mock_ssm):
        """PUT with empty path parameters returns 400."""
        event = _make_admin_event(
            method="PUT",
            path_params={},
            body=json.dumps({"enabled": True}),
        )
        response = handler(event, None)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert "Missing flag name" in body["message"]

    @patch("src.handlers.admin_feature_flags.ssm_client")
    def test_null_path_parameters_returns_400(self, mock_ssm):
        """PUT with null pathParameters returns 400."""
        event = _make_admin_event(
            method="PUT",
            path_params=None,
            body=json.dumps({"enabled": True}),
        )
        # Remove pathParameters key entirely
        event.pop("pathParameters", None)
        response = handler(event, None)

        assert response["statusCode"] == 400


class TestMalformedRequestBody:
    """Test that malformed request bodies return 400."""

    @patch("src.handlers.admin_feature_flags.ssm_client")
    def test_invalid_json_returns_400(self, mock_ssm):
        """PUT with invalid JSON body returns 400."""
        event = _make_admin_event(
            method="PUT",
            path_params={"flag-name": "video-processing-enabled"},
            body="not valid json{{{",
        )
        response = handler(event, None)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert "invalid JSON" in body["message"]

    @patch("src.handlers.admin_feature_flags.ssm_client")
    def test_missing_enabled_field_returns_400(self, mock_ssm):
        """PUT with body missing 'enabled' field returns 400."""
        event = _make_admin_event(
            method="PUT",
            path_params={"flag-name": "video-processing-enabled"},
            body=json.dumps({"value": True}),
        )
        response = handler(event, None)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert "enabled" in body["message"]

    @patch("src.handlers.admin_feature_flags.ssm_client")
    def test_non_boolean_enabled_returns_400(self, mock_ssm):
        """PUT with non-boolean 'enabled' value returns 400."""
        event = _make_admin_event(
            method="PUT",
            path_params={"flag-name": "video-processing-enabled"},
            body=json.dumps({"enabled": "yes"}),
        )
        response = handler(event, None)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert "boolean" in body["message"]

    @patch("src.handlers.admin_feature_flags.ssm_client")
    def test_empty_body_returns_400(self, mock_ssm):
        """PUT with empty body returns 400."""
        event = _make_admin_event(
            method="PUT",
            path_params={"flag-name": "video-processing-enabled"},
            body="",
        )
        response = handler(event, None)

        assert response["statusCode"] == 400
