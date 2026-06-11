"""Unit tests for the ID generator utility."""

import uuid

from src.utils.id_generator import generate_correlation_id, generate_submission_id


class TestGenerateSubmissionId:
    def test_returns_string(self):
        result = generate_submission_id()
        assert isinstance(result, str)

    def test_returns_valid_uuid4(self):
        result = generate_submission_id()
        parsed = uuid.UUID(result)
        assert parsed.version == 4

    def test_returns_unique_values(self):
        ids = {generate_submission_id() for _ in range(100)}
        assert len(ids) == 100


class TestGenerateCorrelationId:
    def test_returns_string(self):
        result = generate_correlation_id()
        assert isinstance(result, str)

    def test_returns_valid_uuid4(self):
        result = generate_correlation_id()
        parsed = uuid.UUID(result)
        assert parsed.version == 4

    def test_returns_unique_values(self):
        ids = {generate_correlation_id() for _ in range(100)}
        assert len(ids) == 100
