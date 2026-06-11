"""CDK Stack defining CI/CD pipelines for the Webapp and Upload Service.

Pipeline 1 - Webapp: Syncs webapp/ to S3 and invalidates CloudFront
Pipeline 2 - Upload Service: Installs deps, runs CDK deploy for upload-service
Pipeline 3 - Full: Runs Upload Service first, then Webapp in sequence
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


class WebappUploadPipelineStack(Stack):
    """CI/CD pipelines for the Webapp (frontend SPA) and Upload Service (backend)."""

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
        # PIPELINE 1: Webapp (frontend SPA)
        # =====================================================================
        webapp_build = codebuild.PipelineProject(
            self,
            "WebappBuild",
            project_name=f"{resource_prefix}-webapp-build",
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
                            "echo 'Deploying webapp to S3...'",
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
        webapp_build.add_to_role_policy(deploy_policy)

        webapp_source_output = codepipeline.Artifact("WebappSource")
        webapp_pipeline = codepipeline.Pipeline(
            self,
            "WebappPipeline",
            pipeline_name=f"{resource_prefix}-webapp",
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
                            output=webapp_source_output,
                            trigger=actions.GitHubTrigger.NONE,
                        ),
                    ],
                ),
                codepipeline.StageProps(
                    stage_name="Deploy",
                    actions=[
                        actions.CodeBuildAction(
                            action_name="DeployWebapp",
                            project=webapp_build,
                            input=webapp_source_output,
                        ),
                    ],
                ),
            ],
        )

        # =====================================================================
        # PIPELINE 2: Upload Service (backend)
        # =====================================================================
        upload_service_build = codebuild.PipelineProject(
            self,
            "UploadServiceBuild",
            project_name=f"{resource_prefix}-upload-service-build",
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
                            "pip install pydantic -t src/ --no-cache-dir",
                            "echo 'Installing CDK dependencies...'",
                            "cd cdk",
                            "pip install -r requirements.txt",
                        ],
                    },
                    "build": {
                        "commands": [
                            "echo 'Deploying upload-service via CDK...'",
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
        upload_service_build.add_to_role_policy(deploy_policy)

        upload_service_source_output = codepipeline.Artifact("UploadServiceSource")
        upload_service_pipeline = codepipeline.Pipeline(
            self,
            "UploadServicePipeline",
            pipeline_name=f"{resource_prefix}-upload-service",
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
                            output=upload_service_source_output,
                            trigger=actions.GitHubTrigger.NONE,
                        ),
                    ],
                ),
                codepipeline.StageProps(
                    stage_name="Deploy",
                    actions=[
                        actions.CodeBuildAction(
                            action_name="DeployUploadService",
                            project=upload_service_build,
                            input=upload_service_source_output,
                        ),
                    ],
                ),
            ],
        )

        # =====================================================================
        # PIPELINE 3: Full Deploy (Upload Service first, then Webapp)
        # =====================================================================
        full_source_output = codepipeline.Artifact("FullSource")
        full_pipeline = codepipeline.Pipeline(
            self,
            "FullPipeline",
            pipeline_name=f"{resource_prefix}-webapp-upload-full-deploy",
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
                            trigger=actions.GitHubTrigger.NONE,
                        ),
                    ],
                ),
                codepipeline.StageProps(
                    stage_name="DeployUploadService",
                    actions=[
                        actions.CodeBuildAction(
                            action_name="UploadService",
                            project=upload_service_build,
                            input=full_source_output,
                        ),
                    ],
                ),
                codepipeline.StageProps(
                    stage_name="DeployWebapp",
                    actions=[
                        actions.CodeBuildAction(
                            action_name="Webapp",
                            project=webapp_build,
                            input=full_source_output,
                        ),
                    ],
                ),
            ],
        )

        # --- Outputs ---
        CfnOutput(self, "WebappPipelineName", value=webapp_pipeline.pipeline_name)
        CfnOutput(self, "UploadServicePipelineName", value=upload_service_pipeline.pipeline_name)
        CfnOutput(self, "FullDeployPipelineName", value=full_pipeline.pipeline_name)
