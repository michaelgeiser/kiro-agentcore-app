#!/usr/bin/env python3
"""CDK app entry point for CI/CD pipelines.

Creates three CodePipeline pipelines:
1. Frontend (webapp) deploy
2. Backend (upload-service) deploy
3. Full deploy (orchestrates both in order)
"""

import os

import aws_cdk as cdk

from pipeline_stack import PipelineStack

app = cdk.App()

# Read parameters from CDK context
app_name = app.node.try_get_context("appName") or "prescoach"
env_name = app.node.try_get_context("envName") or "dev"
instance_id = app.node.try_get_context("instanceId") or "kiro"
github_repo = app.node.try_get_context("githubRepo") or "michaelgeiser/kiro-agentcore-app"
github_branch = app.node.try_get_context("githubBranch") or "main"
cloudfront_dist_id = app.node.try_get_context("cloudfrontDistId") or ""
s3_bucket = app.node.try_get_context("s3Bucket") or ""

account = os.environ.get("CDK_DEFAULT_ACCOUNT")
region = os.environ.get("CDK_DEFAULT_REGION", "us-east-1")

env = cdk.Environment(account=account, region=region) if account else None

PipelineStack(
    app,
    f"{app_name}-{env_name}-{instance_id}-cicd",
    env=env,
    app_name=app_name,
    env_name=env_name,
    instance_id=instance_id,
    github_repo=github_repo,
    github_branch=github_branch,
    cloudfront_dist_id=cloudfront_dist_id,
    s3_bucket=s3_bucket,
)

app.synth()
