"""Unit tests for admin environment variables handler.

Validates Requirements: 8.1, 8.2, 8.7, 8.8, 6.7
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from src.handlers.admin_env_vars import handler, KNOWN_VARIABLES


# --- Helpers ---


def _make_admin_event(method="GET", body=None):
    """Build an API Gateway v2 event with admin JWT claims."""
    event = {
        "requestContext": {
            "authorizer": {
                "jwt": {
                    "claims": {
                        "sub": "admin-user-001",
                        "cognito:groups": "administrators",
                    }
                }
            },
            "http": {
                "method": method,
            },
        },
    }
    if body is not None:
        event["body"] = json.dumps(body) if isinstance(body, dict) else body
    return event


def _make_non_admin_event(method="GET", body=None):
    """Build an API Gateway v2 event with non-admin JWT claims."""
    event = {
        "requestContext": {
            "authorizer": {
                "jwt": {
                    "claims": {
                        "sub": "regular-user-001",
                        "cognito:groups": "users",
                    }
                }
            },
            "http": {
                "method": method,
            },
        },
    }
    if body is not None:
        event["body"] = json.dumps(body) if isinstance(body, dict) else body
    return event


def _mock_get_parameter(name_to_value):
    """Create a mock ssm_client.get_parameter that returns values by param name."""
    def get_parameter(Name, **kwargs):
        # Extract the variable name from the full path
        var_name = Name.split("/")[-1]
        if var_name in name_to_value:
            return {"Parameter": {"Value": name_to_value[var_name]}}
        from botocore.exceptions import ClientError
        raise ClientError(
            {"Error": {"Code": "ParameterNotFound", "Message": "Not found"}},
            "GetParameter",
        )
    return get_parameter


# --- GET Tests ---


class TestGetEnvironmentVariables:
    """Tests for GET /admin/environment-variables (Requirement 8.1, 8.7)."""

    @patch("src.handlers.admin_env_vars.ssm_client")
    def test_get_returns_correct_structure_with_all_6_variables(self, mock_ssm):
        """GET returns 200 with all 6 known variables including name, value, description, inputType."""
        values = {
            "SESSION_SUPERVISOR_MODEL_ID": "us.anthropic.claude-sonnet-4-6",
            "COACHING_SUPERVISOR_MODEL_ID": "us.amazon.nova-pro-v1:0",
            "EVALUATION_MODEL_ID": "us.anthropic.claude-3-5-haiku-20241022-v1:0",
            "IDLE_TIMEOUT_MINUTES": "30",
            "MAX_CONCURRENT_EVALUATIONS": "5",
            "COGNITO_USER_POOL_NAME": "prescoach-prod-pool",
        }
        mock_ssm.get_parameter = MagicMock(side_effect=_mock_get_parameter(values))

        event = _make_admin_event(method="GET")
        response = handler(event, None)

        assert response["statusCode"] == 200
        assert "Content-Type" in response["headers"]
        assert response["headers"]["Content-Type"] == "application/json"

        body = json.loads(response["body"])
        assert "variables" in body
        variables = body["variables"]
        assert len(variables) == 6

        # Verify each variable has the correct structure
        var_names = [v["name"] for v in variables]
        for var_name in KNOWN_VARIABLES:
            assert var_name in var_names

        for var in variables:
            assert "name" in var
            assert "value" in var
            assert "description" in var
            assert "inputType" in var
            # Check value matches what SSM returned
            assert var["value"] == values[var["name"]]
            # Check description and inputType come from KNOWN_VARIABLES
            expected_desc, expected_type = KNOWN_VARIABLES[var["name"]]
            assert var["description"] == expected_desc
            assert var["inputType"] == expected_type

    @patch("src.handlers.admin_env_vars.ssm_client")
    def test_get_returns_empty_string_for_missing_parameters(self, mock_ssm):
        """GET returns empty string for parameters that don't exist in SSM yet."""
        from botocore.exceptions import ClientError

        def get_parameter(Name, **kwargs):
            raise ClientError(
                {"Error": {"Code": "ParameterNotFound", "Message": "Not found"}},
                "GetParameter",
            )

        mock_ssm.get_parameter = MagicMock(side_effect=get_parameter)

        event = _make_admin_event(method="GET")
        response = handler(event, None)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        for var in body["variables"]:
            assert var["value"] == ""

    @patch("src.handlers.admin_env_vars.ssm_client")
    def test_get_includes_cors_headers(self, mock_ssm):
        """GET response includes CORS headers."""
        mock_ssm.get_parameter = MagicMock(
            side_effect=_mock_get_parameter({
                "SESSION_SUPERVISOR_MODEL_ID": "model-1",
                "COACHING_SUPERVISOR_MODEL_ID": "model-2",
                "EVALUATION_MODEL_ID": "model-3",
                "IDLE_TIMEOUT_MINUTES": "30",
                "MAX_CONCURRENT_EVALUATIONS": "5",
                "COGNITO_USER_POOL_NAME": "pool",
            })
        )

        event = _make_admin_event(method="GET")
        response = handler(event, None)

        assert "Access-Control-Allow-Origin" in response["headers"]
        assert "Access-Control-Allow-Methods" in response["headers"]


