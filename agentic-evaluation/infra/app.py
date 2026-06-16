#!/usr/bin/env python3
"""CDK app entry point for Agentic Evaluation infrastructure.

Creates the runtime infrastructure for the evaluation module:
- SSM Parameters for runtime configuration
- SNS Topic for evaluation error notifications
- CloudWatch Alarm for DLQ threshold monitoring
"""

import os

import aws_cdk as cdk

from agentic_evaluation_stack import AgenticEvaluationStack

app = cdk.App()

app_name = app.node.try_get_context("appName") or "prescoach"
env_name = app.node.try_get_context("envName") or "dev"
instance_id = app.node.try_get_context("instanceId") or "kiro"

account = os.environ.get("CDK_DEFAULT_ACCOUNT")
region = os.environ.get("CDK_DEFAULT_REGION", "us-east-1")

env = cdk.Environment(account=account, region=region) if account else None

AgenticEvaluationStack(
    app,
    f"{app_name}-{env_name}-{instance_id}-agentic-evaluation",
    env=env,
    app_name=app_name,
    env_name=env_name,
    instance_id=instance_id,
)

app.synth()
