"""File format validation for the Preparation Workflow."""

import os

from src.models import FileValidationResult

AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm"}


def validate_format(filename: str) -> FileValidationResult:
    """Validate file format against accepted audio and video extensions.

    Extracts the file extension case-insensitively and checks it against
    the accepted audio and video format sets.

    Args:
        filename: The filename (or path) to validate.

    Returns:
        FileValidationResult with:
        - valid=True, file_type="audio" for audio extensions
        - valid=True, file_type="video" for video extensions
        - valid=False, error="..." for unrecognized extensions
    """
    if not filename or not filename.strip():
        return FileValidationResult(
            valid=False,
            error="Filename is empty",
        )

    _, ext = os.path.splitext(filename)
    ext_lower = ext.lower()

    if not ext_lower:
        return FileValidationResult(
            valid=False,
            error=f"No file extension found in '{filename}'",
        )

    if ext_lower in AUDIO_EXTENSIONS:
        return FileValidationResult(valid=True, file_type="audio")

    if ext_lower in VIDEO_EXTENSIONS:
        return FileValidationResult(valid=True, file_type="video")

    return FileValidationResult(
        valid=False,
        error=f"Unsupported file extension '{ext_lower}'",
    )
