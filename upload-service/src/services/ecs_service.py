"""ECS deployment service for task definition updates and service redeployment."""

import copy
import logging
import random
import time

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# Recoverable error codes — retry with exponential backoff + jitter
RECOVERABLE_ERROR_CODES = frozenset([
    "ThrottlingException",
    "ServiceUnavailableException",
])

# Unrecoverable error codes — fail immediately, never retry
UNRECOVERABLE_ERROR_CODES = frozenset([
    "AccessDeniedException",
    "ResourceNotFoundException",
])

# Retry configuration
MAX_RETRIES = 3
BASE_DELAY_SECONDS = 1.0
MAX_JITTER_SECONDS = 1.0


def _is_recoverable(error_code: str) -> bool:
    """Determine if an ECS API error is recoverable (transient)."""
    return error_code in RECOVERABLE_ERROR_CODES


def _retry_with_backoff(func, *args, **kwargs):
    """Execute a function with exponential backoff + jitter for recoverable errors.

    Retries up to MAX_RETRIES times for recoverable errors.
    Fails immediately for unrecoverable errors.

    Args:
        func: The callable to execute.
        *args: Positional arguments for the callable.
        **kwargs: Keyword arguments for the callable.

    Returns:
        The return value of the callable on success.

    Raises:
        ClientError: If all retries are exhausted or an unrecoverable error occurs.
    """
    last_exception = None

    for attempt in range(MAX_RETRIES + 1):
        try:
            return func(*args, **kwargs)
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            last_exception = e

            if not _is_recoverable(error_code):
                # Unrecoverable — fail immediately, don't retry
                logger.error(
                    "Unrecoverable ECS API error: %s — %s",
                    error_code,
                    e.response["Error"].get("Message", ""),
                )
                raise

            if attempt < MAX_RETRIES:
                delay = BASE_DELAY_SECONDS * (2 ** attempt)
                jitter = random.uniform(0, MAX_JITTER_SECONDS)
                total_delay = delay + jitter
                logger.warning(
                    "Recoverable ECS API error: %s (attempt %d/%d). "
                    "Retrying in %.2fs...",
                    error_code,
                    attempt + 1,
                    MAX_RETRIES + 1,
                    total_delay,
                )
                time.sleep(total_delay)
            else:
                logger.error(
                    "Max retries exhausted for ECS API call. "
                    "Last error: %s — %s",
                    error_code,
                    e.response["Error"].get("Message", ""),
                )
                raise

    # Should not reach here, but raise last exception for safety
    raise last_exception  # type: ignore[misc]


# Fields from describe_task_definition that must NOT be passed to
# register_task_definition (read-only or server-managed fields).
_TASK_DEF_EXCLUDE_FIELDS = frozenset([
    "taskDefinitionArn",
    "revision",
    "status",
    "requiresAttributes",
    "compatibilities",
    "registeredAt",
    "registeredBy",
    "deregisteredAt",
])


class EcsService:
    """Manages ECS task definition updates and service redeployment."""

    def __init__(self) -> None:
        self._client = boto3.client("ecs")

    def update_task_environment(
        self, task_family: str, env_updates: dict[str, str]
    ) -> str:
        """Register a new task definition revision with updated environment variables.

        Describes the current task definition, copies all fields, updates the
        environment variables in each container definition, and registers a new
        revision.

        Args:
            task_family: The ECS task definition family name.
            env_updates: Map of environment variable names to their new values.

        Returns:
            The ARN of the newly registered task definition revision.

        Raises:
            ClientError: On unrecoverable ECS API errors or after retry exhaustion.
        """
        # Describe the current task definition
        response = _retry_with_backoff(
            self._client.describe_task_definition,
            taskDefinition=task_family,
        )
        task_def = response["taskDefinition"]

        # Build the registration payload by copying fields (excluding read-only ones)
        register_kwargs = {
            k: copy.deepcopy(v)
            for k, v in task_def.items()
            if k not in _TASK_DEF_EXCLUDE_FIELDS
        }

        # Update environment variables in each container definition
        for container in register_kwargs.get("containerDefinitions", []):
            existing_env = container.get("environment", [])

            # Build a map of current env vars for easy lookup
            env_map = {item["name"]: item["value"] for item in existing_env}

            # Apply updates
            env_map.update(env_updates)

            # Convert back to the list format ECS expects
            container["environment"] = [
                {"name": name, "value": value}
                for name, value in env_map.items()
            ]

        # Register the new task definition revision
        register_response = _retry_with_backoff(
            self._client.register_task_definition,
            **register_kwargs,
        )
        new_task_def_arn = register_response["taskDefinition"]["taskDefinitionArn"]

        logger.info(
            "Registered new task definition revision: %s", new_task_def_arn
        )
        return new_task_def_arn

    def force_new_deployment(
        self, cluster: str, service: str, task_definition_arn: str
    ) -> dict:
        """Trigger ECS force-new-deployment.

        Skips if the service's desired_count is 0 (no running tasks to replace).
        This avoids launching tasks for a service that is intentionally scaled to zero.

        Args:
            cluster: The ECS cluster name or ARN.
            service: The ECS service name or ARN.
            task_definition_arn: The task definition ARN to deploy.

        Returns:
            A dict with deployment status info:
            - deploymentStatus: "triggered" | "skipped_no_running_tasks"
            - message: Human-readable description of the action taken.

        Raises:
            ClientError: On unrecoverable ECS API errors or after retry exhaustion.
        """
        # Check current desired_count
        describe_response = _retry_with_backoff(
            self._client.describe_services,
            cluster=cluster,
            services=[service],
        )

        services = describe_response.get("services", [])
        if not services:
            raise ClientError(
                {
                    "Error": {
                        "Code": "ResourceNotFoundException",
                        "Message": f"Service '{service}' not found in cluster '{cluster}'",
                    }
                },
                "DescribeServices",
            )

        desired_count = services[0].get("desiredCount", 0)

        if desired_count == 0:
            logger.info(
                "Service %s in cluster %s has desired_count=0. "
                "Skipping force-new-deployment.",
                service,
                cluster,
            )
            return {
                "deploymentStatus": "skipped_no_running_tasks",
                "message": (
                    "ECS service has no running tasks (desired_count=0). "
                    "Task definition updated; new tasks will use updated values "
                    "when the service is scaled up."
                ),
            }

        # Trigger force-new-deployment
        _retry_with_backoff(
            self._client.update_service,
            cluster=cluster,
            service=service,
            taskDefinition=task_definition_arn,
            forceNewDeployment=True,
        )

        logger.info(
            "Force-new-deployment triggered for service %s in cluster %s "
            "with task definition %s",
            service,
            cluster,
            task_definition_arn,
        )
        return {
            "deploymentStatus": "triggered",
            "message": (
                "Configuration saved. ECS service redeployment triggered — "
                "new tasks will use updated values within minutes."
            ),
        }
