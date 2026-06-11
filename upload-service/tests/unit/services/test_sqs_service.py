"""Unit tests for SQS service retry logic.

Tests exponential backoff timing, successful publish scenarios,
and failure after retry exhaustion.
"""

from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from src.models.sqs_message import SqsMessageBody
from src.services.sqs_service import SqsService


@pytest.fixture
def sqs_message() -> SqsMessageBody:
    return SqsMessageBody(
        submission_id="sub-123",
        user_id="user-456",
        s3_file_key="uploads/user-456/sub-123/presentation.mp3",
        original_file_name="presentation.mp3",
        presentation_title="My Presentation",
    )


def _make_client_error() -> ClientError:
    return ClientError(
        error_response={"Error": {"Code": "ServiceUnavailable", "Message": "Service unavailable"}},
        operation_name="SendMessage",
    )


@patch.dict("os.environ", {"SQS_QUEUE_URL": "https://sqs.us-east-1.amazonaws.com/123456789/test-queue"})
class TestSqsServiceRetryLogic:
    """Tests for SQS publish retry behavior."""

    @patch("src.services.sqs_service.time.sleep")
    @patch("src.services.sqs_service.boto3.client")
    def test_successful_publish_first_attempt_no_retry(
        self, mock_boto_client: MagicMock, mock_sleep: MagicMock, sqs_message: SqsMessageBody
    ) -> None:
        """Successful publish on first attempt should not invoke any retries or sleep."""
        mock_sqs = MagicMock()
        mock_boto_client.return_value = mock_sqs

        service = SqsService()
        service.publish_message(sqs_message)

        mock_sqs.send_message.assert_called_once_with(
            QueueUrl="https://sqs.us-east-1.amazonaws.com/123456789/test-queue",
            MessageBody=sqs_message.model_dump_json(),
        )
        mock_sleep.assert_not_called()

    @patch("src.services.sqs_service.time.sleep")
    @patch("src.services.sqs_service.boto3.client")
    def test_successful_publish_on_second_retry(
        self, mock_boto_client: MagicMock, mock_sleep: MagicMock, sqs_message: SqsMessageBody
    ) -> None:
        """Successful publish on second attempt after first failure."""
        mock_sqs = MagicMock()
        mock_boto_client.return_value = mock_sqs
        mock_sqs.send_message.side_effect = [
            _make_client_error(),
            None,  # Success on second attempt
        ]

        service = SqsService()
        service.publish_message(sqs_message)

        assert mock_sqs.send_message.call_count == 2
        # First failure triggers sleep with base_delay * 2^0 = 0.1s
        mock_sleep.assert_called_once_with(0.1)

    @patch("src.services.sqs_service.time.sleep")
    @patch("src.services.sqs_service.boto3.client")
    def test_failure_after_all_retries_exhausted(
        self, mock_boto_client: MagicMock, mock_sleep: MagicMock, sqs_message: SqsMessageBody
    ) -> None:
        """Should raise after all 3 retry attempts are exhausted."""
        mock_sqs = MagicMock()
        mock_boto_client.return_value = mock_sqs
        mock_sqs.send_message.side_effect = [
            _make_client_error(),
            _make_client_error(),
            _make_client_error(),
        ]

        service = SqsService()

        with pytest.raises(ClientError):
            service.publish_message(sqs_message)

        assert mock_sqs.send_message.call_count == 3
        # Sleep called between attempts: after attempt 0 and attempt 1
        # (not after the final attempt since it raises immediately)
        assert mock_sleep.call_count == 2

    @patch("src.services.sqs_service.time.sleep")
    @patch("src.services.sqs_service.boto3.client")
    def test_exponential_backoff_timing(
        self, mock_boto_client: MagicMock, mock_sleep: MagicMock, sqs_message: SqsMessageBody
    ) -> None:
        """Backoff should follow 100ms, 200ms, 400ms pattern (base=0.1, multiplier=2)."""
        mock_sqs = MagicMock()
        mock_boto_client.return_value = mock_sqs
        mock_sqs.send_message.side_effect = [
            _make_client_error(),
            _make_client_error(),
            _make_client_error(),
        ]

        service = SqsService()

        with pytest.raises(ClientError):
            service.publish_message(sqs_message)

        # Verify exponential backoff delays: 0.1 * 2^0 = 0.1, 0.1 * 2^1 = 0.2
        # No sleep after the last attempt since it raises
        sleep_calls = [call.args[0] for call in mock_sleep.call_args_list]
        assert sleep_calls == [0.1, 0.2]

    @patch("src.services.sqs_service.time.sleep")
    @patch("src.services.sqs_service.boto3.client")
    def test_successful_publish_on_third_attempt(
        self, mock_boto_client: MagicMock, mock_sleep: MagicMock, sqs_message: SqsMessageBody
    ) -> None:
        """Successful publish on third (final) attempt after two failures."""
        mock_sqs = MagicMock()
        mock_boto_client.return_value = mock_sqs
        mock_sqs.send_message.side_effect = [
            _make_client_error(),
            _make_client_error(),
            None,  # Success on third attempt
        ]

        service = SqsService()
        service.publish_message(sqs_message)

        assert mock_sqs.send_message.call_count == 3
        # Sleep between attempt 0→1 (0.1s) and attempt 1→2 (0.2s)
        sleep_calls = [call.args[0] for call in mock_sleep.call_args_list]
        assert sleep_calls == [0.1, 0.2]
