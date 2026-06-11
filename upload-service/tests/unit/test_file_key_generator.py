"""Unit tests for the file key generator utility."""

from src.utils.file_key_generator import generate_file_key


class TestGenerateFileKey:
    def test_returns_correct_format(self):
        result = generate_file_key("user-123", "sub-456", "presentation.mp3")
        assert result == "uploads/user-123/sub-456/presentation.mp3"

    def test_preserves_original_extension(self):
        result = generate_file_key("u1", "s1", "my_video.mp4")
        assert result.endswith(".mp4")

    def test_preserves_complex_file_name(self):
        result = generate_file_key("abc", "def", "my.file.name.wav")
        assert result == "uploads/abc/def/my.file.name.wav"

    def test_handles_uuid_style_ids(self):
        user_id = "d290f1ee-6c54-4b01-90e6-d701748f0851"
        submission_id = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        result = generate_file_key(user_id, submission_id, "talk.m4a")
        assert result == f"uploads/{user_id}/{submission_id}/talk.m4a"

    def test_returns_string(self):
        result = generate_file_key("user", "sub", "file.webm")
        assert isinstance(result, str)

    def test_starts_with_uploads_prefix(self):
        result = generate_file_key("any-user", "any-sub", "file.mov")
        assert result.startswith("uploads/")
