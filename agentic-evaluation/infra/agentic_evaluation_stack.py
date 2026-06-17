"""CDK Stack for Agentic Evaluation runtime infrastructure.

Creates the AWS resources needed by the evaluation module at runtime:
- SSM Parameters for configuration (queue URLs, table name, bucket, topic ARN)
- SNS Topic for evaluation-specific error notifications
- CloudWatch Alarm monitoring the handoff DLQ message count
- ECS Cluster with Fargate Spot capacity for running evaluation tasks
- Lambda function to launch ECS tasks on demand (prevents duplicates)
- EventBridge rule to trigger task launch when messages arrive on the queue
- CloudWatch Log Group for ECS task output
- Docker image built and pushed automatically during cdk deploy

Resources created by OTHER stacks and referenced here (not recreated):
- SQS FIFO Queue (prescoach-dev-preparation-handoff.fifo) — created by preparation-workflow
- DynamoDB Table (prescoach-dev-kiro-submissions) — created by upload-service
- S3 Bucket (prescoach-dev-kiro-uploads) — created by upload-service

Networking: Uses the account's default VPC public subnets automatically.
No manual subnet/security group configuration required.
"""

import os
from pathlib import Path

from aws_cdk import (
    CfnOutput,
    Duration,
    Stack,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cw_actions,
    aws_ec2 as ec2,
    aws_ecr_assets as ecr_assets,
    aws_ecs as ecs,
    aws_events as events,
    aws_events_targets as targets,
    aws_iam as iam,
    aws_lambda as _lambda,
    aws_logs as logs,
    aws_sns as sns,
    aws_sqs as sqs,
    aws_ssm as ssm,
)
from constructs import Construct


