#!/usr/bin/env python3
"""CDK app entry point for deploying the Preparation Workflow infrastructure.

Deploys: Step Functions state machine, Lambda functions, SQS queues,
SNS topic, SSM parameters, and EventBridge Pipe.
"""

import os

import aws_cdk as cdk

from preparation_workflow_stack import PreparationWorkflowStack

app = cdk.App()

# Read parameters from CDK context
app_name = app.node.try_get_context("appName") or "prescoach"
env_name = app.node.try_get_context("envName") or "dev"
instance_id = app.node.try_get_context("instanceId") or "kiro"

account = os.environ.get("CDK_DEFAULT_ACCOUNT")
region = os.environ.get("CDK_DEFAULT_REGION", "us-east-1")

env = cdk.Environment(account=account, region=region) if account else None

PreparationWorkflowStack(
    app,
    f"{app_name}-{env_name}-{instance_id}-preparation-workflow",
    env=env,
    env_name=env_name,
)

app.synth()
