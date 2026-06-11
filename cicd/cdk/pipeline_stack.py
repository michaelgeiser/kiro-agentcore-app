"""CDK Stack defining three CodePipeline pipelines for CI/CD.

Pipeline 1 - Frontend: Syncs webapp/ to S3 and invalidates CloudFront
Pipeline 2 - Backend: Installs deps, runs CDK deploy for upload-service
Pipeline 3 - Full: Runs Frontend then Backend in sequence
"""

from aws_cdk import (
    CfnOutput,
    Duration,
    SecretValue,
    Stack,
    aws_codebuild as codebuild,
    aws_codepipeline as codepipeline,
    aws_codepipeline_actions as actions,
    aws_iam as iam,
    aws_s3 as s3,
)
from constructs import Construct


class PipelineStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        app_name: str,
        env_name: str,
        instance_id: str,
        github_repo: str,
        github_branch: str,
        cloudfront_dist_id: str,
        s3_bucket: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        resource_prefix = f"{app_name}-{env_name}-{instance_id}"

        # --- GitHub Source (shared across all pipelines) ---
        # You must store a GitHub personal access token in Secrets Manager
        # as "github-token" before deploying this stack.
        github_token = SecretValue.secrets_manager("github-token")

        # --- Shared IAM Policy for CodeBuild ---
        deploy_policy = iam.PolicyStatement(
            actions=[
                # S3 (frontend deploy)
                "s3:PutObject",
                "s3:DeleteObject",
                "s3:GetObject",
                "s3:ListBucket",
                "s3:GetBucketLocation",
                # CloudFront (invalidation)
                "cloudfront:CreateInvalidation",
                # CloudFormation (CDK deploy)
                "cloudformation:*",
                # CDK asset publishing
                "sts:AssumeRole",
                # Lambda, DynamoDB, SQS, SNS, Cognito, API Gateway (CDK creates these)
                "lambda:*",
                "dynamodb:*",
                "sqs:*",
                "sns:*",
                "cognito-idp:*",
                "apigateway:*",
                "execute-api:*",
                # IAM (CDK creates roles)
                "iam:*",
                # S3 (CDK assets bucket + upload bucket)
                "s3:*",
                # SSM (CDK bootstrap reads)
                "ssm:GetParameter",
                # ECR (CDK bootstrap)
                "ecr:*",
            ],
            resources=["*"],
        )

        # =====================================================================
        # PIPELINE 1: Frontend (webapp)
        # =====================================================================
        frontend_build = codebuild.PipelineProject(
            self,
            "FrontendBuild",
            project_name=f"{resource_prefix}-frontend-build",
            environment=codebuild.BuildEnvironment(
                build_image=codebuild.LinuxBuildImage.STANDARD_7_0,
                compute_type=codebuild.ComputeType.SMALL,
            ),
            environment_variables={
                "S3_BUCKET": codebuild.BuildEnvironmentVariable(value=s3_bucket),
                "CLOUDFRONT_DIST_ID": codebuild.BuildEnvironmentVariable(value=cloudfront_dist_id),
                "APP_NAME": codebuild.BuildEnvironmentVariable(value=app_name),
                "ENV_NAME": codebuild.BuildEnvironmentVariable(value=env_name),
                "INSTANCE_ID": codebuild.BuildEnvironmentVariable(value=instance_id),
                "STACK_NAME": codebuild.BuildEnvironmentVariable(value=resource_prefix),
            },
            build_spec=codebuild.BuildSpec.from_object({
                "version": "0.2",
                "phases": {
                    "install": {
                        "runtime-versions": {"nodejs": "20"},
                        "commands": [
                            "echo 'Installing jq...'",
                            "yum install -y jq || apt-get install -y jq || true",
                        ],
                    },
                    "pre_build": {
                        "commands": [
                            "echo 'Generating frontend config from CDK outputs...'",
                            "cd upload-service",
                            "chmod +x scripts/generate-frontend-config.sh",
                            "./scripts/generate-frontend-config.sh $STACK_NAME",
                            "cd ..",
                        ],
                    },
                    "build": {
                        "commands": [
                            "echo 'Deploying frontend to S3...'",
                            "cd webapp",
                            "aws s3 sync . s3://$S3_BUCKET/ "
                            "--exclude 'node_modules/*' "
                            "--exclude 'tests/*' "
                            "--exclude 'package*.json' "
                            "--exclude 'vitest.config.js' "
                            "--delete",
                            "echo 'Invalidating CloudFront cache...'",
                            "aws cloudfront create-invalidation --distribution-id $CLOUDFRONT_DIST_ID --paths '/*'",
                        ],
                    },
                },
            }),
        )
        frontend_build.add_to_role_policy(deploy_policy)

        frontend_source_output = codepipeline.Artifact("FrontendSource")
        frontend_pipeline = codepipeline.Pipeline(
            self,
            "FrontendPipeline",
            pipeline_name=f"{resource_prefix}-frontend",
            stages=[
                codepipeline.StageProps(
                    stage_name="Source",
                    actions=[
                        actions.GitHubSourceAction(
                            action_name="GitHub",
                            owner=github_repo.split("/")[0],
                            repo=github_repo.split("/")[1],
                            branch=github_branch,
                            oauth_token=github_token,
                            output=frontend_source_output,
                            trigger=actions.GitHubTrigger.NONE,  # Manual or invoked by orchestrator
                        ),
                    ],
                ),
                codepipeline.StageProps(
                    stage_name="Deploy",
                    actions=[
                        actions.CodeBuildAction(
                            action_name="DeployFrontend",
                            project=frontend_build,
                            input=frontend_source_output,
                        ),
                    ],
                ),
            ],
        )

        # =====================================================================
        # PIPELINE 2: Backend (upload-service)
        # =====================================================================
        backend_build = codebuild.PipelineProject(
            self,
            "BackendBuild",
            project_name=f"{resource_prefix}-backend-build",
            environment=codebuild.BuildEnvironment(
                build_image=codebuild.LinuxBuildImage.STANDARD_7_0,
                compute_type=codebuild.ComputeType.MEDIUM,
            ),
            environment_variables={
                "APP_NAME": codebuild.BuildEnvironmentVariable(value=app_name),
                "ENV_NAME": codebuild.BuildEnvironmentVariable(value=env_name),
                "INSTANCE_ID": codebuild.BuildEnvironmentVariable(value=instance_id),
            },
            build_spec=codebuild.BuildSpec.from_object({
                "version": "0.2",
                "phases": {
                    "install": {
                        "runtime-versions": {"python": "3.12", "nodejs": "20"},
                        "commands": [
                            "echo 'Installing CDK CLI...'",
                            "npm install -g aws-cdk@latest",
                            "echo 'Installing Lambda dependencies...'",
                            "cd upload-service",
                            "pip install -r requirements.txt -t .",
                            "echo 'Installing CDK dependencies...'",
                            "cd cdk",
                            "pip install -r requirements.txt",
                        ],
                    },
                    "build": {
                        "commands": [
                            "echo 'Deploying backend via CDK...'",
                            "cdk deploy "
                            "-c appName=$APP_NAME "
                            "-c envName=$ENV_NAME "
                            "-c instanceId=$INSTANCE_ID "
                            "--require-approval never",
                        ],
                    },
                },
            }),
        )
        backend_build.add_to_role_policy(deploy_policy)

        backend_source_output = codepipeline.Artifact("BackendSource")
        backend_pipeline = codepipeline.Pipeline(
            self,
            "BackendPipeline",
            pipeline_name=f"{resource_prefix}-backend",
            stages=[
                codepipeline.StageProps(
                    stage_name="Source",
                    actions=[
                        actions.GitHubSourceAction(
                            action_name="GitHub",
                            owner=github_repo.split("/")[0],
                            repo=github_repo.split("/")[1],
                            branch=github_branch,
                            oauth_token=github_token,
                            output=backend_source_output,
                            trigger=actions.GitHubTrigger.NONE,
                        ),
                    ],
                ),
                codepipeline.StageProps(
                    stage_name="Deploy",
                    actions=[
                        actions.CodeBuildAction(
                            action_name="DeployBackend",
                            project=backend_build,
                            input=backend_source_output,
                        ),
                    ],
                ),
            ],
        )

        # =====================================================================
        # PIPELINE 3: Full Deploy (Backend first, then Frontend)
        # =====================================================================
        full_source_output = codepipeline.Artifact("FullSource")
        full_pipeline = codepipeline.Pipeline(
            self,
            "FullPipeline",
            pipeline_name=f"{resource_prefix}-full-deploy",
            stages=[
                codepipeline.StageProps(
                    stage_name="Source",
                    actions=[
                        actions.GitHubSourceAction(
                            action_name="GitHub",
                            owner=github_repo.split("/")[0],
                            repo=github_repo.split("/")[1],
                            branch=github_branch,
                            oauth_token=github_token,
                            output=full_source_output,
                            trigger=actions.GitHubTrigger.WEBHOOK,  # Auto-trigger on push to main
                        ),
                    ],
                ),
                codepipeline.StageProps(
                    stage_name="DeployBackend",
                    actions=[
                        actions.CodeBuildAction(
                            action_name="Backend",
                            project=backend_build,
                            input=full_source_output,
                        ),
                    ],
                ),
                codepipeline.StageProps(
                    stage_name="DeployFrontend",
                    actions=[
                        actions.CodeBuildAction(
                            action_name="Frontend",
                            project=frontend_build,
                            input=full_source_output,
                        ),
                    ],
                ),
            ],
        )

        # --- Outputs ---
        CfnOutput(self, "FrontendPipelineName", value=frontend_pipeline.pipeline_name)
        CfnOutput(self, "BackendPipelineName", value=backend_pipeline.pipeline_name)
        CfnOutput(self, "FullPipelineName", value=full_pipeline.pipeline_name)
