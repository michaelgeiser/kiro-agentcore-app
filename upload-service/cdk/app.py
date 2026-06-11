#!/usr/bin/env python3
"""CDK app entry point for the Upload and Storage Service.

Reads deployment parameters from CDK context and instantiates
the UploadServiceStack with a consistent stack name.

Requirements: 9.1, 11.2, 11.3
"""

import os

import aws_cdk as cdk

from upload_service.upload_service_stack import UploadServiceStack


app = cdk.App()

# Read deployment parameters from CDK context
app_name: str = app.node.try_get_context("appName") or "prescoach"
env_name: str = app.node.try_get_context("envName")
instance_id: str = app.node.try_get_context("instanceId")

# Construct stack name: {appName}-{envName}-{instanceId}
stack_name = f"{app_name}-{env_name}-{instance_id}"

# Configure environment from CDK_DEFAULT_ACCOUNT/CDK_DEFAULT_REGION or None
account = os.environ.get("CDK_DEFAULT_ACCOUNT")
region = os.environ.get("CDK_DEFAULT_REGION")

env = (
    cdk.Environment(account=account, region=region)
    if account and region
    else None
)

UploadServiceStack(
    app,
    stack_name,
    env=env,
)

app.synth()
