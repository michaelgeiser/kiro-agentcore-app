# Feature: admin-panel, Property 9: PUT environment-variables response contains required fields
"""
Property-based tests for PUT /admin/environment-variables response structure.

**Validates: Requirements 8.8**

For any successful PUT request to /admin/environment-variables with one or more
changed variables, the response body shall contain: a `updatedVars` array listing
exactly the variable names that were updated, a `deploymentStatus` string, and a
`message` string.
"""

import json
from unittest.mock import MagicMock, patch

from hypothesis import given, settings
from hypothesis import strategies as st

from src.handlers.admin_env_vars import KNOWN_VARIABLES, handler


# --- Strategies ---

# Strategy for selecting 1-6 variable names from KNOWN_VARIABLES
variable_names_strategy = st.lists(
    st.sampled_from(list(KNOWN_VARIABLES.keys())),
    min_size=1,
    max_size=6,
    unique=True,
)

# Strategy for generating random string values for variables
variable_value_strategy = st.text(min_size=1, max_size=64).filter(
    lambda s: s.strip() != ""
)


def build_admin_put_event(variables: dict[str, str]) -> dict:
    """Build a valid API Gateway v2 PUT event for /admin/environment-variables.

    Includes admin JWT claims so the handler passes authorization.
    """
    return {
        "requestContext": {
            "authorizer": {
                "jwt": {
                    "claims": {
                        "sub": "admin-user-123",
                        "cognito:groups": ["administrators"],
                    }
                }
            },
            "http": {
                "method": "PUT",
            },
        },
        "body": json.dumps({"variables": variables}),
    }


@settings(max_examples=100)
@given(
    var_names=variable_names_strategy,
    values=st.lists(variable_value_strategy, min_size=6, max_size=6),
)
def test_put_response_contains_required_fields(var_names: list[str], values: list[str]) -> None:
    """PUT /admin/environment-variables response always contains updatedVars, deploymentStatus, message.

    For any random subset of valid variable names with random values, after mocking
    SSM and ECS calls to succeed, the response must:
    1. Have statusCode 200
    2. Body contains `updatedVars` (list) with exactly the variable names sent
    3. Body contains `deploymentStatus` (string)
    4. Body contains `message` (string)
    """
    # Build the variables map from names and values
    variables = {name: values[i] for i, name in enumerate(var_names)}

    event = build_admin_put_event(variables)

    fake_task_def_arn = "arn:aws:ecs:us-east-1:123456789:task-definition/prescoach-eval:42"

    with patch("src.handlers.admin_env_vars.ssm_client") as mock_ssm, \
         patch("src.handlers.admin_env_vars.ecs_service") as mock_ecs:

        # Mock SSM get_parameter and put_parameter to succeed
        mock_ssm.get_parameter.return_value = {
            "Parameter": {"Value": "old-value"}
        }
        mock_ssm.put_parameter.return_value = {"Version": 1}

        # Mock ECS update_task_environment to return a fake ARN
        mock_ecs.update_task_environment.return_value = fake_task_def_arn

        # Mock ECS force_new_deployment to return a valid deployment result
        mock_ecs.force_new_deployment.return_value = {
            "deploymentStatus": "triggered",
            "message": "Configuration saved. ECS service redeployment triggered.",
        }

        response = handler(event, None)

    # Verify statusCode is 200
    assert response["statusCode"] == 200, (
        f"Expected statusCode 200, got {response['statusCode']}"
    )

    # Parse the response body
    body = json.loads(response["body"])

    # Verify `updatedVars` is a list
    assert "updatedVars" in body, "Response body missing 'updatedVars' field"
    assert isinstance(body["updatedVars"], list), (
        f"Expected updatedVars to be a list, got {type(body['updatedVars'])}"
    )

    # Verify `updatedVars` contains exactly the variable names that were in the request
    assert set(body["updatedVars"]) == set(var_names), (
        f"Expected updatedVars to be {sorted(var_names)}, got {sorted(body['updatedVars'])}"
    )
    assert len(body["updatedVars"]) == len(var_names), (
        f"Expected {len(var_names)} updatedVars, got {len(body['updatedVars'])}"
    )

    # Verify `deploymentStatus` is a string
    assert "deploymentStatus" in body, "Response body missing 'deploymentStatus' field"
    assert isinstance(body["deploymentStatus"], str), (
        f"Expected deploymentStatus to be a string, got {type(body['deploymentStatus'])}"
    )

    # Verify `message` is a string
    assert "message" in body, "Response body missing 'message' field"
    assert isinstance(body["message"], str), (
        f"Expected message to be a string, got {type(body['message'])}"
    )
