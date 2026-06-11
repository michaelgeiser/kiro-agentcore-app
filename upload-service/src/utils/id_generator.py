"""UUID generation utilities for the Upload Service."""

import uuid


def generate_submission_id() -> str:
    """Generate a unique submission ID using UUID v4.

    Returns:
        A UUID v4 string for uniquely identifying a submission.
    """
    return str(uuid.uuid4())


def generate_correlation_id() -> str:
    """Generate a unique correlation ID using UUID v4.

    Used in error responses for troubleshooting and log correlation.

    Returns:
        A UUID v4 string for correlating requests across services.
    """
    return str(uuid.uuid4())
