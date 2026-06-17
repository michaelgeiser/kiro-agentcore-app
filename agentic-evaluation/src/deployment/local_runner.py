"""Local development runner for the Agentic Evaluation module.

Entry point for running the SessionSupervisor in Strands local mode
without needing Amazon Bedrock AgentCore deployed. Useful for
development, testing, and rapid iteration.

Also used as the entrypoint for ECS Fargate Spot tasks.

Reads configuration from environment variables:
    SQS_QUEUE_URL: URL of the SQS FIFO handoff queue
    SQS_DLQ_URL: URL of the dead-letter queue
    DYNAMODB_TABLE_NAME: DynamoDB submissions table name
    S3_BUCKET_NAME: S3 bucket for evaluation results and reports
    SNS_TOPIC_ARN: SNS topic ARN for error notifications
    AWS_REGION: AWS region (default: us-east-1)
    LOCAL_MODE: Always "true" when using this runner
    DEPLOYMENT_ENV: Environment name (default: dev)
    IDLE_TIMEOUT_MINUTES: Minutes of inactivity before graceful exit (default: 30)
    MAX_CONCURRENT_EVALUATIONS: Max parallel message processing (default: 5)

Requirements: 7.1, 7.2, 7.4, 7.5
"""

import logging
import os
import sys

import boto3

from agents.coaching_supervisor import CoachingSupervisor
from agents.registry import AgentRegistry
from agents.session_supervisor import SessionSupervisor
from deployment.agentcore_config import AgentCoreConfig, load_config
from services.error_notifier import ErrorNotifier
from services.report_generator import ReportGenerator
from services.sqs_consumer import SQSConsumer
from services.status_manager import StatusManager

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    """Set up structured logging for local development."""
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )


def _validate_config(config: AgentCoreConfig) -> None:
    """Validate that the configuration has all required infrastructure settings.

    Args:
        config: The loaded AgentCore configuration.

    Raises:
        SystemExit: If required infrastructure configuration is missing.
    """
    if config.infrastructure is None:
        logger.error(
            "Infrastructure configuration is incomplete. "
            "Ensure the following environment variables are set:\n"
            "  SQS_QUEUE_URL\n"
            "  SQS_DLQ_URL\n"
            "  DYNAMODB_TABLE_NAME\n"
            "  S3_BUCKET_NAME\n"
            "  SNS_TOPIC_ARN"
        )
        sys.exit(1)


def build_session_supervisor(config: AgentCoreConfig) -> SessionSupervisor:
    """Construct a fully-wired SessionSupervisor from configuration.

    Creates all service dependencies (SQS consumer, status manager,
    error notifier, report generator, coaching supervisor) using the
    infrastructure settings from the provided configuration.

    In local mode, all components use standard boto3 clients pointed at
    real or localstack AWS services. The Strands agent within the
    CoachingSupervisor runs in local mode (no AgentCore Runtime needed).

    Args:
        config: The deployment configuration with infrastructure settings.

    Returns:
        A fully-configured SessionSupervisor ready to consume messages.
    """
    infra = config.infrastructure
    assert infra is not None, "Infrastructure config must be set"

    region = infra.aws_region

    # Create boto3 clients
    sqs_client = boto3.client("sqs", region_name=region)
    s3_client = boto3.client("s3", region_name=region)
    sns_client = boto3.client("sns", region_name=region)
    dynamodb_resource = boto3.resource("dynamodb", region_name=region)

    # Build service dependencies
    sqs_consumer = SQSConsumer(
        queue_url=infra.sqs_queue_url,
        dlq_url=infra.sqs_dlq_url,
        sqs_client=sqs_client,
    )

    status_manager = StatusManager(
        table_name=infra.dynamodb_table_name,
        dynamodb_resource=dynamodb_resource,
    )

    error_notifier = ErrorNotifier(
        topic_arn=infra.sns_topic_arn,
        sns_client=sns_client,
    )

    report_generator = ReportGenerator(
        bucket_name=infra.s3_bucket_name,
        s3_client=s3_client,
    )

    # Build agent registry and coaching supervisor
    registry = AgentRegistry()

    coaching_model_id = os.environ.get(
        "COACHING_SUPERVISOR_MODEL_ID", "anthropic.claude-sonnet-4-6"
    )
    coaching_supervisor = CoachingSupervisor(
        registry=registry,
        model_id=coaching_model_id,
    )

    # Wire together the Session Supervisor
    session_supervisor = SessionSupervisor(
        sqs_consumer=sqs_consumer,
        status_manager=status_manager,
        coaching_supervisor=coaching_supervisor,
        report_generator=report_generator,
        error_notifier=error_notifier,
        s3_client=s3_client,
        bucket_name=infra.s3_bucket_name,
        registry=registry,
    )

    return session_supervisor


def main() -> None:
    """Entry point for local development execution.

    Loads configuration from environment variables, constructs the
    SessionSupervisor with all dependencies wired up, and starts
    the queue consumption loop.

    The SessionSupervisor runs in Strands local mode — the Coaching
    Supervisor's Strands Agent executes locally without AgentCore
    Runtime deployed. All AWS service calls (SQS, DynamoDB, S3, SNS)
    go to real or localstack endpoints based on boto3 configuration.
    """
    _configure_logging()

    logger.info("Starting Agentic Evaluation local runner")
    logger.info("Loading configuration from environment variables...")

    # Force local mode for this runner
    os.environ.setdefault("LOCAL_MODE", "true")

    config = load_config()

    logger.info(
        "Configuration loaded: environment=%s, local_mode=%s",
        config.environment.value,
        config.local_mode,
    )
    logger.info(
        "Agent configuration: "
        "session_supervisor(model=%s, timeout=%ds), "
        "coaching_supervisor(model=%s, timeout=%ds)",
        config.session_supervisor.model_id,
        config.session_supervisor.timeout_seconds,
        config.coaching_supervisor.model_id,
        config.coaching_supervisor.timeout_seconds,
    )
    logger.info(
        "Memory configuration: enabled=%s, ttl=%dh, max_entries=%d",
        config.memory.enabled,
        config.memory.session_ttl_hours,
        config.memory.max_session_entries,
    )

    _validate_config(config)

    logger.info(
        "Infrastructure: queue=%s, table=%s, bucket=%s",
        config.infrastructure.sqs_queue_url,
        config.infrastructure.dynamodb_table_name,
        config.infrastructure.s3_bucket_name,
    )

    session_supervisor = build_session_supervisor(config)

    # Read concurrency and idle timeout from environment
    idle_timeout_minutes = int(
        os.environ.get("IDLE_TIMEOUT_MINUTES", "30")
    )
    max_concurrent_evaluations = int(
        os.environ.get("MAX_CONCURRENT_EVALUATIONS", "5")
    )

    logger.info(
        "Session Supervisor initialized. Starting queue consumption loop..."
    )
    logger.info(
        "ECS config: idle_timeout=%d min, max_concurrent=%d",
        idle_timeout_minutes,
        max_concurrent_evaluations,
    )
    logger.info("Press Ctrl+C to stop.")

    try:
        session_supervisor.consume_queue(
            idle_timeout_minutes=idle_timeout_minutes,
            max_concurrent=max_concurrent_evaluations,
        )
    except KeyboardInterrupt:
        logger.info("Shutting down local runner (KeyboardInterrupt)")
    except Exception:
        logger.exception("Fatal error in local runner")
        sys.exit(1)


if __name__ == "__main__":
    main()