# --- PUT Tests ---


class TestPutEnvironmentVariables:
    """Tests for PUT /admin/environment-variables (Requirements 8.2, 8.8, 6.7)."""

    @patch("src.handlers.admin_env_vars.ecs_service")
    @patch("src.handlers.admin_env_vars.ssm_client")
    def test_put_calls_ssm_put_parameter_for_each_changed_variable(
        self, mock_ssm, mock_ecs
    ):
        """PUT calls ssm put_parameter for each changed variable."""
        mock_ssm.put_parameter = MagicMock(return_value={})
        mock_ecs.update_task_environment = MagicMock(
            return_value="arn:aws:ecs:us-east-1:123:task-definition/prescoach:42"
        )
        mock_ecs.force_new_deployment = MagicMock(
            return_value={
                "deploymentStatus": "triggered",
                "message": "Configuration saved. ECS service redeployment triggered.",
            }
        )

        changed_vars = {
            "SESSION_SUPERVISOR_MODEL_ID": "us.amazon.nova-pro-v1:0",
            "IDLE_TIMEOUT_MINUTES": "45",
        }
        event = _make_admin_event(method="PUT", body={"variables": changed_vars})
        response = handler(event, None)

        assert response["statusCode"] == 200
        # Verify SSM put_parameter was called for each changed variable
        assert mock_ssm.put_parameter.call_count == 2

        call_args_list = mock_ssm.put_parameter.call_args_list
        ssm_names_called = [call.kwargs["Name"] for call in call_args_list]
        assert any("SESSION_SUPERVISOR_MODEL_ID" in name for name in ssm_names_called)
        assert any("IDLE_TIMEOUT_MINUTES" in name for name in ssm_names_called)

        # Verify values written are correct
        for call in call_args_list:
            if "SESSION_SUPERVISOR_MODEL_ID" in call.kwargs["Name"]:
                assert call.kwargs["Value"] == "us.amazon.nova-pro-v1:0"
            elif "IDLE_TIMEOUT_MINUTES" in call.kwargs["Name"]:
                assert call.kwargs["Value"] == "45"

    @patch("src.handlers.admin_env_vars.ecs_service")
    @patch("src.handlers.admin_env_vars.ssm_client")
    def test_put_calls_ecs_update_task_definition_with_correct_env_vars(
        self, mock_ssm, mock_ecs
    ):
        """PUT calls ECS update_task_environment with the changed variables."""
        mock_ssm.put_parameter = MagicMock(return_value={})
        mock_ecs.update_task_environment = MagicMock(
            return_value="arn:aws:ecs:us-east-1:123:task-definition/prescoach:43"
        )
        mock_ecs.force_new_deployment = MagicMock(
            return_value={
                "deploymentStatus": "triggered",
                "message": "Redeployment triggered.",
            }
        )

        changed_vars = {
            "EVALUATION_MODEL_ID": "us.anthropic.claude-3-5-haiku-20241022-v1:0",
            "MAX_CONCURRENT_EVALUATIONS": "10",
        }
        event = _make_admin_event(method="PUT", body={"variables": changed_vars})
        response = handler(event, None)

        assert response["statusCode"] == 200
        # Verify update_task_environment was called with correct env_updates
        mock_ecs.update_task_environment.assert_called_once()
        call_kwargs = mock_ecs.update_task_environment.call_args.kwargs
        assert call_kwargs["env_updates"] == {
            "EVALUATION_MODEL_ID": "us.anthropic.claude-3-5-haiku-20241022-v1:0",
            "MAX_CONCURRENT_EVALUATIONS": "10",
        }

    @patch("src.handlers.admin_env_vars.ecs_service")
    @patch("src.handlers.admin_env_vars.ssm_client")
    def test_put_skips_force_deploy_when_desired_count_zero(
        self, mock_ssm, mock_ecs
    ):
        """PUT skips force-deploy when ECS service desired_count=0 (Requirement 6.7)."""
        mock_ssm.put_parameter = MagicMock(return_value={})
        mock_ecs.update_task_environment = MagicMock(
            return_value="arn:aws:ecs:us-east-1:123:task-definition/prescoach:44"
        )
        mock_ecs.force_new_deployment = MagicMock(
            return_value={
                "deploymentStatus": "skipped_no_running_tasks",
                "message": (
                    "ECS service has no running tasks (desired_count=0). "
                    "Task definition updated; new tasks will use updated values "
                    "when the service is scaled up."
                ),
            }
        )

        changed_vars = {"IDLE_TIMEOUT_MINUTES": "60"}
        event = _make_admin_event(method="PUT", body={"variables": changed_vars})
        response = handler(event, None)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["deploymentStatus"] == "skipped_no_running_tasks"
        assert "desired_count=0" in body["message"] or "no running tasks" in body["message"]

    @patch("src.handlers.admin_env_vars.ecs_service")
    @patch("src.handlers.admin_env_vars.ssm_client")
    def test_put_response_contains_required_fields(self, mock_ssm, mock_ecs):
        """PUT response includes updatedVars, deploymentStatus, and message (Requirement 8.8)."""
        mock_ssm.put_parameter = MagicMock(return_value={})
        mock_ecs.update_task_environment = MagicMock(
            return_value="arn:aws:ecs:us-east-1:123:task-definition/prescoach:45"
        )
        mock_ecs.force_new_deployment = MagicMock(
            return_value={
                "deploymentStatus": "triggered",
                "message": "Configuration saved. ECS service redeployment triggered.",
            }
        )

        changed_vars = {
            "SESSION_SUPERVISOR_MODEL_ID": "us.amazon.nova-pro-v1:0",
            "IDLE_TIMEOUT_MINUTES": "45",
            "COGNITO_USER_POOL_NAME": "prescoach-new-pool",
        }
        event = _make_admin_event(method="PUT", body={"variables": changed_vars})
        response = handler(event, None)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])

        # All three required response fields must be present
        assert "updatedVars" in body
        assert "deploymentStatus" in body
        assert "message" in body

        # updatedVars should list exactly the variables that were updated
        assert isinstance(body["updatedVars"], list)
        assert set(body["updatedVars"]) == set(changed_vars.keys())

        # deploymentStatus should be a string
        assert isinstance(body["deploymentStatus"], str)

        # message should be a non-empty string
        assert isinstance(body["message"], str)
        assert len(body["message"]) > 0


