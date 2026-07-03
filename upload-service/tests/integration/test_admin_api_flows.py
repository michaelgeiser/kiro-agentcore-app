"""Integration tests for admin API flows.

Tests multi-component interactions: handler + auth + ECS service with mocked
boto3 clients (SSM, ECS). The verify_admin and EcsService are NOT mocked —
only the underlying AWS clients are mocked to validate real wiring.

Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 6.2, 6.3, 6.4
"""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest


# --- Environment setup ---
_ENV_VARS = {
    "SSM_PREFIX": "/prescoach/test/admin/env-vars/",
    "ECS_CLUSTER": "test-cluster",
    "ECS_SERVICE": "test-service",
    "TASK_FAMILY": "test-task-family",
    "AWS_DEFAULT_REGION": "us-east-1",
}

# Feature flags handler uses a different SSM prefix env var
_FF_ENV_VARS = {
    "SSM_PREFIX": "/prescoach/test/feature-flags/",
    "AWS_DEFAULT_REGION": "us-east-1",
}


# --- Event Builders ---


def _admin_event(method: str = "GET", body: dict | None = None, path_params: dict | None = None) -> dict:
    """Build an API Gateway v2 event with admin JWT claims."""
    event = {
        "requestContext": {
            "authorizer": {
                "jwt": {
                    "claims": {
                        "sub": "admin-integration-001",
                        "cognito:groups": "administrators",
                    }
                }
            },
            "http": {"method": method},
        },
    }
    if body is not None:
        event["body"] = json.dumps(body)
    if path_params is not None:
        event["pathParameters"] = path_params
    return event


def _non_admin_event(method: str = "GET", body: dict | None = None, path_params: dict | None = None) -> dict:
    """Build an API Gateway v2 event with non-admin JWT claims."""
    event = {
        "requestContext": {
            "authorizer": {
                "jwt": {
                    "claims": {
                        "sub": "regular-user-001",
                        "cognito:groups": "viewers",
                    }
                }
            },
            "http": {"method": method},
        },
    }
    if body is not None:
        event["body"] = json.dumps(body)
    if path_params is not None:
        event["pathParameters"] = path_params
    return event


# --- Helper: reload modules for fresh boto3 client instantiation ---


def _reload_env_vars_handler():
    """Force reimport of env vars handler and its dependencies.

    This ensures the EcsService and SSM client are freshly instantiated
    with whatever mock is in place at import time.
    """
    modules_to_clear = [
        "src.services.ecs_service",
        "src.utils.admin_auth",
        "src.handlers.admin_env_vars",
    ]
    for mod_name in modules_to_clear:
        if mod_name in sys.modules:
            del sys.modules[mod_name]

    from src.handlers.admin_env_vars import handler
    return handler


def _reload_feature_flags_handler():
    """Force reimport of feature flags handler and its dependencies."""
    modules_to_clear = [
        "src.utils.admin_auth",
        "src.handlers.admin_feature_flags",
    ]
    for mod_name in modules_to_clear:
        if mod_name in sys.modules:
            del sys.modules[mod_name]

    from src.handlers.admin_feature_flags import handler
    return handler


# --- Mock Factory Helpers ---


def _make_ssm_mock(stored_params: dict[str, str] | None = None):
    """Create a mock SSM client that stores parameters in a dict.

    Args:
        stored_params: Initial parameter store contents {full_path: value}.

    Returns:
        A MagicMock SSM client with working get_parameter and put_parameter.
    """
    from botocore.exceptions import ClientError

    store = dict(stored_params or {})
    mock_ssm = MagicMock()

    def get_parameter(Name, **kwargs):
        if Name in store:
            return {"Parameter": {"Value": store[Name]}}
        raise ClientError(
            {"Error": {"Code": "ParameterNotFound", "Message": f"Parameter {Name} not found"}},
            "GetParameter",
        )

    def put_parameter(Name, Value, **kwargs):
        store[Name] = Value
        return {"Version": 1}

    mock_ssm.get_parameter = MagicMock(side_effect=get_parameter)
    mock_ssm.put_parameter = MagicMock(side_effect=put_parameter)
    # Expose store for test assertions
    mock_ssm._store = store
    return mock_ssm


