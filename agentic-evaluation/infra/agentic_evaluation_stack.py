"""CDK Stack for Agentic Evaluation runtime infrastructure.

Creates the AWS resources needed by the evaluation module at runtime:
- SSM Parameters for configuration (queue URLs, table name, bucket, topic ARN)
- SNS Topic for evaluation-specific error notifications
- CloudWatch Alarm monitoring the handoff DLQ message count

Resources created by OTHER stacks and referenced here (not recreated):
- SQS FIFO Queue (prescoach-dev-preparation-handoff.fifo) — created by preparation-workflow
- DynamoDB Table (prescoach-dev-kiro-submissions) — created by upload-service
- S3 Bucket (prescoach-dev-kiro-uploads) — created by upload-service
"""

from aws_cdk import (
    CfnOutput,
    Duration,
    Stack,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cw_actions,
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
        handoff_dlq_name = f"{app_name}-{env_name}-preparation-handoff-dlq.fifo"

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
        # Outputs
        # =====================================================================

        CfnOutput(self, "ErrorTopicArn", value=error_topic.topic_arn)
        CfnOutput(self, "DLQAlarmName", value=dlq_alarm.alarm_name)
        CfnOutput(self, "SSMPrefix", value=ssm_prefix)