class AgenticEvaluationStack(Stack):
    """Runtime infrastructure for the Agentic Evaluation module."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        app_name: str,
        env_name: str,
        instance_id: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        resource_prefix = f"{app_name}-{env_name}-{instance_id}"
        ssm_prefix = f"/{app_name}/{env_name}/agentic-evaluation"

        # =====================================================================
        # Reference existing resources (created by other stacks)
        # =====================================================================

        # The handoff FIFO queue created by the preparation-workflow stack
        handoff_queue_name = f"{app_name}-{env_name}-preparation-handoff.fifo"
        handoff_dlq_name = f"{app_name}-{env_name}-preparation-dlq-handoff.fifo"

        # DynamoDB table and S3 bucket created by upload-service
        submissions_table_name = f"{resource_prefix}-submissions"
        uploads_bucket_name = f"{resource_prefix}-uploads"

        # =====================================================================
        # SNS Topic: Evaluation Error Notifications
        # =====================================================================

        error_topic = sns.Topic(
            self,
            "EvaluationErrorTopic",
            topic_name=f"{resource_prefix}-evaluation-errors",
            display_name="Agentic Evaluation Error Notifications",
        )

        # =====================================================================
        # SSM Parameters: Runtime Configuration
        # =====================================================================

        params = {
            "sqs-queue-url": f"https://sqs.{self.region}.amazonaws.com/{self.account}/{handoff_queue_name}",
            "sqs-dlq-url": f"https://sqs.{self.region}.amazonaws.com/{self.account}/{handoff_dlq_name}",
            "dynamodb-table-name": submissions_table_name,
            "s3-bucket-name": uploads_bucket_name,
            "sns-topic-arn": error_topic.topic_arn,
            "dlq-threshold": "10",
            "retry-max-attempts": "3",
            "retry-base-delay-seconds": "1.0",
            "retry-backoff-multiplier": "2.0",
            "retry-max-delay-seconds": "30.0",
        }

        for key, value in params.items():
            ssm.StringParameter(
                self,
                f"Param-{key}",
                parameter_name=f"{ssm_prefix}/{key}",
                string_value=value,
                description=f"Agentic Evaluation config: {key}",
            )

        # =====================================================================
        # CloudWatch Alarm: DLQ Threshold Monitor
        # =====================================================================

        # Import the existing DLQ by name to create a metric
        dlq = sqs.Queue.from_queue_arn(
            self,
            "HandoffDLQ",
            queue_arn=f"arn:aws:sqs:{self.region}:{self.account}:{handoff_dlq_name}",
        )

        dlq_messages_metric = cloudwatch.Metric(
            namespace="AWS/SQS",
            metric_name="ApproximateNumberOfMessagesVisible",
            dimensions_map={"QueueName": handoff_dlq_name},
            period=Duration.minutes(1),
            statistic="Maximum",
        )

        dlq_alarm = cloudwatch.Alarm(
            self,
            "DLQThresholdAlarm",
            alarm_name=f"{resource_prefix}-eval-dlq-threshold",
            alarm_description=(
                "Fires when the agentic evaluation handoff DLQ has more than "
                "10 messages, indicating repeated processing failures."
            ),
            metric=dlq_messages_metric,
            threshold=10,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )

        # Send alarm notifications to the error topic
        dlq_alarm.add_alarm_action(cw_actions.SnsAction(error_topic))

        # =====================================================================
        # VPC: Look up the default VPC (no manual subnet config needed)
        # =====================================================================

        vpc = ec2.Vpc.from_lookup(
            self,
            "DefaultVPC",
            is_default=True,
        )

        # =====================================================================
        # Docker Image: Built and pushed automatically during cdk deploy
        # =====================================================================

        # Path to the agentic-evaluation directory containing the Dockerfile
        docker_context_path = str(
            Path(__file__).parent.parent.resolve()
        )

        docker_image_asset = ecr_assets.DockerImageAsset(
            self,
            "EvalDockerImage",
            directory=docker_context_path,
            platform=ecr_assets.Platform.LINUX_AMD64,
            exclude=["infra", "cdk.out", "tests", ".hypothesis", "__pycache__", ".venv"],
        )

        # =====================================================================
        # CloudWatch Log Group for ECS tasks
        # =====================================================================

        ecs_log_group = logs.LogGroup(
            self,
            "EvalECSLogGroup",
            log_group_name="/ecs/prescoach-dev-kiro-agentic-evaluation",
            retention=logs.RetentionDays.TWO_WEEKS,
        )

        # =====================================================================
        # ECS Cluster with Fargate Spot Capacity Provider
        # =====================================================================

        cluster = ecs.Cluster(
            self,
            "EvalCluster",
            cluster_name=f"{resource_prefix}-eval-cluster",
            vpc=vpc,
            enable_fargate_capacity_providers=True,
        )

        # =====================================================================
        # ECS Task Definition (Fargate Spot, 0.5 vCPU, 1 GB)
        # =====================================================================

        task_role = iam.Role(
            self,
            "EvalTaskRole",
            role_name=f"{resource_prefix}-eval-task-role",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            inline_policies={
                "EvalTaskPolicy": iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            actions=[
                                "bedrock:InvokeModel",
                                "bedrock:InvokeModelWithResponseStream",
                                "bedrock:Converse",
                                "bedrock:ConverseStream",
                                "aws-marketplace:ViewSubscriptions",
                                "aws-marketplace:Subscribe",
                                "sqs:*",
                                "s3:*",
                                "dynamodb:*",
                                "sns:*",
                                "ssm:GetParameter",
                                "ssm:GetParameters",
                                "ssm:GetParametersByPath",
                                "logs:*",
                            ],
                            resources=["*"],
                        ),
                    ]
                ),
            },
        )

        task_execution_role = iam.Role(
            self,
            "EvalTaskExecutionRole",
            role_name=f"{resource_prefix}-eval-task-exec-role",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AmazonECSTaskExecutionRolePolicy"
                ),
            ],
        )

        task_definition = ecs.FargateTaskDefinition(
            self,
            "EvalTaskDef",
            family=f"{resource_prefix}-eval-task",
            cpu=512,       # 0.5 vCPU
            memory_limit_mib=1024,  # 1 GB
            task_role=task_role,
            execution_role=task_execution_role,
        )

        # Construct the SQS queue URLs for environment variables
        sqs_queue_url = (
            f"https://sqs.{self.region}.amazonaws.com/"
            f"{self.account}/{handoff_queue_name}"
        )
        sqs_dlq_url = (
            f"https://sqs.{self.region}.amazonaws.com/"
            f"{self.account}/{handoff_dlq_name}"
        )

        task_definition.add_container(
            "eval-container",
            image=ecs.ContainerImage.from_docker_image_asset(docker_image_asset),
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix="eval",
                log_group=ecs_log_group,
            ),
            environment={
                "SQS_QUEUE_URL": sqs_queue_url,
                "SQS_DLQ_URL": sqs_dlq_url,
                "DYNAMODB_TABLE_NAME": submissions_table_name,
                "S3_BUCKET_NAME": uploads_bucket_name,
                "SNS_TOPIC_ARN": error_topic.topic_arn,
                "AWS_DEFAULT_REGION": self.region,
                "LOCAL_MODE": "true",
                "IDLE_TIMEOUT_MINUTES": "30",
                "MAX_CONCURRENT_EVALUATIONS": "5",
                "EVALUATION_MODEL_ID": "us.anthropic.claude-sonnet-4-6",
                "COACHING_SUPERVISOR_MODEL_ID": "us.anthropic.claude-sonnet-4-6",
            },
        )

        # =====================================================================
        # ECS Service (desired count 0 — scaled by EventBridge/Lambda)
        # =====================================================================

        ecs_service = ecs.FargateService(
            self,
            "EvalService",
            service_name=f"{resource_prefix}-eval-service",
            cluster=cluster,
            task_definition=task_definition,
            desired_count=0,
            capacity_provider_strategies=[
                ecs.CapacityProviderStrategy(
                    capacity_provider="FARGATE_SPOT",
                    weight=1,
                ),
            ],
            assign_public_ip=True,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PUBLIC,
            ),
        )

        # =====================================================================
        # Lambda: eval-task-launcher (prevents duplicate ECS tasks)
        # =====================================================================

        # Get public subnet IDs and create a security group for the tasks
        public_subnet_ids = ",".join(
            [subnet.subnet_id for subnet in vpc.public_subnets]
        )

        # Create a security group for the ECS tasks (allows all outbound)
        eval_sg = ec2.SecurityGroup(
            self,
            "EvalTaskSG",
            vpc=vpc,
            security_group_name=f"{resource_prefix}-eval-task-sg",
            description="Security group for agentic evaluation ECS tasks",
            allow_all_outbound=True,
        )

        launcher_lambda = _lambda.Function(
            self,
            "EvalTaskLauncherFn",
            function_name=f"{resource_prefix}-eval-task-launcher",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="index.handler",
            timeout=Duration.seconds(30),
            environment={
                "ECS_CLUSTER_ARN": cluster.cluster_arn,
                "TASK_DEFINITION_ARN": task_definition.task_definition_arn,
                "SUBNETS": public_subnet_ids,
                "SECURITY_GROUPS": eval_sg.security_group_id,
                "CONTAINER_NAME": "eval-container",
            },
            code=_lambda.Code.from_inline(
                'import boto3\n'
                'import os\n'
                'import json\n'
                '\n'
                'ecs = boto3.client("ecs")\n'
                '\n'
                'def handler(event, context):\n'
                '    cluster = os.environ["ECS_CLUSTER_ARN"]\n'
                '    task_def = os.environ["TASK_DEFINITION_ARN"]\n'
                '\n'
                '    # Check if a task is already running\n'
                '    running = ecs.list_tasks(\n'
                '        cluster=cluster,\n'
                '        desiredStatus="RUNNING",\n'
                '    )\n'
                '    if running.get("taskArns"):\n'
                '        print(f"Task already running: {running[\'taskArns\']}")\n'
                '        return {"launched": False, "reason": "task_already_running"}\n'
                '\n'
                '    # Launch a new task using capacity provider (not launchType)\n'
                '    response = ecs.run_task(\n'
                '        cluster=cluster,\n'
                '        taskDefinition=task_def,\n'
                '        count=1,\n'
                '        capacityProviderStrategy=[\n'
                '            {"capacityProvider": "FARGATE_SPOT", "weight": 1}\n'
                '        ],\n'
                '        networkConfiguration={\n'
                '            "awsvpcConfiguration": {\n'
                '                "assignPublicIp": "ENABLED",\n'
                '                "subnets": [s for s in os.environ.get("SUBNETS", "").split(",") if s],\n'
                '                "securityGroups": [s for s in os.environ.get("SECURITY_GROUPS", "").split(",") if s],\n'
                '            }\n'
                '        },\n'
                '    )\n'
                '    task_arns = [t["taskArn"] for t in response.get("tasks", [])]\n'
                '    print(f"Launched task(s): {task_arns}")\n'
                '    return {"launched": True, "taskArns": task_arns}\n'
            ),
        )

        # Grant the Lambda permission to list and run ECS tasks
        launcher_lambda.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "ecs:ListTasks",
                    "ecs:RunTask",
                    "ecs:DescribeTasks",
                ],
                resources=["*"],
            )
        )
        launcher_lambda.add_to_role_policy(
            iam.PolicyStatement(
                actions=["iam:PassRole"],
                resources=[
                    task_role.role_arn,
                    task_execution_role.role_arn,
                ],
            )
        )

        # =====================================================================
        # EventBridge Rule: Trigger task launcher when queue has messages
        # =====================================================================

        # CloudWatch Alarm triggers when ApproximateNumberOfMessagesVisible > 0
        handoff_queue_metric = cloudwatch.Metric(
            namespace="AWS/SQS",
            metric_name="ApproximateNumberOfMessagesVisible",
            dimensions_map={"QueueName": handoff_queue_name},
            period=Duration.minutes(1),
            statistic="Maximum",
        )

        queue_has_messages_alarm = cloudwatch.Alarm(
            self,
            "QueueHasMessagesAlarm",
            alarm_name=f"{resource_prefix}-eval-queue-has-messages",
            alarm_description=(
                "Fires when the handoff queue has messages waiting, "
                "triggering the ECS task launcher Lambda."
            ),
            metric=handoff_queue_metric,
            threshold=0,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )

        # EventBridge rule triggered by the alarm state change
        launch_rule = events.Rule(
            self,
            "EvalLaunchRule",
            rule_name=f"{resource_prefix}-eval-launch-on-messages",
            description=(
                "Triggers the eval-task-launcher Lambda when the handoff "
                "queue alarm transitions to ALARM state."
            ),
            event_pattern=events.EventPattern(
                source=["aws.cloudwatch"],
                detail_type=["CloudWatch Alarm State Change"],
                detail={
                    "alarmName": [queue_has_messages_alarm.alarm_name],
                    "state": {"value": ["ALARM"]},
                },
            ),
        )

        launch_rule.add_target(targets.LambdaFunction(launcher_lambda))

        # =====================================================================
        # Outputs
        # =====================================================================

        CfnOutput(self, "ErrorTopicArn", value=error_topic.topic_arn)
        CfnOutput(self, "DLQAlarmName", value=dlq_alarm.alarm_name)
        CfnOutput(self, "SSMPrefix", value=ssm_prefix)
        CfnOutput(self, "ECSClusterArn", value=cluster.cluster_arn)
        CfnOutput(self, "TaskDefinitionArn", value=task_definition.task_definition_arn)
        CfnOutput(self, "DockerImageUri", value=docker_image_asset.image_uri)
        CfnOutput(self, "ECSLogGroup", value=ecs_log_group.log_group_name)
        CfnOutput(self, "LauncherLambdaArn", value=launcher_lambda.function_arn)
        CfnOutput(self, "VpcId", value=vpc.vpc_id)
        CfnOutput(self, "PublicSubnets", value=public_subnet_ids)