def _make_ecs_mock(desired_count: int = 1):
    """Create a mock ECS client with working describe/register/update methods.

    Args:
        desired_count: The desired task count for describe_services.

    Returns:
        A MagicMock ECS client with realistic responses.
    """
    mock_ecs = MagicMock()

    # describe_task_definition returns a realistic task def
    mock_ecs.describe_task_definition = MagicMock(return_value={
        "taskDefinition": {
            "family": "test-task-family",
            "containerDefinitions": [
                {
                    "name": "evaluation-container",
                    "image": "123456789012.dkr.ecr.us-east-1.amazonaws.com/eval:latest",
                    "environment": [
                        {"name": "SESSION_SUPERVISOR_MODEL_ID", "value": "us.anthropic.claude-sonnet-4-6"},
                        {"name": "IDLE_TIMEOUT_MINUTES", "value": "30"},
                    ],
                    "essential": True,
                }
            ],
            "cpu": "1024",
            "memory": "2048",
            "networkMode": "awsvpc",
            "requiresCompatibilities": ["FARGATE"],
        }
    })

    # register_task_definition returns new revision ARN
    mock_ecs.register_task_definition = MagicMock(return_value={
        "taskDefinition": {
            "taskDefinitionArn": "arn:aws:ecs:us-east-1:123456789012:task-definition/test-task-family:42",
            "family": "test-task-family",
            "revision": 42,
        }
    })

    # describe_services returns service with configurable desired count
    mock_ecs.describe_services = MagicMock(return_value={
        "services": [
            {
                "serviceName": "test-service",
                "desiredCount": desired_count,
                "status": "ACTIVE",
            }
        ]
    })

    # update_service returns success
    mock_ecs.update_service = MagicMock(return_value={
        "service": {
            "serviceName": "test-service",
            "desiredCount": desired_count,
            "deployments": [{"status": "PRIMARY"}],
        }
    })

    return mock_ecs


# ===========================================================================
# Test Class 1: Full environment variables flow
# GET env vars → modify → PUT → verify SSM updated and ECS triggered
# Requirements: 8.1, 8.2, 6.2, 6.3, 6.4
# ===========================================================================


class TestEnvVarsFullFlow:
    """Integration: GET env vars → PUT changed values → verify SSM and ECS updates."""

    @patch("boto3.client")
    def test_get_then_put_updates_ssm_and_triggers_ecs(self, mock_boto3_client):
        """Full flow: GET returns current values, PUT updates SSM and triggers ECS deployment."""
        ssm_prefix = "/prescoach/test/admin/env-vars/"
        initial_params = {
            f"{ssm_prefix}SESSION_SUPERVISOR_MODEL_ID": "us.anthropic.claude-sonnet-4-6",
            f"{ssm_prefix}COACHING_SUPERVISOR_MODEL_ID": "us.amazon.nova-pro-v1:0",
            f"{ssm_prefix}EVALUATION_MODEL_ID": "us.anthropic.claude-3-5-haiku-20241022-v1:0",
            f"{ssm_prefix}IDLE_TIMEOUT_MINUTES": "30",
            f"{ssm_prefix}MAX_CONCURRENT_EVALUATIONS": "5",
            f"{ssm_prefix}COGNITO_USER_POOL_NAME": "prescoach-prod-pool",
        }

        mock_ssm = _make_ssm_mock(initial_params)
        mock_ecs = _make_ecs_mock(desired_count=2)

        def client_factory(service_name, **kwargs):
            if service_name == "ssm":
                return mock_ssm
            elif service_name == "ecs":
                return mock_ecs
            return MagicMock()

        mock_boto3_client.side_effect = client_factory

        with patch.dict(os.environ, _ENV_VARS):
            handler = _reload_env_vars_handler()

            # Step 1: GET current env vars
            get_event = _admin_event(method="GET")
            get_response = handler(get_event, None)

            assert get_response["statusCode"] == 200
            get_body = json.loads(get_response["body"])
            variables = get_body["variables"]
            assert len(variables) == 6

            # Verify current values match initial SSM state
            var_map = {v["name"]: v["value"] for v in variables}
            assert var_map["SESSION_SUPERVISOR_MODEL_ID"] == "us.anthropic.claude-sonnet-4-6"
            assert var_map["IDLE_TIMEOUT_MINUTES"] == "30"

            # Step 2: PUT with modified values
            changed_vars = {
                "SESSION_SUPERVISOR_MODEL_ID": "us.amazon.nova-pro-v1:0",
                "IDLE_TIMEOUT_MINUTES": "45",
            }
            put_event = _admin_event(method="PUT", body={"variables": changed_vars})
            put_response = handler(put_event, None)

            assert put_response["statusCode"] == 200
            put_body = json.loads(put_response["body"])
            assert set(put_body["updatedVars"]) == {"SESSION_SUPERVISOR_MODEL_ID", "IDLE_TIMEOUT_MINUTES"}
            assert put_body["deploymentStatus"] == "triggered"
            assert len(put_body["message"]) > 0

            # Step 3: Verify SSM was updated with new values
            put_calls = mock_ssm.put_parameter.call_args_list
            ssm_writes = {call.kwargs["Name"]: call.kwargs["Value"] for call in put_calls}
            assert ssm_writes[f"{ssm_prefix}SESSION_SUPERVISOR_MODEL_ID"] == "us.amazon.nova-pro-v1:0"
            assert ssm_writes[f"{ssm_prefix}IDLE_TIMEOUT_MINUTES"] == "45"

            # Step 4: Verify ECS task definition was updated
            mock_ecs.describe_task_definition.assert_called_once()
            mock_ecs.register_task_definition.assert_called_once()

            # Verify the registered task def includes updated env vars
            reg_call = mock_ecs.register_task_definition.call_args
            containers = reg_call.kwargs["containerDefinitions"]
            env_vars = {e["name"]: e["value"] for e in containers[0]["environment"]}
            assert env_vars["SESSION_SUPERVISOR_MODEL_ID"] == "us.amazon.nova-pro-v1:0"
            assert env_vars["IDLE_TIMEOUT_MINUTES"] == "45"

            # Step 5: Verify force-new-deployment was triggered
            mock_ecs.describe_services.assert_called_once()
            mock_ecs.update_service.assert_called_once()
            update_call = mock_ecs.update_service.call_args
            assert update_call.kwargs["forceNewDeployment"] is True
            assert "test-cluster" in str(update_call.kwargs["cluster"])


