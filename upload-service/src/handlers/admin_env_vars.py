"""Admin environment variables handler — GET/PUT /admin/environment-variables.

Reads and writes runtime environment variable configuration from SSM Parameter
Store. On PUT, updates the ECS task definition and triggers a force-new-deployment
so that running tasks pick up changes immediately.
"""

import json
import logging
import os
import random
import time
import uuid
from typing import Any

import boto3
from botocore.exceptions import ClientError

from services.ecs_service import EcsService
from utils.admin_auth import verify_admin

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# --- Configuration from environment variables ---
SSM_PREFIX = os.environ.get("SSM_PREFIX", "/prescoach/prod/admin/env-vars/")
ECS_CLUSTER = os.environ.get("ECS_CLUSTER", "")
ECS_SERVICE = os.environ.get("ECS_SERVICE", "")
TASK_FAMILY = os.environ.get("TASK_FAMILY", "")

# CORS headers including PUT for admin endpoints
CORS_HEADERS: dict[str, str] = {
    "Access-Control-Allow-Origin": "https://kiro.geiserai.com",
    "Access-Control-Allow-Methods": "GET, PUT, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
    "Access-Control-Max-Age": "86400",
}

# --- Known variables registry ---
# Each entry: (description, inputType)
KNOWN_VARIABLES: dict[str, tuple[str, str]] = {
    "SESSION_SUPERVISOR_MODEL_ID": (
        "Foundation model used by the Session Supervisor agent",
        "model-dropdown",
    ),
    "COACHING_SUPERVISOR_MODEL_ID": (
        "Foundation model used by the Coaching Supervisor agent",
        "model-dropdown",
    ),
    "EVALUATION_MODEL_ID": (
        "Foundation model used by the individual evaluation agents",
        "model-dropdown",
    ),
    "IDLE_TIMEOUT_MINUTES": (
        "Minutes of inactivity before the ECS evaluation task exits",
        "text",
    ),
    "MAX_CONCURRENT_EVALUATIONS": (
        "Maximum number of submissions processed simultaneously",
        "concurrency-dropdown",
    ),
    "COGNITO_USER_POOL_NAME": (
        "Name of the Cognito User Pool for user lookups",
        "text",
    ),
}

# --- Retry configuration for SSM throttling ---
MAX_RETRIES = 3
BASE_DELAY_SECONDS = 0.5

# SSM recoverable error codes
SSM_RECOVERABLE_ERRORS = frozenset([
    "ThrottlingException",
    "TooManyRequestsException",
])

# Initialize AWS clients
ssm_client = boto3.client("ssm")
ecs_service = EcsService()


def _ssm_call_with_retry(operation, **kwargs) -> Any:
    """Execute an SSM operation with exponential backoff + jitter for throttling.

    Recoverable errors (throttling) are retried up to MAX_RETRIES times.
    Unrecoverable errors (access denied, parameter not found) fail immediately.

    Args:
        operation: The SSM client method to call.
        **kwargs: Arguments to pass to the SSM method.

    Returns:
        The response from the SSM method.

    Raises:
        ClientError: After retry exhaustion or on unrecoverable errors.
    """
    for attempt in range(MAX_RETRIES + 1):
        try:
            return operation(**kwargs)
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            if error_code in SSM_RECOVERABLE_ERRORS:
                if attempt < MAX_RETRIES:
                    delay = BASE_DELAY_SECONDS * (2 ** attempt) + random.uniform(0, 0.5)
                    logger.warning(
                        "SSM throttled (attempt %d/%d), retrying in %.2fs",
                        attempt + 1,
                        MAX_RETRIES,
                        delay,
                    )
                    time.sleep(delay)
                    continue
                else:
                    logger.error("SSM throttling persisted after %d retries", MAX_RETRIES)
                    raise
            else:
                # Unrecoverable — fail immediately
                raise


def _handle_get() -> dict[str, Any]:
    """Handle GET /admin/environment-variables.

    Reads all known environment variable values from SSM Parameter Store
    and returns them with descriptions and input type metadata.

    Returns:
        HTTP API v2 response with variables array.
    """
    variables = []

    for var_name, (description, input_type) in KNOWN_VARIABLES.items():
        param_path = f"{SSM_PREFIX}{var_name}"
        try:
            response = _ssm_call_with_retry(
                ssm_client.get_parameter,
                Name=param_path,
            )
            value = response["Parameter"]["Value"]
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            if error_code == "ParameterNotFound":
                # Parameter doesn't exist yet — return empty string
                value = ""
                logger.info("SSM parameter not found: %s (returning empty)", param_path)
            else:
                logger.error(
                    "Failed to read SSM parameter %s: %s",
                    param_path,
                    e.response["Error"].get("Message", ""),
                )
                return {
                    "statusCode": 500,
                    "headers": {**CORS_HEADERS, "Content-Type": "application/json"},
                    "body": json.dumps({
                        "message": f"Failed to read parameter: {var_name}",
                    }),
                }

        variables.append({
            "name": var_name,
            "value": value,
            "description": description,
            "inputType": input_type,
        })

    return {
        "statusCode": 200,
        "headers": {**CORS_HEADERS, "Content-Type": "application/json"},
        "body": json.dumps({"variables": variables}),
    }


