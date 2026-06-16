#!/usr/bin/env python3
"""CDK app entry point for Agentic Evaluation CI/CD pipeline.

Creates a CodePipeline pipeline that:
1. Pulls source from GitHub
2. Runs tests (property, unit, integration)
3. Deploys the Agentic Evaluation infrastructure via CDK
"""

import os

import aws_cdk as cdk

from agentic_evaluation_pipeline_stack import AgenticEvaluationPipelineStack

app = cdk.App()

# Read parameters from CDK context
app_name = app.node.try_get_context("appName") or "prescoach"
env_name = app.node.try_get_context("envName") or "dev"
instance_id = app.node.try_get_context("instanceId") or "kiro"
github_repo = app.node.try_get_context("githubRepo") or "michaelgeiser/kiro-agentcore-app"
github_branch = app.node.try_get_context("githubBranch") or "main"

account = os.environ.get("CDK_DEFAULT_ACCOUNT")
region = os.environ.get("CDK_DEFAULT_REGION", "us-east-1")

env = cdk.Environment(account=account, region=region) if account else None

AgenticEvaluationPipelineStack(
    app,
    f"{app_name}-{env_name}-{instance_id}-agentic-evaluation-cicd",
    env=env,
    app_name=app_name,
    env_name=env_name,
    instance_id=instance_id,
    github_repo=github_repo,
    github_branch=github_branch,
)

app.synth()