# ===========================================================================
# Test Class 2: Full feature flags flow
# GET flags → toggle one → verify SSM updated
# Requirements: 8.3, 8.4
# ===========================================================================


class TestFeatureFlagsFullFlow:
    """Integration: GET feature flags → PUT to toggle one → verify SSM updated."""

    @patch("boto3.client")
    def test_get_then_toggle_flag_updates_ssm(self, mock_boto3_client):
        """Full flow: GET returns flags, PUT toggles one, verify SSM written correctly."""
        ssm_prefix = "/prescoach/test/feature-flags/"
        initial_params = {
            f"{ssm_prefix}video-processing-enabled": "true",
            f"{ssm_prefix}batch-processing-enabled": "false",
            f"{ssm_prefix}embeddings-enabled": "true",
            f"{ssm_prefix}local-mode": "false",
        }

        mock_ssm = _make_ssm_mock(initial_params)

        def client_factory(service_name, **kwargs):
            if service_name == "ssm":
                return mock_ssm
            return MagicMock()

        mock_boto3_client.side_effect = client_factory

        with patch.dict(os.environ, _FF_ENV_VARS):
            handler = _reload_feature_flags_handler()

            # Step 1: GET all feature flags
            get_event = _admin_event(method="GET")
            get_response = handler(get_event, None)

            assert get_response["statusCode"] == 200
            get_body = json.loads(get_response["body"])
            flags = get_body["flags"]
            assert len(flags) == 4

            # Verify initial state
            flag_map = {f["name"]: f["enabled"] for f in flags}
            assert flag_map["video-processing-enabled"] is True
            assert flag_map["batch-processing-enabled"] is False
            assert flag_map["embeddings-enabled"] is True
            assert flag_map["local-mode"] is False

            # Step 2: Toggle batch-processing-enabled from false to true
            put_event = _admin_event(
                method="PUT",
                body={"enabled": True},
                path_params={"flag-name": "batch-processing-enabled"},
            )
            put_response = handler(put_event, None)

            assert put_response["statusCode"] == 200
            put_body = json.loads(put_response["body"])
            assert put_body["name"] == "batch-processing-enabled"
            assert put_body["enabled"] is True

            # Step 3: Verify SSM put_parameter was called with "true"
            put_calls = mock_ssm.put_parameter.call_args_list
            assert len(put_calls) == 1
            assert put_calls[0].kwargs["Name"] == f"{ssm_prefix}batch-processing-enabled"
            assert put_calls[0].kwargs["Value"] == "true"

    @patch("boto3.client")
    def test_toggle_flag_from_true_to_false(self, mock_boto3_client):
        """Toggle a flag from true to false writes 'false' to SSM."""
        ssm_prefix = "/prescoach/test/feature-flags/"
        initial_params = {
            f"{ssm_prefix}video-processing-enabled": "true",
            f"{ssm_prefix}batch-processing-enabled": "false",
            f"{ssm_prefix}embeddings-enabled": "true",
            f"{ssm_prefix}local-mode": "false",
        }

        mock_ssm = _make_ssm_mock(initial_params)

        def client_factory(service_name, **kwargs):
            if service_name == "ssm":
                return mock_ssm
            return MagicMock()

        mock_boto3_client.side_effect = client_factory

        with patch.dict(os.environ, _FF_ENV_VARS):
            handler = _reload_feature_flags_handler()

            # Toggle embeddings-enabled from true to false
            put_event = _admin_event(
                method="PUT",
                body={"enabled": False},
                path_params={"flag-name": "embeddings-enabled"},
            )
            put_response = handler(put_event, None)

            assert put_response["statusCode"] == 200
            put_body = json.loads(put_response["body"])
            assert put_body["name"] == "embeddings-enabled"
            assert put_body["enabled"] is False

            # Verify SSM was called with "false"
            put_calls = mock_ssm.put_parameter.call_args_list
            assert len(put_calls) == 1
            assert put_calls[0].kwargs["Value"] == "false"