# --- Authorization Tests ---


class TestAdminAuthorization:
    """Tests for non-admin request rejection (Requirement 8.5, 8.6)."""

    def test_non_admin_get_returns_403(self):
        """Non-admin GET request returns 403 Forbidden."""
        event = _make_non_admin_event(method="GET")
        response = handler(event, None)

        assert response["statusCode"] == 403
        body = json.loads(response["body"])
        assert "message" in body
        assert "Forbidden" in body["message"] or "forbidden" in body["message"].lower()

    def test_non_admin_put_returns_403(self):
        """Non-admin PUT request returns 403 Forbidden."""
        event = _make_non_admin_event(
            method="PUT",
            body={"variables": {"IDLE_TIMEOUT_MINUTES": "99"}},
        )
        response = handler(event, None)

        assert response["statusCode"] == 403
        body = json.loads(response["body"])
        assert "message" in body

    def test_missing_auth_context_returns_403(self):
        """Request with missing auth context returns 403."""
        event = {
            "requestContext": {
                "http": {"method": "GET"},
            },
        }
        response = handler(event, None)
        assert response["statusCode"] == 403


# --- Validation Tests ---


class TestRequestValidation:
    """Tests for request body validation (invalid variable name, malformed body)."""

    @patch("src.handlers.admin_env_vars.ssm_client")
    def test_invalid_variable_name_returns_400(self, mock_ssm):
        """PUT with unknown variable name returns 400 Bad Request."""
        event = _make_admin_event(
            method="PUT",
            body={"variables": {"NONEXISTENT_VARIABLE": "some-value"}},
        )
        response = handler(event, None)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert "message" in body
        assert "NONEXISTENT_VARIABLE" in body["message"]

    @patch("src.handlers.admin_env_vars.ssm_client")
    def test_multiple_invalid_variable_names_returns_400(self, mock_ssm):
        """PUT with multiple unknown variable names returns 400 listing all invalid names."""
        event = _make_admin_event(
            method="PUT",
            body={
                "variables": {
                    "FAKE_VAR_ONE": "val1",
                    "SESSION_SUPERVISOR_MODEL_ID": "us.amazon.nova-pro-v1:0",
                    "FAKE_VAR_TWO": "val2",
                }
            },
        )
        response = handler(event, None)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert "FAKE_VAR_ONE" in body["message"]
        assert "FAKE_VAR_TWO" in body["message"]

    def test_malformed_json_body_returns_400(self):
        """PUT with invalid JSON body returns 400."""
        event = _make_admin_event(method="PUT")
        event["body"] = "not valid json {{{{"
        response = handler(event, None)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert "message" in body
        assert "malformed" in body["message"].lower() or "invalid" in body["message"].lower()

    def test_missing_variables_key_returns_400(self):
        """PUT with body missing 'variables' key returns 400."""
        event = _make_admin_event(method="PUT", body={"data": {"key": "val"}})
        response = handler(event, None)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert "message" in body

    def test_empty_variables_map_returns_400(self):
        """PUT with empty variables map returns 400."""
        event = _make_admin_event(method="PUT", body={"variables": {}})
        response = handler(event, None)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert "message" in body

    def test_null_body_returns_400(self):
        """PUT with null/empty body returns 400."""
        event = _make_admin_event(method="PUT")
        event["body"] = None
        response = handler(event, None)

        assert response["statusCode"] == 400
