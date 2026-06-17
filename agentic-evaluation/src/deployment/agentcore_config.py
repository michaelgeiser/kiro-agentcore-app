"""Bedrock AgentCore Runtime deployment configuration.

Provides environment-based configuration for deploying the Session Supervisor
and Coaching Supervisor agents on Amazon Bedrock AgentCore Runtime, including
memory configuration for session context persistence.

Supports three environments (dev, staging, prod) with appropriate defaults,
and can be overridden via environment variables for flexibility.

Requirements: 7.1, 7.2, 7.4, 7.5
"""

import os
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class DeploymentEnvironment(str, Enum):
    """Target deployment environment."""

    DEV = "dev"
    STAGING = "staging"
    PROD = "prod"


class AgentEndpointConfig(BaseModel):
    """Configuration for a single agent deployed on AgentCore Runtime.

    Attributes:
        agent_name: Logical name of the agent (used for registration).
        agent_id: AgentCore-assigned agent identifier (populated after deployment).
        model_id: The foundation model ID to use for reasoning.
        memory_enabled: Whether AgentCore memory is enabled for this agent.
        memory_retention_days: How long session memory is retained.
        max_tokens: Maximum tokens for agent responses.
        temperature: Temperature for model inference.
        timeout_seconds: Maximum execution time for the agent.
    """

    agent_name: str = Field(..., min_length=1)
    agent_id: str | None = None
    model_id: str = Field(default="anthropic.claude-sonnet-4-6")
    memory_enabled: bool = True
    memory_retention_days: int = Field(default=7, ge=1)
    max_tokens: int = Field(default=4096, ge=1)
    temperature: float = Field(default=0.3, ge=0.0, le=1.0)
    timeout_seconds: int = Field(default=300, ge=30)


class MemoryConfig(BaseModel):
    """AgentCore memory configuration for session context persistence.

    Memory allows agents to maintain context across the evaluation lifecycle
    without custom state management (Requirement 7.4).

    Attributes:
        enabled: Whether memory is active.
        session_ttl_hours: How long a session context is retained in memory.
        max_session_entries: Maximum number of context entries per session.
        persistence_type: Type of memory persistence (short-term session).
    """

    enabled: bool = True
    session_ttl_hours: int = Field(default=24, ge=1)
    max_session_entries: int = Field(default=100, ge=1)
    persistence_type: str = Field(default="short-term-session")


class InfrastructureConfig(BaseModel):
    """AWS infrastructure resource identifiers.

    Attributes:
        sqs_queue_url: URL of the SQS FIFO handoff queue.
        sqs_dlq_url: URL of the dead-letter queue.
        dynamodb_table_name: DynamoDB submissions table name.
        s3_bucket_name: S3 bucket for evaluation results and reports.
        sns_topic_arn: SNS topic ARN for error notifications.
        aws_region: AWS region for service clients.
    """

    sqs_queue_url: str = Field(..., min_length=1)
    sqs_dlq_url: str = Field(..., min_length=1)
    dynamodb_table_name: str = Field(..., min_length=1)
    s3_bucket_name: str = Field(..., min_length=1)
    sns_topic_arn: str = Field(..., min_length=1)
    aws_region: str = Field(default="us-east-1", min_length=1)


class AgentCoreConfig(BaseModel):
    """Complete deployment configuration for the Agentic Evaluation platform.

    Encapsulates agent endpoint configurations, memory settings, and
    infrastructure resource identifiers. Supports environment-based
    defaults (dev/staging/prod) and environment variable overrides.

    Attributes:
        environment: Target deployment environment.
        session_supervisor: Configuration for the Session Supervisor agent.
        coaching_supervisor: Configuration for the Coaching Supervisor agent.
        memory: AgentCore memory configuration for session persistence.
        infrastructure: AWS infrastructure resource identifiers.
        local_mode: If True, agents run locally via Strands without AgentCore.
    """

    environment: DeploymentEnvironment = DeploymentEnvironment.DEV
    session_supervisor: AgentEndpointConfig = Field(
        default_factory=lambda: AgentEndpointConfig(
            agent_name="session-supervisor",
            memory_enabled=True,
            timeout_seconds=600,
        )
    )
    coaching_supervisor: AgentEndpointConfig = Field(
        default_factory=lambda: AgentEndpointConfig(
            agent_name="coaching-supervisor",
            memory_enabled=True,
            timeout_seconds=300,
        )
    )
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    infrastructure: InfrastructureConfig | None = None
    local_mode: bool = False

    def is_local(self) -> bool:
        """Check if this configuration targets local execution."""
        return self.local_mode


