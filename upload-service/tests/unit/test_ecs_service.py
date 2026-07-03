"""Unit tests for ECS deployment service.

Tests task definition updates, force-new-deployment logic, retry behavior
on transient errors, and immediate failure on unrecoverable errors.

Requirements: 6.3, 6.4, 6.7
"""

from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from src.services.ecs_service import EcsService


def _make_client_error(code: str, message: str = "Error") -> ClientError:
    """Build a botocore ClientError with the given error code."""
    return ClientError(
        {"Error": {"Code": code, "Message": message}},
        "EcsOperation",
    )


@pytest.fixture
def mock_ecs_client():
    """Patch boto3.client to return a mocked ECS client."""
    with patch("src.services.ecs_service.boto3.client") as mock_boto_client:
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client
        yield mock_client


@pytest.fixture
def ecs_service(mock_ecs_client):
    """Create an EcsService instance with the mocked boto3 client."""
    return EcsService()


class TestUpdateTaskEnvironment:
    """Tests for EcsService.update_task_environment."""

    def test_registers_new_task_definition_with_updated_env_vars(
        self, ecs_service, mock_ecs_client
    ):
        """update_task_environment registers a new task definition with updated env vars."""
        # Arrange: describe_task_definition returns a task def with one container
        mock_ecs_client.describe_task_definition.return_value = {
            "taskDefinition": {
                "family": "my-task",
                "containerDefinitions": [
                    {
                        "name": "app",
                        "image": "my-image:latest",
                        "environment": [
                            {"name": "MODEL_ID", "value": "old-model"},
                            {"name": "TIMEOUT", "value": "30"},
                        ],
                    }
                ],
                "taskDefinitionArn": "arn:aws:ecs:us-east-1:123:task-definition/my-task:1",
                "revision": 1,
                "status": "ACTIVE",
                "requiresAttributes": [],
                "compatibilities": ["FARGATE"],
                "registeredAt": "2024-01-01T00:00:00Z",
                "registeredBy": "arn:aws:iam::123:root",
            }
        }
        mock_ecs_client.register_task_definition.return_value = {
            "taskDefinition": {
                "taskDefinitionArn": "arn:aws:ecs:us-east-1:123:task-definition/my-task:2",
            }
        }

        # Act
        result = ecs_service.update_task_environment(
            task_family="my-task",
            env_updates={"MODEL_ID": "new-model", "NEW_VAR": "new-value"},
        )

        # Assert: new task definition ARN returned
        assert result == "arn:aws:ecs:us-east-1:123:task-definition/my-task:2"

        # Assert: register_task_definition was called with correct env vars
        mock_ecs_client.register_task_definition.assert_called_once()
        call_kwargs = mock_ecs_client.register_task_definition.call_args[1]

        # Should not include read-only fields
        assert "taskDefinitionArn" not in call_kwargs
        assert "revision" not in call_kwargs
        assert "status" not in call_kwargs
        assert "requiresAttributes" not in call_kwargs
        assert "compatibilities" not in call_kwargs
        assert "registeredAt" not in call_kwargs
        assert "registeredBy" not in call_kwargs

        # Should include updated environment variables
        container_env = call_kwargs["containerDefinitions"][0]["environment"]
        env_map = {item["name"]: item["value"] for item in container_env}
        assert env_map["MODEL_ID"] == "new-model"
        assert env_map["TIMEOUT"] == "30"
        assert env_map["NEW_VAR"] == "new-value"


