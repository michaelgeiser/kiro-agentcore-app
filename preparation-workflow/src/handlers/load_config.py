"""Lambda handler for loading workflow configuration from SSM Parameter Store."""

import logging
import os
from typing import Any

import boto3

from models.workflow_config import WorkflowConfig

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Mapping from SSM parameter names to WorkflowConfig field names
PARAMETER_NAME_MAP: dict[str, str] = {
    "embedding-model-id": "embedding_model_id",
    "chunk-size-seconds": "chunk_size_seconds",
    "chunk-overlap-seconds": "chunk_overlap_seconds",
    "max-retry-attempts": "max_retry_attempts",
    "video-processing-enabled": "video_processing_enabled",
    "vector-store-endpoint": "vector_store_endpoint",
    "vector-store-type": "vector_store_type",
    "batch-size": "batch_size",
    "batch-processing-enabled": "batch_processing_enabled",
    "embeddings-enabled": "embeddings_enabled",
}

# Fields that should be parsed as integers
INT_FIELDS: set[str] = {
    "chunk_size_seconds",
    "chunk_overlap_seconds",
    "max_retry_attempts",
    "batch_size",
}

# Fields that should be parsed as booleans
BOOL_FIELDS: set[str] = {
    "video_processing_enabled",
    "batch_processing_enabled",
    "embeddings_enabled",
}


def _parse_value(field_name: str, value: str) -> Any:
    """Parse a string value from SSM into the appropriate Python type."""
    if field_name in INT_FIELDS:
        try:
            return int(value)
        except ValueError:
            raise ValueError(
                f"Parameter '{field_name}' must be an integer, got '{value}'"
            )
    if field_name in BOOL_FIELDS:
        lower = value.lower()
        if lower == "true":
            return True
        elif lower == "false":
            return False
        else:
            raise ValueError(
                f"Parameter '{field_name}' must be 'true' or 'false', got '{value}'"
            )
    return value


def _fetch_ssm_parameters(ssm_client: Any, path: str) -> dict[str, str]:
    """Fetch all parameters under the given path, handling pagination."""
    parameters: dict[str, str] = {}
    kwargs: dict[str, Any] = {
        "Path": path,
        "Recursive": True,
        "WithDecryption": True,
    }

    while True:
        response = ssm_client.get_parameters_by_path(**kwargs)
        for param in response.get("Parameters", []):
            # Extract the parameter name (last segment of the full path)
            name = param["Name"].rsplit("/", 1)[-1]
            parameters[name] = param["Value"]

        next_token = response.get("NextToken")
        if next_token:
            kwargs["NextToken"] = next_token
        else:
            break

    return parameters


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda handler that loads workflow configuration from SSM Parameter Store.

    Reads all parameters from /prescoach/{env}/preparation-workflow/ namespace,
    parses them into a WorkflowConfig model, and returns the config as a dict.

    Args:
        event: Step Functions input event (passed through).
        context: Lambda context object.

    Returns:
        WorkflowConfig as a dictionary.

    Raises:
        ValueError: If required parameters are missing or have invalid values.
    """
    env = os.environ.get("ENV_NAME", os.environ.get("ENVIRONMENT", "dev"))
    path = f"/prescoach/{env}/preparation-workflow/"

    logger.info("Loading configuration from SSM path: %s", path)

    ssm_client = boto3.client("ssm")
    raw_parameters = _fetch_ssm_parameters(ssm_client, path)

    logger.info("Fetched %d parameters from SSM", len(raw_parameters))

    # Check for missing parameters
    missing_params = []
    for ssm_name in PARAMETER_NAME_MAP:
        if ssm_name not in raw_parameters:
            missing_params.append(ssm_name)

    if missing_params:
        missing_list = ", ".join(sorted(missing_params))
        raise ValueError(
            f"Missing required SSM parameters under '{path}': {missing_list}"
        )

    # Parse parameters into config fields
    config_values: dict[str, Any] = {}
    for ssm_name, field_name in PARAMETER_NAME_MAP.items():
        raw_value = raw_parameters[ssm_name]
        config_values[field_name] = _parse_value(field_name, raw_value)

    # Construct and validate WorkflowConfig
    config = WorkflowConfig(**config_values)

    logger.info("Successfully loaded workflow configuration")
    return config.model_dump()
