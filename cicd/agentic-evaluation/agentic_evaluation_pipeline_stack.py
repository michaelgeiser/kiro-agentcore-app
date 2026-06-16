"""CDK Stack defining CI/CD pipelines for the Agentic Evaluation module.

Pipeline 1 - Test: Runs property tests, unit tests, and integration tests
Pipeline 2 - Deploy: Installs deps, runs CDK deploy for agentic-evaluation infrastructure
Pipeline 3 - Full: Runs Tests first, then Deploy in sequence
"""

from aws_cdk import (
    CfnOutput,
    SecretValue,
    Stack,
    aws_codebuild as codebuild,
    aws_codepipeline as codepipeline,
    aws_codepipeline_actions as actions,
    aws_iam as iam,
)
from constructs import Construct


class AgenticEvaluationPipelineStack(Stack):
    """CI/CD pipelines for the Agentic Evaluation module.

    Deploys infrastructure for the evaluation layer: SQS FIFO queues,
    S3 result storage, SNS error notifications, and AgentCore agent
    registration.
    """

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
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        resource_prefix = f"{app_name}-{env_name}-{instance_id}"

        # --- GitHub Source (shared across all pipelines) ---
        github_token = SecretValue.secrets_manager("github-token")

        # --- Shared IAM Policy for CodeBuild ---
        deploy_policy = iam.PolicyStatement(
            actions=[
                # CloudFormation (CDK deploy)
                "cloudformation:*",
                # CDK asset publishing
                "sts:AssumeRole",
                # SQS (handoff queue, DLQ)
                "sqs:*",
                # SNS (error notifications, DLQ alerts)
                "sns:*",
                # DynamoDB (status table — shared with upload-service)
                "dynamodb:*",
                # S3 (evaluation results, reports, CDK assets)
                "s3:*",
                # SSM Parameter Store
                "ssm:*",
                # IAM (CDK creates roles)
                "iam:*",
                # CloudWatch Logs
                "logs:*",
                # Bedrock (AgentCore, model access)
                "bedrock:*",
                # ECR (CDK bootstrap)
                "ecr:*",
                # Lambda (if needed for future agent deployment)
                "lambda:*",
            ],
            resources=["*"],
        )

        # =====================================================================
        # PIPELINE 1: Test (property tests, unit tests, integration tests)
        # =====================================================================
        test_build = codebuild.PipelineProject(
            self,
            "EvalWorkflowTestBuild",
            project_name=f"{resource_prefix}-eval-workflow-test",
            environment=codebuild.BuildEnvironment(
                build_image=codebuild.LinuxBuildImage.STANDARD_7_0,
                compute_type=codebuild.ComputeType.SMALL,
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
                        "runtime-versions": {"python": "3.12"},
                        "commands": [
                            "echo 'Installing agentic-evaluation dependencies...'",
                            "cd $CODEBUILD_SRC_DIR/agentic-evaluation",
                            "pip install -r requirements.txt --no-cache-dir",
                            "pip install -r requirements-dev.txt --no-cache-dir",
                        ],
                    },
                    "build": {
                        "commands": [
                            "echo 'Running agentic-evaluation tests...'",
                            "cd $CODEBUILD_SRC_DIR/agentic-evaluation",
                            "python -m pytest tests/ -v --tb=short "
                            "--junitxml=test-results/results.xml",
                        ],
                    },
                },
                "reports": {
                    "test-results": {
                        "files": ["test-results/results.xml"],
                        "base-directory": "agentic-evaluation",
                        "file-format": "JUNITXML",
                    },
                },
            }),
        )

        test_source_output = codepipeline.Artifact("TestSource")
        test_pipeline = codepipeline.Pipeline(
            self,
            "EvalWorkflowTestPipeline",
            pipeline_name=f"{resource_prefix}-eval-workflow-test",
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
                            output=test_source_output,
                            trigger=actions.GitHubTrigger.NONE,
                        ),
                    ],
                ),
                codepipeline.StageProps(
                    stage_name="Test",
                    actions=[
                        actions.CodeBuildAction(
                            action_name="RunTests",
                            project=test_build,
                            input=test_source_output,
                        ),
                    ],
                ),
            ],
        )

        # =====================================================================
        # PIPELINE 2: Deploy (CDK deploy for agentic-evaluation infra)
        # =====================================================================
        deploy_build = codebuild.PipelineProject(
            self,
            "EvalWorkflowDeployBuild",
            project_name=f"{resource_prefix}-eval-workflow-deploy",
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
                            "echo 'Installing runtime dependencies...'",
                            "cd $CODEBUILD_SRC_DIR/agentic-evaluation",
                            "pip install -r requirements.txt --no-cache-dir",
                            "echo 'Installing CDK dependencies...'",
                            "pip install aws-cdk-lib>=2.100.0 constructs>=10.0.0 --no-cache-dir",
                        ],
                    },
                    "build": {
                        "commands": [
                            "echo 'Deploying agentic-evaluation infrastructure via CDK...'",
                            "cd $CODEBUILD_SRC_DIR/agentic-evaluation/infra",
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
        deploy_build.add_to_role_policy(deploy_policy)

        deploy_source_output = codepipeline.Artifact("DeploySource")
        deploy_pipeline = codepipeline.Pipeline(
            self,
            "EvalWorkflowDeployPipeline",
            pipeline_name=f"{resource_prefix}-eval-workflow-deploy",
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
                            output=deploy_source_output,
                            trigger=actions.GitHubTrigger.NONE,
                        ),
                    ],
                ),
                codepipeline.StageProps(
                    stage_name="Deploy",
                    actions=[
                        actions.CodeBuildAction(
                            action_name="DeployEvalWorkflow",
                            project=deploy_build,
                            input=deploy_source_output,
                        ),
                    ],
                ),
            ],
        )

        # =====================================================================
        # PIPELINE 3: Full (Test first, then Deploy)
        # =====================================================================
        full_source_output = codepipeline.Artifact("FullSource")
        full_pipeline = codepipeline.Pipeline(
            self,
            "EvalWorkflowFullPipeline",
            pipeline_name=f"{resource_prefix}-eval-workflow-full-deploy",
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
                    stage_name="Test",
                    actions=[
                        actions.CodeBuildAction(
                            action_name="RunTests",
                            project=test_build,
                            input=full_source_output,
                        ),
                    ],
                ),
                codepipeline.StageProps(
                    stage_name="Deploy",
                    actions=[
                        actions.CodeBuildAction(
                            action_name="DeployEvalWorkflow",
                            project=deploy_build,
                            input=full_source_output,
                        ),
                    ],
                ),
            ],
        )

        # --- Outputs ---
        CfnOutput(self, "TestPipelineName", value=test_pipeline.pipeline_name)
        CfnOutput(self, "DeployPipelineName", value=deploy_pipeline.pipeline_name)
        CfnOutput(self, "FullDeployPipelineName", value=full_pipeline.pipeline_name)
