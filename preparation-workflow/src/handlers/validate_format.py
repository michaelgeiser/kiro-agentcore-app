"""Lambda handler for file format validation and processing decision.

Combines FileValidationResult with the Feature_Flag_Video_Processing
configuration to determine the next processing step in the workflow.
"""

from validation.format_validator import validate_format


def make_processing_decision(
    file_type: str | None, video_processing_enabled: bool
) -> dict:
    """Determine next processing step based on file type and feature flag.

    Args:
        file_type: The validated file type ("audio" or "video"), or None.
        video_processing_enabled: Whether video processing is enabled.

    Returns:
        A dict with keys:
        - "decision": one of "embed", "extract_audio", or "fail"
        - "reason": human-readable explanation of the decision
    """
    if file_type == "audio":
        return {
            "decision": "embed",
            "reason": "Audio file proceeds directly to embedding",
        }

    if file_type == "video" and video_processing_enabled:
        return {
            "decision": "extract_audio",
            "reason": "Video file will have audio extracted before embedding",
        }

    if file_type == "video" and not video_processing_enabled:
        return {
            "decision": "fail",
            "reason": "Video processing is not currently enabled",
        }

    return {
        "decision": "fail",
        "reason": f"Unknown file type: {file_type}",
    }


def handler(event, context):
    """Lambda handler for format validation and processing decision.

    Args:
        event: Dict containing:
            - original_file_name: The filename to validate
            - video_processing_enabled: Whether video processing is enabled
        context: Lambda context (unused).

    Returns:
        Dict with keys:
        - valid: Whether the file format is valid
        - decision: The processing decision ("embed", "extract_audio", or "fail")
        - reason: Explanation of the decision
        - file_type: The detected file type (when valid)
    """
    filename = event.get("original_file_name", "")
    video_flag = event.get("video_processing_enabled", False)

    validation_result = validate_format(filename)
    if not validation_result.valid:
        return {"decision": "fail", "reason": validation_result.error, "valid": False}

    decision = make_processing_decision(validation_result.file_type, video_flag)
    decision["valid"] = True
    decision["file_type"] = validation_result.file_type
    return decision