# ===========================================================================
# Test Class 3: ECS deployment flow
# PUT env vars → verify task definition registered → verify update_service called
# Requirements: 6.2, 6.3, 6.4
# ===========================================================================


class TestEcsDeploymentFlow:
    """Integration: PUT env vars triggers correct ECS API call sequence."""

    @patch("boto3.client")
    def test_ecs_calls_happen_in_correct_order(self, mock_boto3_client):
        """PUT env vars calls describe → register → describe_services → update_service in order."""
        ssm_prefix = "/prescoach/test/admin/env-vars/"
        initial_params = {
            f"{ssm_prefix}SESSION_SUPERVISOR_MODEL_ID": "us.anthropic.claude-sonnet-4-6",
            f"{ssm_prefix}COACHING_SUPERVISOR_MODEL_ID": "us.amazon.nova-pro-v1:0",
            f"{ssm_prefix}EVALUATION_MODEL_ID": "us.anthropic.claude-3-5-haiku-20241022-v1:0",
            f"{ssm_prefix}IDLE_TIMEOUT_MINUTES": "30",
            f"{ssm_prefix}MAX_CONCURRENT_EVALUATIONS": "5",
            f"{ssm_prefix}COGNITO_USER_POOL_NAME": "prescoach-prod-pool",
        }

        mock_ssm = _make_ssm_mock(initial_params)
        mock_ecs = _make_ecs_mock(desired_count=3)

        # Track call order
        call_order = []
        original_describe_td = mock_ecs.describe_task_definition.side_effect
        original_register_td = mock_ecs.register_task_definition.side_effect
        original_describe_svc = mock_ecs.describe_services.side_effect
        original_update_svc = mock_ecs.update_service.side_effect

        def track_describe_td(**kwargs):
            call_order.append("describe_task_definition")
            return mock_ecs.describe_task_definition.return_value

        def track_register_td(**kwargs):
            call_order.append("register_task_definition")
            return mock_ecs.register_task_definition.return_value

        def track_describe_svc(**kwargs):
            call_order.append("describe_services")
            return mock_ecs.describe_services.return_value

        def track_update_svc(**kwargs):
            call_order.append("update_service")
            return mock_ecs.update_service.return_value

        mock_ecs.describe_task_definition.side_effect = track_describe_td
        mock_ecs.register_task_definition.side_effect = track_register_td
        mock_ecs.describe_services.side_effect = track_describe_svc
        mock_ecs.update_service.side_effect = track_update_svc

        def client_factory(service_name, **kwargs):
            if service_name == "ssm":
                return mock_ssm
            elif service_name == "ecs":
                return mock_ecs
            return MagicMock()

        mock_boto3_client.side_effect = client_factory

        with patch.dict(os.environ, _ENV_VARS):
            handler = _reload_env_vars_handler()

            put_event = _admin_event(
                method="PUT",
                body={"variables": {"IDLE_TIMEOUT_MINUTES": "60"}},
            )
            response = handler(put_event, None)

            assert response["statusCode"] == 200

            # Verify correct call order
            assert call_order == [
                "describe_task_definition",
                "register_task_definition",
                "describe_services",
                "update_service",
            ]

    @patch("boto3.client")
    def test_ecs_skips_update_service_when_desired_count_zero(self, mock_boto3_client):
        """When desired_count=0, update_service is NOT called (Requirement 6.4)."""
        ssm_prefix = "/prescoach/test/admin/env-vars/"
        initial_params = {
            f"{ssm_prefix}SESSION_SUPERVISOR_MODEL_ID": "us.anthropic.claude-sonnet-4-6",
            f"{ssm_prefix}COACHING_SUPERVISOR_MODEL_ID": "us.amazon.nova-pro-v1:0",
            f"{ssm_prefix}EVALUATION_MODEL_ID": "model",
            f"{ssm_prefix}IDLE_TIMEOUT_MINUTES": "30",
            f"{ssm_prefix}MAX_CONCURRENT_EVALUATIONS": "5",
            f"{ssm_prefix}COGNITO_USER_POOL_NAME": "pool",
        }

        mock_ssm = _make_ssm_mock(initial_params)
        mock_ecs = _make_ecs_mock(desired_count=0)

        def client_factory(service_name, **kwargs):
            if service_name == "ssm":
                return mock_ssm
            elif service_name == "ecs":
                return mock_ecs
            return MagicMock()

        mock_boto3_client.side_effect = client_factory

        with patch.dict(os.environ, _ENV_VARS):
            handler = _reload_env_vars_handler()

            put_event = _admin_event(
                method="PUT",
                body={"variables": {"MAX_CONCURRENT_EVALUATIONS": "10"}},
            )
            response = handler(put_event, None)

            assert response["statusCode"] == 200
            body = json.loads(response["body"])
            assert body["deploymentStatus"] == "skipped_no_running_tasks"

            # SSM was updated
            mock_ssm.put_parameter.assert_called_once()

            # Task definition was registered
            mock_ecs.register_task_definition.assert_called_once()

            # describe_services was called to check desired count
            mock_ecs.describe_services.assert_called_once()

            # update_service was NOT called
            mock_ecs.update_service.assert_not_called()

    @patch("boto3.client")
    def test_registered_task_def_has_updated_env_vars(self, mock_boto3_client):
        """The newly registered task definition includes the updated env vars."""
        ssm_prefix = "/prescoach/test/admin/env-vars/"
        initial_params = {
            f"{ssm_prefix}SESSION_SUPERVISOR_MODEL_ID": "old-model",
            f"{ssm_prefix}COACHING_SUPERVISOR_MODEL_ID": "old-model-2",
            f"{ssm_prefix}EVALUATION_MODEL_ID": "old-model-3",
            f"{ssm_prefix}IDLE_TIMEOUT_MINUTES": "30",
            f"{ssm_prefix}MAX_CONCURRENT_EVALUATIONS": "5",
            f"{ssm_prefix}COGNITO_USER_POOL_NAME": "pool",
        }

        mock_ssm = _make_ssm_mock(initial_params)
        mock_ecs = _make_ecs_mock(desired_count=1)

        def client_factory(service_name, **kwargs):
            if service_name == "ssm":
                return mock_ssm
            elif service_name == "ecs":
                return mock_ecs
            return MagicMock()

        mock_boto3_client.side_effect = client_factory

        with patch.dict(os.environ, _ENV_VARS):
            handler = _reload_env_vars_handler()

            put_event = _admin_event(
                method="PUT",
                body={"variables": {
                    "SESSION_SUPERVISOR_MODEL_ID": "us.amazon.nova-pro-v1:0",
                    "IDLE_TIMEOUT_MINUTES": "120",
                }},
            )
            response = handler(put_event, None)

            assert response["statusCode"] == 200

            # Check the task definition registration payload
            reg_call = mock_ecs.register_task_definition.call_args
            containers = reg_call.kwargs["containerDefinitions"]
            env_list = containers[0]["environment"]
            env_map = {e["name"]: e["value"] for e in env_list}

            # Updated vars have new values
            assert env_map["SESSION_SUPERVISOR_MODEL_ID"] == "us.amazon.nova-pro-v1:0"
            assert env_map["IDLE_TIMEOUT_MINUTES"] == "120"