def _handle_put(event: dict) -> dict[str, Any]:
    """Handle PUT /admin/environment-variables.

    Validates the request body, writes changed values to SSM, updates the
    ECS task definition, and triggers a force-new-deployment.

    Returns:
        HTTP API v2 response with updatedVars, deploymentStatus, and message.
    """
    # Parse and validate request body
    try:
        body = json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, TypeError):
        return {
            "statusCode": 400,
            "headers": {**CORS_HEADERS, "Content-Type": "application/json"},
            "body": json.dumps({
                "message": "Malformed request body: invalid JSON",
            }),
        }

    variables = body.get("variables")
    if not isinstance(variables, dict) or not variables:
        return {
            "statusCode": 400,
            "headers": {**CORS_HEADERS, "Content-Type": "application/json"},
            "body": json.dumps({
                "message": "Request body must contain a non-empty 'variables' map.",
            }),
        }

    # Reject unknown variable names (unrecoverable — 400 immediately)
    unknown_vars = [name for name in variables if name not in KNOWN_VARIABLES]
    if unknown_vars:
        return {
            "statusCode": 400,
            "headers": {**CORS_HEADERS, "Content-Type": "application/json"},
            "body": json.dumps({
                "message": f"Unknown variable names: {', '.join(unknown_vars)}",
            }),
        }

    # Write each changed variable to SSM
    updated_vars = []
    for var_name, var_value in variables.items():
        param_path = f"{SSM_PREFIX}{var_name}"
        try:
            _ssm_call_with_retry(
                ssm_client.put_parameter,
                Name=param_path,
                Value=str(var_value),
                Type="String",
                Overwrite=True,
            )
            updated_vars.append(var_name)
            logger.info("Updated SSM parameter: %s", param_path)
        except ClientError as e:
            logger.error(
                "Failed to write SSM parameter %s: %s",
                param_path,
                e.response["Error"].get("Message", ""),
            )
            return {
                "statusCode": 500,
                "headers": {**CORS_HEADERS, "Content-Type": "application/json"},
                "body": json.dumps({
                    "message": f"Failed to write parameter: {var_name}",
                }),
            }

    # Update ECS task definition and trigger force-deployment
    try:
        new_task_def_arn = ecs_service.update_task_environment(
            task_family=TASK_FAMILY,
            env_updates={name: str(val) for name, val in variables.items()},
        )

        deployment_result = ecs_service.force_new_deployment(
            cluster=ECS_CLUSTER,
            service=ECS_SERVICE,
            task_definition_arn=new_task_def_arn,
        )

        deployment_status = deployment_result["deploymentStatus"]
        message = deployment_result["message"]

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        logger.error(
            "ECS deployment failed: %s — %s",
            error_code,
            e.response["Error"].get("Message", ""),
        )
        # SSM is already updated — report partial success
        return {
            "statusCode": 200,
            "headers": {**CORS_HEADERS, "Content-Type": "application/json"},
            "body": json.dumps({
                "updatedVars": updated_vars,
                "deploymentStatus": "failed",
                "message": (
                    f"Configuration saved to SSM, but ECS deployment failed: "
                    f"{error_code}. Next manual deployment will use updated values."
                ),
            }),
        }

    return {
        "statusCode": 200,
        "headers": {**CORS_HEADERS, "Content-Type": "application/json"},
        "body": json.dumps({
            "updatedVars": updated_vars,
            "deploymentStatus": deployment_status,
            "message": message,
        }),
    }


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Route GET/PUT /admin/environment-variables.

    GET: Read all env var values from SSM, return with descriptions.
    PUT: Write changed values to SSM, update ECS task definition, trigger force-deploy.

    Defense in depth: Verifies 'administrators' in cognito:groups claim.
    """
    # Defense-in-depth: verify admin group membership
    is_admin, user_id = verify_admin(event)
    if not is_admin:
        logger.warning("Non-admin access attempt to admin env vars endpoint")
        return {
            "statusCode": 403,
            "headers": {**CORS_HEADERS, "Content-Type": "application/json"},
            "body": json.dumps({
                "message": "Forbidden: administrator access required",
            }),
        }

    # Route by HTTP method
    http_method = event["requestContext"]["http"]["method"]

    if http_method == "GET":
        return _handle_get()
    elif http_method == "PUT":
        return _handle_put(event)
    else:
        return {
            "statusCode": 405,
            "headers": {**CORS_HEADERS, "Content-Type": "application/json"},
            "body": json.dumps({
                "message": f"Method {http_method} not allowed",
            }),
        }
