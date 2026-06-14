"""Unit tests for the load_config Lambda handler."""

import os
from unittest.mock import MagicMock, patch

import pytest
from moto import mock_aws
import boto3

from handlers.load_config import (
    PARAMETER_NAME_MAP,
    _fetch_ssm_parameters,
    _parse_value,
    handler,
)


class TestParseValue:
    """Tests for the _parse_value helper function."""

    def test_parse_int_field_valid(self):
        assert _parse_value("chunk_size_seconds", "30") == 30

    def test_parse_int_field_invalid(self):
        with pytest.raises(ValueError, match="must be an integer"):
            _parse_value("chunk_size_seconds", "not_a_number")

    def test_parse_bool_field_true(self):
        assert _parse_value("video_processing_enabled", "true") is True

    def test_parse_bool_field_false(self):
        assert _parse_value("video_processing_enabled", "false") is False

    def test_parse_bool_field_true_case_insensitive(self):
        assert _parse_value("video_processing_enabled", "True") is True
        assert _parse_value("batch_processing_enabled", "TRUE") is True

    def test_parse_bool_field_invalid(self):
        with pytest.raises(ValueError, match="must be 'true' or 'false'"):
            _parse_value("video_processing_enabled", "yes")

    def test_parse_string_field(self):
        assert _parse_value("embedding_model_id", "amazon.nova-embed") == "amazon.nova-embed"


class TestFetchSsmParameters:
    """Tests for the _fetch_ssm_parameters helper."""

    def test_single_page(self):
        mock_client = MagicMock()
        mock_client.get_parameters_by_path.return_value = {
            "Parameters": [
                {"Name": "/prescoach/dev/preparation-workflow/embedding-model-id", "Value": "model-1"},
                {"Name": "/prescoach/dev/preparation-workflow/chunk-size-seconds", "Value": "30"},
            ]
        }

        result = _fetch_ssm_parameters(mock_client, "/prescoach/dev/preparation-workflow/")

        assert result == {"embedding-model-id": "model-1", "chunk-size-seconds": "30"}
        mock_client.get_parameters_by_path.assert_called_once()

    def test_paginated_results(self):
        mock_client = MagicMock()
        mock_client.get_parameters_by_path.side_effect = [
            {
                "Parameters": [
                    {"Name": "/prescoach/dev/preparation-workflow/embedding-model-id", "Value": "model-1"},
                ],
                "NextToken": "token123",
            },
            {
                "Parameters": [
                    {"Name": "/prescoach/dev/preparation-workflow/chunk-size-seconds", "Value": "30"},
                ],
            },
        ]

        result = _fetch_ssm_parameters(mock_client, "/prescoach/dev/preparation-workflow/")

        assert result == {"embedding-model-id": "model-1", "chunk-size-seconds": "30"}
        assert mock_client.get_parameters_by_path.call_count == 2


@mock_aws
class TestHandler:
    """Tests for the load_config Lambda handler using moto."""

    def _setup_ssm_parameters(self, env: str = "dev"):
        """Set up all required SSM parameters."""
        ssm = boto3.client("ssm", region_name="us-east-1")
        base_path = f"/prescoach/{env}/preparation-workflow"
        params = {
            "embedding-model-id": "amazon.nova-embed-v1",
            "chunk-size-seconds": "30",
            "chunk-overlap-seconds": "5",
            "max-retry-attempts": "3",
            "video-processing-enabled": "true",
            "vector-store-endpoint": "https://vectorstore.example.com",
            "vector-store-type": "opensearch",
            "batch-size": "10",
            "batch-processing-enabled": "false",
        }
        for name, value in params.items():
            ssm.put_parameter(
                Name=f"{base_path}/{name}",
                Value=value,
                Type="String",
            )

    def test_handler_loads_all_parameters(self):
        self._setup_ssm_parameters()
        with patch.dict(os.environ, {"ENVIRONMENT": "dev"}):
            result = handler({}, None)

        assert result["embedding_model_id"] == "amazon.nova-embed-v1"
        assert result["chunk_size_seconds"] == 30
        assert result["chunk_overlap_seconds"] == 5
        assert result["max_retry_attempts"] == 3
        assert result["video_processing_enabled"] is True
        assert result["vector_store_endpoint"] == "https://vectorstore.example.com"
        assert result["vector_store_type"] == "opensearch"
        assert result["batch_size"] == 10
        assert result["batch_processing_enabled"] is False

    def test_handler_uses_environment_variable(self):
        self._setup_ssm_parameters(env="staging")
        with patch.dict(os.environ, {"ENVIRONMENT": "staging"}):
            result = handler({}, None)

        assert result["embedding_model_id"] == "amazon.nova-embed-v1"

    def test_handler_defaults_to_dev_environment(self):
        self._setup_ssm_parameters(env="dev")
        with patch.dict(os.environ, {}, clear=True):
            # Restore AWS credentials needed by moto
            os.environ["AWS_ACCESS_KEY_ID"] = "testing"
            os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
            os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
            result = handler({}, None)

        assert result["embedding_model_id"] == "amazon.nova-embed-v1"

    def test_handler_raises_on_missing_parameters(self):
        # Only put a subset of parameters
        ssm = boto3.client("ssm", region_name="us-east-1")
        ssm.put_parameter(
            Name="/prescoach/dev/preparation-workflow/embedding-model-id",
            Value="model-1",
            Type="String",
        )

        with patch.dict(os.environ, {"ENVIRONMENT": "dev"}):
            with pytest.raises(ValueError, match="Missing required SSM parameters"):
                handler({}, None)

    def test_handler_raises_on_no_parameters(self):
        with patch.dict(os.environ, {"ENVIRONMENT": "dev"}):
            with pytest.raises(ValueError, match="Missing required SSM parameters"):
                handler({}, None)

    def test_handler_error_message_lists_missing_params(self):
        ssm = boto3.client("ssm", region_name="us-east-1")
        # Only set a few parameters
        ssm.put_parameter(
            Name="/prescoach/dev/preparation-workflow/embedding-model-id",
            Value="model-1",
            Type="String",
        )
        ssm.put_parameter(
            Name="/prescoach/dev/preparation-workflow/chunk-size-seconds",
            Value="30",
            Type="String",
        )

        with patch.dict(os.environ, {"ENVIRONMENT": "dev"}):
            with pytest.raises(ValueError) as exc_info:
                handler({}, None)

        error_msg = str(exc_info.value)
        # Should mention specific missing parameters
        assert "batch-processing-enabled" in error_msg
        assert "batch-size" in error_msg
        assert "max-retry-attempts" in error_msg
