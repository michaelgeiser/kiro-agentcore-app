"""Parse message Lambda handler for the Preparation Workflow.

Deserializes SQS message body JSON into a validated InputMessage model.
Returns structured results for both valid and invalid messages.
"""

import json

from pydantic import ValidationError

from models.input_message import InputMessage


def parse_message(message_body: str) -> dict:
    """Parse and validate SQS message body.

    Args:
        message_body: Raw JSON string from SQS message body.

    Returns:
        {"valid": True, "message": {...}} on success, or
        {"valid": False, "error": "..."} on failure.
    """
    if not message_body:
        return {"valid": False, "error": "Empty message body"}

    try:
        data = json.loads(message_body)
    except (json.JSONDecodeError, TypeError) as e:
        return {"valid": False, "error": f"Malformed JSON: {str(e)}"}

    try:
        input_message = InputMessage.model_validate(data)
    except ValidationError as e:
        return {"valid": False, "error": f"Validation error: {str(e)}"}

    return {"valid": True, "message": input_message.model_dump()}


def handler(event, context):
    """AWS Lambda handler entry point.

    Expects event with a "message_body" field containing the raw SQS message JSON string.
    """
    message_body = event.get("message_body", "")
    return parse_message(message_body)