class TestForceNewDeployment:
    """Tests for EcsService.force_new_deployment."""

    def test_calls_update_service_with_force_new_deployment(
        self, ecs_service, mock_ecs_client
    ):
        """force_new_deployment calls UpdateService with forceNewDeployment=True."""
        mock_ecs_client.describe_services.return_value = {
            "services": [{"desiredCount": 2}]
        }
        mock_ecs_client.update_service.return_value = {}

        result = ecs_service.force_new_deployment(
            cluster="my-cluster",
            service="my-service",
            task_definition_arn="arn:aws:ecs:us-east-1:123:task-definition/my-task:2",
        )

        # Assert: update_service called with correct parameters
        mock_ecs_client.update_service.assert_called_once_with(
            cluster="my-cluster",
            service="my-service",
            taskDefinition="arn:aws:ecs:us-east-1:123:task-definition/my-task:2",
            forceNewDeployment=True,
        )
        assert result["deploymentStatus"] == "triggered"

    def test_skips_deployment_when_desired_count_is_zero(
        self, ecs_service, mock_ecs_client
    ):
        """force_new_deployment skips when desired_count=0."""
        mock_ecs_client.describe_services.return_value = {
            "services": [{"desiredCount": 0}]
        }

        result = ecs_service.force_new_deployment(
            cluster="my-cluster",
            service="my-service",
            task_definition_arn="arn:aws:ecs:us-east-1:123:task-definition/my-task:2",
        )

        # Assert: update_service NOT called
        mock_ecs_client.update_service.assert_not_called()
        assert result["deploymentStatus"] == "skipped_no_running_tasks"


class TestRetryBehavior:
    """Tests for retry with exponential backoff on recoverable errors."""

    @patch("src.services.ecs_service.time.sleep")
    def test_retries_on_throttling_exception(
        self, mock_sleep, ecs_service, mock_ecs_client
    ):
        """Recoverable ThrottlingException triggers retries, then succeeds."""
        # First two calls raise ThrottlingException, third call succeeds
        mock_ecs_client.describe_services.side_effect = [
            _make_client_error("ThrottlingException", "Rate exceeded"),
            _make_client_error("ThrottlingException", "Rate exceeded"),
            {"services": [{"desiredCount": 1}]},
        ]
        mock_ecs_client.update_service.return_value = {}

        result = ecs_service.force_new_deployment(
            cluster="my-cluster",
            service="my-service",
            task_definition_arn="arn:aws:ecs:us-east-1:123:task-definition/my-task:2",
        )

        # Assert: succeeded after retries
        assert result["deploymentStatus"] == "triggered"
        # Assert: sleep was called for backoff (2 retries before success)
        assert mock_sleep.call_count == 2

    @patch("src.services.ecs_service.time.sleep")
    def test_raises_after_max_retries_exhausted(
        self, mock_sleep, ecs_service, mock_ecs_client
    ):
        """When all retries are exhausted, the ThrottlingException propagates."""
        # All calls raise ThrottlingException (initial + 3 retries = 4 calls)
        mock_ecs_client.describe_services.side_effect = _make_client_error(
            "ThrottlingException", "Rate exceeded"
        )

        with pytest.raises(ClientError) as exc_info:
            ecs_service.force_new_deployment(
                cluster="my-cluster",
                service="my-service",
                task_definition_arn="arn:aws:ecs:us-east-1:123:task-definition/my-task:2",
            )

        assert exc_info.value.response["Error"]["Code"] == "ThrottlingException"
        # Assert: sleep called MAX_RETRIES times (3)
        assert mock_sleep.call_count == 3


class TestImmediateFailure:
    """Tests for immediate failure on unrecoverable errors."""

    @patch("src.services.ecs_service.time.sleep")
    def test_access_denied_fails_immediately_without_retry(
        self, mock_sleep, ecs_service, mock_ecs_client
    ):
        """AccessDeniedException propagates immediately without retries."""
        mock_ecs_client.describe_services.side_effect = _make_client_error(
            "AccessDeniedException", "User not authorized"
        )

        with pytest.raises(ClientError) as exc_info:
            ecs_service.force_new_deployment(
                cluster="my-cluster",
                service="my-service",
                task_definition_arn="arn:aws:ecs:us-east-1:123:task-definition/my-task:2",
            )

        assert exc_info.value.response["Error"]["Code"] == "AccessDeniedException"
        # Assert: no retries — sleep never called
        mock_sleep.assert_not_called()