# ---------------------------------------------------------------------------
# Environment-specific defaults
# ---------------------------------------------------------------------------

_ENVIRONMENT_DEFAULTS: dict[DeploymentEnvironment, dict[str, Any]] = {
    DeploymentEnvironment.DEV: {
        "session_supervisor": {
            "model_id": "anthropic.claude-sonnet-4-6",
            "timeout_seconds": 600,
            "temperature": 0.3,
        },
        "coaching_supervisor": {
            "model_id": "anthropic.claude-sonnet-4-6",
            "timeout_seconds": 300,
            "temperature": 0.3,
        },
        "memory": {
            "session_ttl_hours": 24,
            "max_session_entries": 50,
        },
    },
    DeploymentEnvironment.STAGING: {
        "session_supervisor": {
            "model_id": "anthropic.claude-sonnet-4-6",
            "timeout_seconds": 600,
            "temperature": 0.2,
        },
        "coaching_supervisor": {
            "model_id": "anthropic.claude-sonnet-4-6",
            "timeout_seconds": 300,
            "temperature": 0.2,
        },
        "memory": {
            "session_ttl_hours": 48,
            "max_session_entries": 100,
        },
    },
    DeploymentEnvironment.PROD: {
        "session_supervisor": {
            "model_id": "anthropic.claude-sonnet-4-6",
            "timeout_seconds": 900,
            "temperature": 0.1,
        },
        "coaching_supervisor": {
            "model_id": "anthropic.claude-sonnet-4-6",
            "timeout_seconds": 600,
            "temperature": 0.1,
        },
        "memory": {
            "session_ttl_hours": 72,
            "max_session_entries": 200,
        },
    },
}


