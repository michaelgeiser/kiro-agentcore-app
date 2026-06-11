"""Unit tests for the format validator."""

import pytest

from src.validation.format_validator import validate_format


class TestValidateFormat:
    """Tests for validate_format function."""

    @pytest.mark.parametrize(
        "filename,expected_type",
        [
            ("recording.mp3", "audio"),
            ("recording.wav", "audio"),
            ("recording.m4a", "audio"),
            ("recording.aac", "audio"),
            ("video.mp4", "video"),
            ("video.mov", "video"),
            ("video.webm", "video"),
        ],
    )
    def test_valid_extensions(self, filename: str, expected_type: str):
        result = validate_format(filename)
        assert result.valid is True
        assert result.file_type == expected_type
        assert result.error is None

    @pytest.mark.parametrize(
        "filename",
        [
            "Recording.MP3",
            "Recording.WAV",
            "Recording.M4A",
            "Recording.AAC",
            "Video.MP4",
            "Video.MOV",
            "Video.WEBM",
            "file.Mp3",
            "file.WaV",
        ],
    )
    def test_case_insensitive(self, filename: str):
        result = validate_format(filename)
        assert result.valid is True

    def test_multiple_dots_in_filename(self):
        result = validate_format("my.presentation.file.mp3")
        assert result.valid is True
        assert result.file_type == "audio"

    def test_unsupported_extension(self):
        result = validate_format("document.pdf")
        assert result.valid is False
        assert result.error is not None
        assert ".pdf" in result.error

    def test_no_extension(self):
        result = validate_format("filename_without_ext")
        assert result.valid is False
        assert result.error is not None

    def test_empty_filename(self):
        result = validate_format("")
        assert result.valid is False
        assert result.error is not None

    def test_whitespace_only_filename(self):
        result = validate_format("   ")
        assert result.valid is False
        assert result.error is not None

    def test_dot_only(self):
        result = validate_format(".")
        assert result.valid is False
        assert result.error is not None
