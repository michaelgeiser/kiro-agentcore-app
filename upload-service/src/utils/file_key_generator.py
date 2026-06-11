"""S3 file key generation utilities for the Upload Service."""


def generate_file_key(user_id: str, submission_id: str, original_file_name: str) -> str:
    """Generate an S3 file key following the platform naming convention.

    Produces a key in the format: uploads/{user_id}/{submission_id}/{original_file_name}
    The original file extension is preserved as part of the file name.

    Args:
        user_id: The authenticated user's identifier (Cognito sub).
        submission_id: The unique submission identifier (UUID v4).
        original_file_name: The original file name including extension.

    Returns:
        The S3 object key string.
    """
    return f"uploads/{user_id}/{submission_id}/{original_file_name}"
