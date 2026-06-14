"""Unit tests for audio extraction service.

Tests extract_audio with mocked MediaConvert responses (success, failure, timeout)
and construct_output_key with various inputs.

Requirements: 3.1, 3.2, 3.3
"""

from unittest.mock import MagicMock, patch

import pytest

from services.audio_extraction import construct_output_key, extract_audio


class TestConstructOutputKey:
    """Tests for construct_output_key function."""

    def test_default_format_mp3(self):
        result = construct_output_key("user123", "sub456")
        assert result == "processed/user123/sub456/audio.mp3"

    def test_custom_format_wav(self):
        result = construct_output_key("user123", "sub456", output_format="wav")
        assert result == "processed/user123/sub456/audio.wav"

    def test_custom_format_m4a(self):
        result = construct_output_key("user_abc", "sub_xyz", output_format="m4a")
        assert result == "processed/user_abc/sub_xyz/audio.m4a"

    def test_preserves_user_id_exactly(self):
        result = construct_output_key("User-With-Dashes", "sub1")
        assert "User-With-Dashes" in result

    def test_preserves_submission_id_exactly(self):
        result = construct_output_key("u1", "submission-with-special_chars")
        assert "submission-with-special_chars" in result

    def test_pattern_structure(self):
        """Verify output matches pattern: processed/{user_id}/{submission_id}/audio.{format}"""
        result = construct_output_key("myuser", "mysub", "aac")
        parts = result.split("/")
        assert parts[0] == "processed"
        assert parts[1] == "myuser"
        assert parts[2] == "mysub"
        assert parts[3] == "audio.aac"


class TestExtractAudio:
    """Tests for extract_audio with mocked MediaConvert client."""

    @patch("services.audio_extraction._create_mediaconvert_client")
    def test_success_scenario(self, mock_create_client):
        """MediaConvert job completes successfully."""
        mock_client = MagicMock()
        mock_create_client.return_value = mock_client

        # Mock create_job returning a job ID
        mock_client.create_job.return_value = {
            "Job": {"Id": "job-12345"}
        }

        # Mock get_job returning COMPLETE status
        mock_client.get_job.return_value = {
            "Job": {"Status": "COMPLETE"}
        }

        result = extract_audio(
            s3_bucket="my-bucket",
            s3_input_key="uploads/user1/sub1/video.mp4",
            user_id="user1",
            submission_id="sub1",
            output_format="mp3",
            mediaconvert_role_arn="arn:aws:iam::123456789:role/MediaConvertRole",
            mediaconvert_endpoint="https://mediaconvert.us-east-1.amazonaws.com",
        )

        assert result["status"] == "COMPLETE"
        assert result["output_s3_key"] == "processed/user1/sub1/audio.mp3"
        assert result["job_id"] == "job-12345"

    @patch("services.audio_extraction._create_mediaconvert_client")
    def test_failure_scenario(self, mock_create_client):
        """MediaConvert job returns ERROR status."""
        mock_client = MagicMock()
        mock_create_client.return_value = mock_client

        mock_client.create_job.return_value = {
            "Job": {"Id": "job-failed-99"}
        }

        # Mock get_job returning ERROR status
        mock_client.get_job.return_value = {
            "Job": {"Status": "ERROR", "ErrorMessage": "Unsupported codec"}
        }

        result = extract_audio(
            s3_bucket="my-bucket",
            s3_input_key="uploads/user2/sub2/video.mov",
            user_id="user2",
            submission_id="sub2",
            output_format="mp3",
            mediaconvert_role_arn="arn:aws:iam::123456789:role/MediaConvertRole",
            mediaconvert_endpoint="https://mediaconvert.us-east-1.amazonaws.com",
        )

        assert result["status"] == "ERROR"
        assert result["output_s3_key"] == "processed/user2/sub2/audio.mp3"
        assert result["job_id"] == "job-failed-99"

    @patch("services.audio_extraction.time.sleep", return_value=None)
    @patch("services.audio_extraction._create_mediaconvert_client")
    def test_timeout_scenario(self, mock_create_client, mock_sleep):
        """MediaConvert job never completes within max polling attempts."""
        mock_client = MagicMock()
        mock_create_client.return_value = mock_client

        mock_client.create_job.return_value = {
            "Job": {"Id": "job-timeout-01"}
        }

        # Always return PROGRESSING status to trigger timeout
        mock_client.get_job.return_value = {
            "Job": {"Status": "PROGRESSING"}
        }

        result = extract_audio(
            s3_bucket="my-bucket",
            s3_input_key="uploads/user3/sub3/video.webm",
            user_id="user3",
            submission_id="sub3",
            output_format="mp3",
            mediaconvert_role_arn="arn:aws:iam::123456789:role/MediaConvertRole",
            mediaconvert_endpoint="https://mediaconvert.us-east-1.amazonaws.com",
        )

        # On timeout, extract_audio catches TimeoutError and returns ERROR status
        assert result["status"] == "ERROR"
        assert result["job_id"] == "job-timeout-01"

    @patch("services.audio_extraction._create_mediaconvert_client")
    def test_job_submission_failure(self, mock_create_client):
        """MediaConvert job submission raises an exception."""
        mock_client = MagicMock()
        mock_create_client.return_value = mock_client

        mock_client.create_job.side_effect = Exception("Access denied")

        with pytest.raises(RuntimeError, match="MediaConvert job submission failed"):
            extract_audio(
                s3_bucket="my-bucket",
                s3_input_key="uploads/user4/sub4/video.mp4",
                user_id="user4",
                submission_id="sub4",
                output_format="mp3",
                mediaconvert_role_arn="arn:aws:iam::123456789:role/MediaConvertRole",
                mediaconvert_endpoint="https://mediaconvert.us-east-1.amazonaws.com",
            )

    @patch("services.audio_extraction._create_mediaconvert_client")
    def test_result_dict_structure(self, mock_create_client):
        """Verify the returned dict has the expected keys."""
        mock_client = MagicMock()
        mock_create_client.return_value = mock_client

        mock_client.create_job.return_value = {"Job": {"Id": "job-struct"}}
        mock_client.get_job.return_value = {"Job": {"Status": "COMPLETE"}}

        result = extract_audio(
            s3_bucket="bucket",
            s3_input_key="key",
            user_id="u",
            submission_id="s",
            mediaconvert_role_arn="arn",
            mediaconvert_endpoint="https://endpoint",
        )

        assert "status" in result
        assert "output_s3_key" in result
        assert "job_id" in result
        assert len(result) == 3