# ===========================================================================
# Test Class 4: End-to-end admin auth enforcement
# Non-admin token → verify 403 from each endpoint
# Requirements: 8.5, 9.1, 9.2, 9.3
# ===========================================================================


class TestAdminAuthEnforcement:
    """Integration: non-admin JWT claims get 403 from all admin endpoints.

    These tests exercise the real verify_admin function — no mocking of auth.
    Only boto3 is mocked to prevent real AWS calls.
    """

    @patch("boto3.client")
    def test_non_admin_get_env_vars_returns_403(self, mock_boto3_client):
        """Non-admin GET /admin/environment-variables returns 403."""
        mock_boto3_client.return_value = MagicMock()

        with patch.dict(os.environ, _ENV_VARS):
            handler = _reload_env_vars_handler()

            event = _non_admin_event(method="GET")
            response = handler(event, None)

            assert response["statusCode"] == 403
            body = json.loads(response["body"])
            assert "forbidden" in body["message"].lower() or "Forbidden" in body["message"]

    @patch("boto3.client")
    def test_non_admin_put_env_vars_returns_403(self, mock_boto3_client):
        """Non-admin PUT /admin/environment-variables returns 403."""
        mock_boto3_client.return_value = MagicMock()

        with patch.dict(os.environ, _ENV_VARS):
            handler = _reload_env_vars_handler()

            event = _non_admin_event(
                method="PUT",
                body={"variables": {"IDLE_TIMEOUT_MINUTES": "999"}},
            )
            response = handler(event, None)

            assert response["statusCode"] == 403
            body = json.loads(response["body"])
            assert "forbidden" in body["message"].lower() or "Forbidden" in body["message"]

    @patch("boto3.client")
    def test_non_admin_get_feature_flags_returns_403(self, mock_boto3_client):
        """Non-admin GET /admin/feature-flags returns 403."""
        mock_boto3_client.return_value = MagicMock()

        with patch.dict(os.environ, _FF_ENV_VARS):
            handler = _reload_feature_flags_handler()

            event = _non_admin_event(method="GET")
            response = handler(event, None)

            assert response["statusCode"] == 403
            body = json.loads(response["body"])
            assert "forbidden" in body["message"].lower() or "Forbidden" in body["message"]

    @patch("boto3.client")
    def test_non_admin_put_feature_flag_returns_403(self, mock_boto3_client):
        """Non-admin PUT /admin/feature-flags/{flag-name} returns 403."""
        mock_boto3_client.return_value = MagicMock()

        with patch.dict(os.environ, _FF_ENV_VARS):
            handler = _reload_feature_flags_handler()

            event = _non_admin_event(
                method="PUT",
                body={"enabled": True},
                path_params={"flag-name": "local-mode"},
            )
            response = handler(event, None)

            assert response["statusCode"] == 403
            body = json.loads(response["body"])
            assert "forbidden" in body["message"].lower() or "Forbidden" in body["message"]

    @patch("boto3.client")
    def test_missing_auth_context_returns_403_env_vars(self, mock_boto3_client):
        """Request with no authorizer context returns 403 from env vars handler."""
        mock_boto3_client.return_value = MagicMock()

        with patch.dict(os.environ, _ENV_VARS):
            handler = _reload_env_vars_handler()

            event = {
                "requestContext": {
                    "http": {"method": "GET"},
                },
            }
            response = handler(event, None)
            assert response["statusCode"] == 403

    @patch("boto3.client")
    def test_missing_auth_context_returns_403_feature_flags(self, mock_boto3_client):
        """Request with no authorizer context returns 403 from feature flags handler."""
        mock_boto3_client.return_value = MagicMock()

        with patch.dict(os.environ, _FF_ENV_VARS):
            handler = _reload_feature_flags_handler()

            event = {
                "requestContext": {
                    "http": {"method": "GET"},
                },
            }
            response = handler(event, None)
            assert response["statusCode"] == 403

    @patch("boto3.client")
    def test_non_admin_does_not_trigger_any_ssm_or_ecs_calls(self, mock_boto3_client):
        """Non-admin request short-circuits before any SSM or ECS interaction."""
        mock_ssm = MagicMock()
        mock_ecs = MagicMock()

        def client_factory(service_name, **kwargs):
            if service_name == "ssm":
                return mock_ssm
            elif service_name == "ecs":
                return mock_ecs
            return MagicMock()

        mock_boto3_client.side_effect = client_factory

        with patch.dict(os.environ, _ENV_VARS):
            handler = _reload_env_vars_handler()

            event = _non_admin_event(
                method="PUT",
                body={"variables": {"IDLE_TIMEOUT_MINUTES": "999"}},
            )
            response = handler(event, None)

            assert response["statusCode"] == 403
            # No SSM or ECS calls should have been made
            mock_ssm.get_parameter.assert_not_called()
            mock_ssm.put_parameter.assert_not_called()
            mock_ecs.describe_task_definition.assert_not_called()
            mock_ecs.register_task_definition.assert_not_called()
            mock_ecs.update_service.assert_not_called()
