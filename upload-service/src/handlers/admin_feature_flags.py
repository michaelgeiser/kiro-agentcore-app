"""Admin feature flags handler for GET/PUT /admin/feature-flags."""

import json
import logging
import os
import random
import time
from typing import Any

import boto3
from botocore.exceptions import ClientError

from src.utils.admin_auth import verify_admin

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# SSM prefix from environment variable, e.g. "/prescoach/prod/feature-flags/"
SSM_PREFIX = os.environ.get("SSM_PREFIX", "/prescoach/dev/feature-flags/")

# Known feature flags with their descriptions
KNOWN_FLAGS: dict[str, str] = {
    "video-processing-enabled": "Allow video file uploads to be processed (audio extraction via MediaConvert)",
    "batch-processing-enabled": "Enable batch processing mode for embedding creation",
    "embeddings-enabled": "Create vector embeddings from audio chunks during preparation (when disabled, evaluation uses transcript only)",
    "local-mode": "Run evaluation agents in local mode (in-process Bedrock calls) vs. AgentCore managed mode",
}

CORS_HEADERS: dict[str, str] = {
    "Access-Control-Allow-Origin": "https://kiro.geiserai.com",
    "Access-Control-Allow-Methods": "GET, PUT, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
    "Access-Control-Max-Age": "86400",
}

# Retry configuration for recoverable SSM errors
MAX_RETRIES = 3
BASE_DELAY_SECONDS = 0.5

ssm_client = boto3.client("ssm")


def _ssm_call_with_retry(operation, **kwargs) -> Any:
    """Execute an SSM operation with exponential backoff + jitter for throttling.

    Recoverable errors (throttling) are retried up to MAX_RETRIES times.
    Unrecoverable errors (access denied, parameter not found) fail immediately.
    """
    for attempt in range(MAX_RETRIES + 1):
        try:
            return operation(**kwargs)
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            if error_code in ("ThrottlingException", "TooManyRequestsException"):
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


def _get_all_flags() -> list[dict[str, Any]]:
    """Read all feature flag values from SSM Parameter Store.

    Returns a list of flag objects with name, enabled (boolean), and description.
    """
    flags = []
    for flag_name, description in KNOWN_FLAGS.items():
        param_path = f"{SSM_PREFIX}{flag_name}"
        try:
            response = _ssm_call_with_retry(
                ssm_client.get_parameter,
                Name=param_path,
            )
            value = response["Parameter"]["Value"].lower() == "true"
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            if error_code == "ParameterNotFound":
                # Default to false if parameter doesn't exist yet
                logger.info("Parameter %s not found, defaulting to false", param_path)
                value = False
            else:
                raise

        flags.append({
            "name": flag_name,
            "enabled": value,
            "description": description,
        })

    return flags


def _update_flag(flag_name: str, enabled: bool) -> dict[str, Any]:
    """Write a single feature flag value to SSM Parameter Store.

    Args:
        flag_name: The known flag name to update.
        enabled: The new boolean state.

    Returns:
        Response dict with name and enabled fields.
    """
    param_path = f"{SSM_PREFIX}{flag_name}"
    value_str = "true" if enabled else "false"

    _ssm_call_with_retry(
        ssm_client.put_parameter,
        Name=param_path,
        Value=value_str,
        Type="String",
        Overwrite=True,
    )

    logger.info("Updated feature flag %s to %s", flag_name, value_str)

    return {
        "name": flag_name,
        "enabled": enabled,
    }


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Route GET /admin/feature-flags and PUT /admin/feature-flags/{flag-name}.

    GET: Read all feature flag values from SSM, return with descriptions.
    PUT: Write single flag value to SSM.

    Defense in depth: Verifies 'administrators' in cognito:groups claim.
    """
    # Defense-in-depth authorization check
    is_admin, user_id = verify_admin(event)
    if not is_admin:
        return {
            "statusCode": 403,
            "headers": {**CORS_HEADERS, "Content-Type": "application/json"},
            "body": json.dumps({"message": "Forbidden: administrator access required"}),
        }

    # Extract HTTP method
    method = event["requestContext"]["http"]["method"]

    if method == "GET":
        return _handle_get()
    elif method == "PUT":
        return _handle_put(event)
    else:
        return {
            "statusCode": 405,
            "headers": {**CORS_HEADERS, "Content-Type": "application/json"},
            "body": json.dumps({"message": f"Method {method} not allowed"}),
        }


def _handle_get() -> dict[str, Any]:
    """Handle GET /admin/feature-flags — return all flags with current state."""
    try:
        flags = _get_all_flags()
    except ClientError as e:
        logger.error("Failed to read feature flags from SSM: %s", str(e))
        return {
            "statusCode": 500,
            "headers": {**CORS_HEADERS, "Content-Type": "application/json"},
            "body": json.dumps({"message": "Failed to read feature flags from SSM"}),
        }

    return {
        "statusCode": 200,
        "headers": {**CORS_HEADERS, "Content-Type": "application/json"},
        "body": json.dumps({"flags": flags}),
    }


def _handle_put(event: dict[str, Any]) -> dict[str, Any]:
    """Handle PUT /admin/feature-flags/{flag-name} — update a single flag."""
    # Extract flag name from path parameters
    path_params = event.get("pathParameters") or {}
    flag_name = path_params.get("flag-name")

    if not flag_name:
        return {
            "statusCode": 400,
            "headers": {**CORS_HEADERS, "Content-Type": "application/json"},
            "body": json.dumps({"message": "Missing flag name in path"}),
        }

    # Validate flag name is known — unknown flags are unrecoverable (404)
    if flag_name not in KNOWN_FLAGS:
        return {
            "statusCode": 404,
            "headers": {**CORS_HEADERS, "Content-Type": "application/json"},
            "body": json.dumps({"message": f"Unknown feature flag: {flag_name}"}),
        }

    # Parse request body
    try:
        body = json.loads(event.get("body", "{}"))
    except (json.JSONDecodeError, TypeError):
        return {
            "statusCode": 400,
            "headers": {**CORS_HEADERS, "Content-Type": "application/json"},
            "body": json.dumps({"message": "Malformed request body: invalid JSON"}),
        }

    # Validate 'enabled' field is present and boolean
    if "enabled" not in body:
        return {
            "statusCode": 400,
            "headers": {**CORS_HEADERS, "Content-Type": "application/json"},
            "body": json.dumps({"message": "Missing required field: enabled"}),
        }

    enabled = body["enabled"]
    if not isinstance(enabled, bool):
        return {
            "statusCode": 400,
            "headers": {**CORS_HEADERS, "Content-Type": "application/json"},
            "body": json.dumps({"message": "Field 'enabled' must be a boolean"}),
        }

    # Update the flag in SSM
    try:
        result = _update_flag(flag_name, enabled)
    except ClientError as e:
        logger.error("Failed to update feature flag %s: %s", flag_name, str(e))
        return {
            "statusCode": 500,
            "headers": {**CORS_HEADERS, "Content-Type": "application/json"},
            "body": json.dumps({"message": "Failed to update feature flag in SSM"}),
        }

    return {
        "statusCode": 200,
        "headers": {**CORS_HEADERS, "Content-Type": "application/json"},
        "body": json.dumps(result),
    }