def load_config(
    environment: DeploymentEnvironment | str | None = None,
) -> AgentCoreConfig:
    """Load deployment configuration from environment variables and defaults.

    Resolution order:
    1. Environment variables (highest priority)
    2. Environment-specific defaults (dev/staging/prod)
    3. Model field defaults (lowest priority)

    Environment Variables:
        DEPLOYMENT_ENV: One of "dev", "staging", "prod" (default: "dev")
        LOCAL_MODE: Set to "true" or "1" to enable local execution mode
        SQS_QUEUE_URL: URL of the SQS FIFO handoff queue
        SQS_DLQ_URL: URL of the dead-letter queue
        DYNAMODB_TABLE_NAME: DynamoDB submissions table name
        S3_BUCKET_NAME: S3 bucket for evaluation results and reports
        SNS_TOPIC_ARN: SNS topic ARN for error notifications
        AWS_REGION: AWS region (default: "us-east-1")
        SESSION_SUPERVISOR_MODEL_ID: Model ID override for Session Supervisor
        COACHING_SUPERVISOR_MODEL_ID: Model ID override for Coaching Supervisor
        MEMORY_SESSION_TTL_HOURS: Session memory TTL override
        MEMORY_ENABLED: Set to "false" or "0" to disable memory

    Args:
        environment: Target environment. If None, reads from DEPLOYMENT_ENV
            environment variable (defaults to "dev").

    Returns:
        A fully-populated AgentCoreConfig instance.
    """
    # Determine environment
    if environment is None:
        env_str = os.environ.get("DEPLOYMENT_ENV", "dev").lower()
    elif isinstance(environment, str):
        env_str = environment.lower()
    else:
        env_str = environment.value

    deploy_env = DeploymentEnvironment(env_str)
    defaults = _ENVIRONMENT_DEFAULTS.get(deploy_env, _ENVIRONMENT_DEFAULTS[DeploymentEnvironment.DEV])

    # Check local mode
    local_mode_raw = os.environ.get("LOCAL_MODE", "false").lower()
    local_mode = local_mode_raw in ("true", "1", "yes")

    # Build Session Supervisor config
    ss_defaults = defaults["session_supervisor"]
    session_supervisor = AgentEndpointConfig(
        agent_name="session-supervisor",
        model_id=os.environ.get("SESSION_SUPERVISOR_MODEL_ID", ss_defaults["model_id"]),
        memory_enabled=True,
        timeout_seconds=int(
            os.environ.get("SESSION_SUPERVISOR_TIMEOUT", str(ss_defaults["timeout_seconds"]))
        ),
        temperature=float(
            os.environ.get("SESSION_SUPERVISOR_TEMPERATURE", str(ss_defaults["temperature"]))
        ),
    )

    # Build Coaching Supervisor config
    cs_defaults = defaults["coaching_supervisor"]
    coaching_supervisor = AgentEndpointConfig(
        agent_name="coaching-supervisor",
        model_id=os.environ.get("COACHING_SUPERVISOR_MODEL_ID", cs_defaults["model_id"]),
        memory_enabled=True,
        timeout_seconds=int(
            os.environ.get("COACHING_SUPERVISOR_TIMEOUT", str(cs_defaults["timeout_seconds"]))
        ),
        temperature=float(
            os.environ.get("COACHING_SUPERVISOR_TEMPERATURE", str(cs_defaults["temperature"]))
        ),
    )

    # Build memory config
    mem_defaults = defaults["memory"]
    memory_enabled_raw = os.environ.get("MEMORY_ENABLED", "true").lower()
    memory_enabled = memory_enabled_raw not in ("false", "0", "no")

    memory = MemoryConfig(
        enabled=memory_enabled,
        session_ttl_hours=int(
            os.environ.get("MEMORY_SESSION_TTL_HOURS", str(mem_defaults["session_ttl_hours"]))
        ),
        max_session_entries=int(
            os.environ.get("MEMORY_MAX_ENTRIES", str(mem_defaults["max_session_entries"]))
        ),
    )

    # Build infrastructure config from env vars (may be None in local mode)
    infrastructure = _load_infrastructure_config()

    return AgentCoreConfig(
        environment=deploy_env,
        session_supervisor=session_supervisor,
        coaching_supervisor=coaching_supervisor,
        memory=memory,
        infrastructure=infrastructure,
        local_mode=local_mode,
    )


def _load_infrastructure_config() -> InfrastructureConfig | None:
    """Load infrastructure resource config from environment variables.

    Returns None if required variables are not set (e.g., in local mode
    without AWS infrastructure).

    Returns:
        InfrastructureConfig if all required vars are present, else None.
    """
    sqs_queue_url = os.environ.get("SQS_QUEUE_URL")
    sqs_dlq_url = os.environ.get("SQS_DLQ_URL")
    dynamodb_table = os.environ.get("DYNAMODB_TABLE_NAME")
    s3_bucket = os.environ.get("S3_BUCKET_NAME")
    sns_topic_arn = os.environ.get("SNS_TOPIC_ARN")
    aws_region = os.environ.get("AWS_REGION", "us-east-1")

    # All infrastructure fields are required if any are set
    required = [sqs_queue_url, sqs_dlq_url, dynamodb_table, s3_bucket, sns_topic_arn]
    if not all(required):
        return None

    return InfrastructureConfig(
        sqs_queue_url=sqs_queue_url,  # type: ignore[arg-type]
        sqs_dlq_url=sqs_dlq_url,  # type: ignore[arg-type]
        dynamodb_table_name=dynamodb_table,  # type: ignore[arg-type]
        s3_bucket_name=s3_bucket,  # type: ignore[arg-type]
        sns_topic_arn=sns_topic_arn,  # type: ignore[arg-type]
        aws_region=aws_region,
    )
