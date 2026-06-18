"""CDK Stack for the Preparation Workflow infrastructure.

Defines all AWS resources for the Preparation Workflow:
- SQS Input Queue (Standard) with DLQ (maxReceiveCount=3)
- SQS Handoff Queue (FIFO) with DLQ
- SNS Topic for error notifications
- Lambda functions for each workflow handler
- Step Functions Standard Workflow state machine with full ASL definition
- SSM Parameter Store parameters
- EventBridge Pipe from SQS Input Queue to Step Functions
"""

import json

from aws_cdk import (
    Duration,
    RemovalPolicy,
    Stack,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_logs as logs,
    aws_pipes as pipes,
    aws_sns as sns,
    aws_sqs as sqs,
    aws_ssm as ssm,
    aws_stepfunctions as sfn,
)
from constructs import Construct


class PreparationWorkflowStack(Stack):
    """CDK Stack defining the Preparation Workflow infrastructure."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        env_name: str = "dev",
        instance_id: str = "kiro",
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.env_name = env_name
        self.instance_id = instance_id
        self.resource_prefix = f"prescoach-{env_name}-{instance_id}"
        self.ssm_prefix = f"/prescoach/{env_name}/preparation-workflow"

        # --- SQS Queues ---
        self._create_sqs_queues()

        # --- SNS Topic ---
        self._create_sns_topic()

        # --- Lambda Functions ---
        self._create_lambda_functions()

        # --- Step Functions State Machine ---
        self._create_state_machine()

        # --- SSM Parameters ---
        self._create_ssm_parameters()

        # --- EventBridge Pipe ---
        self._create_eventbridge_pipe()

    def _create_sqs_queues(self) -> None:
        """Create SQS Input Queue with DLQ and FIFO Handoff Queue with DLQ."""

        # DLQ for the Input Queue (Standard)
        self.dlq_input = sqs.Queue(
            self,
            "DLQInput",
            queue_name=f"prescoach-{self.env_name}-preparation-dlq-input",
            retention_period=Duration.days(14),
            removal_policy=RemovalPolicy.DESTROY,
        )

        # Input Queue (Standard) with DLQ
        self.input_queue = sqs.Queue(
            self,
            "InputQueue",
            queue_name=f"prescoach-{self.env_name}-preparation-input",
            visibility_timeout=Duration.minutes(15),
            retention_period=Duration.days(7),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=3,
                queue=self.dlq_input,
            ),
            removal_policy=RemovalPolicy.DESTROY,
        )

        # DLQ for the Handoff Queue (FIFO)
        self.dlq_handoff = sqs.Queue(
            self,
            "DLQHandoff",
            queue_name=f"prescoach-{self.env_name}-preparation-dlq-handoff.fifo",
            fifo=True,
            retention_period=Duration.days(14),
            removal_policy=RemovalPolicy.DESTROY,
        )

        # Handoff Queue (FIFO) with DLQ
        self.handoff_queue = sqs.Queue(
            self,
            "HandoffQueue",
            queue_name=f"prescoach-{self.env_name}-preparation-handoff.fifo",
            fifo=True,
            content_based_deduplication=True,
            visibility_timeout=Duration.minutes(5),
            retention_period=Duration.days(7),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=3,
                queue=self.dlq_handoff,
            ),
            removal_policy=RemovalPolicy.DESTROY,
        )

    def _create_sns_topic(self) -> None:
        """Create SNS Topic for error notifications."""

        self.error_topic = sns.Topic(
            self,
            "ErrorTopic",
            topic_name=f"prescoach-{self.env_name}-preparation-errors",
            display_name="Preparation Workflow Error Notifications",
        )

    def _create_lambda_functions(self) -> None:
        """Create Lambda functions for each workflow handler with least-privilege IAM."""

        # Shared Lambda execution role base policy
        lambda_base_policy = iam.ManagedPolicy.from_aws_managed_policy_name(
            "service-role/AWSLambdaBasicExecutionRole"
        )

        # --- load_config Lambda ---
        self.load_config_fn = self._create_lambda(
            "LoadConfig",
            handler="handlers.load_config.handler",
            description="Fetch SSM parameters for workflow configuration",
        )
        # SSM read permissions
        self.load_config_fn.add_to_role_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["ssm:GetParameter", "ssm:GetParametersByPath"],
                resources=[
                    f"arn:aws:ssm:{self.region}:{self.account}:parameter{self.ssm_prefix}/*"
                ],
            )
        )

        # --- parse_message Lambda ---
        self.parse_message_fn = self._create_lambda(
            "ParseMessage",
            handler="handlers.parse_message.handler",
            description="Parse and validate SQS message body",
        )

        # --- validate_format Lambda ---
        self.validate_format_fn = self._create_lambda(
            "ValidateFormat",
            handler="handlers.validate_format.handler",
            description="Validate file format against accepted types",
        )

        # --- extract_audio Lambda ---
        self.extract_audio_fn = self._create_lambda(
            "ExtractAudio",
            handler="services.audio_extraction.handler",
            description="Submit MediaConvert job for audio extraction",
            timeout=Duration.minutes(5),
        )
        # MediaConvert and S3 permissions
        self.extract_audio_fn.add_to_role_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "mediaconvert:CreateJob",
                    "mediaconvert:GetJob",
                    "mediaconvert:DescribeEndpoints",
                ],
                resources=["*"],
            )
        )
        self.extract_audio_fn.add_to_role_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["s3:GetObject", "s3:PutObject"],
                resources=[f"arn:aws:s3:::prescoach-{self.env_name}-*/*"],
            )
        )
        # MediaConvert needs a role to pass
        self.extract_audio_fn.add_to_role_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["iam:PassRole"],
                resources=[
                    f"arn:aws:iam::{self.account}:role/prescoach-{self.env_name}-mediaconvert-role"
                ],
            )
        )

        # --- transcribe_audio Lambda ---
        self.transcribe_audio_fn = self._create_lambda(
            "TranscribeAudio",
            handler="handlers.transcribe_audio.handler",
            description="Transcribe audio using Amazon Transcribe",
            timeout=Duration.minutes(6),
        )
        # Transcribe permissions
        self.transcribe_audio_fn.add_to_role_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["transcribe:*"],
                resources=["*"],
            )
        )
        # S3 read/write for transcription input and output
        self.transcribe_audio_fn.add_to_role_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["s3:GetObject", "s3:PutObject"],
                resources=[f"arn:aws:s3:::prescoach-{self.env_name}-*/*"],
            )
        )

        # --- chunk_audio Lambda ---
        # Uses pydub + ffmpeg for actual audio splitting.
        # ffmpeg static binary is bundled in a layer built during CDK deploy.
        ffmpeg_layer = lambda_.LayerVersion(
            self,
            "FfmpegLayer",
            code=lambda_.Code.from_asset("../ffmpeg-layer"),
            compatible_runtimes=[lambda_.Runtime.PYTHON_3_12],
            description="Static ffmpeg/ffprobe binaries for audio processing",
        )

        self.chunk_audio_fn = self._create_lambda(
            "ChunkAudio",
            handler="services.chunking.handler",
            description="Divide audio into chunks and upload to S3",
            timeout=Duration.minutes(5),
            memory_size=1024,
        )
        self.chunk_audio_fn.add_layers(ffmpeg_layer)
        # Add ffmpeg binary path to environment (layer extracts to /opt)
        self.chunk_audio_fn.add_environment(
            "PATH", "/opt/bin:/var/lang/bin:/usr/local/bin:/usr/bin:/bin"
        )
        # S3 read/write for audio chunks
        self.chunk_audio_fn.add_to_role_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["s3:GetObject", "s3:PutObject"],
                resources=[f"arn:aws:s3:::prescoach-{self.env_name}-*/*"],
            )
        )

        # --- create_embedding Lambda ---
        self.create_embedding_fn = self._create_lambda(
            "CreateEmbedding",
            handler="services.embedding.handler",
            description="Invoke Bedrock for embedding creation",
            timeout=Duration.minutes(5),
            memory_size=512,
        )
        # Bedrock invoke permissions
        self.create_embedding_fn.add_to_role_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "bedrock:InvokeModel",
                ],
                resources=[
                    f"arn:aws:bedrock:{self.region}::foundation-model/*",
                ],
            )
        )
        # S3 read for audio chunks
        self.create_embedding_fn.add_to_role_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["s3:GetObject", "s3:ListBucket"],
                resources=[
                    f"arn:aws:s3:::prescoach-{self.env_name}-*",
                    f"arn:aws:s3:::prescoach-{self.env_name}-*/*",
                ],
            )
        )

        # --- store_vectors Lambda ---
        self.store_vectors_fn = self._create_lambda(
            "StoreVectors",
            handler="services.vector_store.handler",
            description="Write embeddings to vector store",
            timeout=Duration.minutes(2),
        )
        # S3 write for vector storage (S3-based store option)
        self.store_vectors_fn.add_to_role_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["s3:PutObject", "s3:GetObject"],
                resources=[f"arn:aws:s3:::prescoach-{self.env_name}-*/*"],
            )
        )

        # --- publish_handoff Lambda ---
        self.publish_handoff_fn = self._create_lambda(
            "PublishHandoff",
            handler="handlers.publish_handoff.handler",
            description="Publish handoff message to FIFO SQS queue",
        )
        # Add HANDOFF_QUEUE_URL environment variable
        self.publish_handoff_fn.add_environment(
            "HANDOFF_QUEUE_URL", self.handoff_queue.queue_url
        )
        # Add eval task launcher function name for immediate trigger
        eval_launcher_fn_name = f"prescoach-{self.env_name}-{self.instance_id}-eval-task-launcher"
        self.publish_handoff_fn.add_environment(
            "EVAL_TASK_LAUNCHER_FN", eval_launcher_fn_name
        )
        # SQS send permission to handoff queue
        self.handoff_queue.grant_send_messages(self.publish_handoff_fn)
        # Permission to invoke the eval task launcher Lambda
        self.publish_handoff_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["lambda:InvokeFunction"],
                resources=[
                    f"arn:aws:lambda:{self.region}:{self.account}:function:{eval_launcher_fn_name}"
                ],
            )
        )

        # --- handle_failure Lambda ---
        self.handle_failure_fn = self._create_lambda(
            "HandleFailure",
            handler="handlers.handle_failure.handler",
            description="Handle workflow failures: update DynamoDB, publish SNS, route to DLQ",
        )
        # Add environment variables for DLQ URLs and SNS topic
        self.handle_failure_fn.add_environment(
            "DLQ_INPUT_URL", self.dlq_input.queue_url
        )
        self.handle_failure_fn.add_environment(
            "DLQ_HANDOFF_URL", self.dlq_handoff.queue_url
        )
        self.handle_failure_fn.add_environment(
            "SNS_TOPIC_ARN", self.error_topic.topic_arn
        )
        self.handle_failure_fn.add_environment(
            "DYNAMODB_TABLE_NAME", f"{self.resource_prefix}-submissions"
        )
        # DynamoDB update permissions
        self.handle_failure_fn.add_to_role_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["dynamodb:UpdateItem"],
                resources=[
                    f"arn:aws:dynamodb:{self.region}:{self.account}:table/{self.resource_prefix}-submissions"
                ],
            )
        )
        # SNS publish permission
        self.error_topic.grant_publish(self.handle_failure_fn)
        # SQS send to DLQs
        self.dlq_input.grant_send_messages(self.handle_failure_fn)
        self.dlq_handoff.grant_send_messages(self.handle_failure_fn)

    def _create_lambda(
        self,
        id: str,
        handler: str,
        description: str,
        timeout: Duration = Duration.seconds(60),
        memory_size: int = 256,
    ) -> lambda_.Function:
        """Create a Lambda function with standard configuration."""

        return lambda_.Function(
            self,
            id,
            function_name=f"prescoach-{self.env_name}-prep-{id.lower().replace(' ', '-')}",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler=handler,
            code=lambda_.Code.from_asset("../src"),
            timeout=timeout,
            memory_size=memory_size,
            description=description,
            environment={
                "ENV_NAME": self.env_name,
                "SSM_PREFIX": self.ssm_prefix,
            },
            log_retention=logs.RetentionDays.TWO_WEEKS,
        )

    def _build_state_machine_definition(self) -> dict:
        """Build the full ASL (Amazon States Language) definition for the Preparation Workflow.

        Flow:
          LoadConfig → ParseMessage → UpdateStatusProcessing → ValidateFileFormat → CheckVideoFlag
            → [Audio/embed] → ChunkAudio → CreateEmbeddings (Map) → StoreVectors → PublishHandoff → UpdateStatusCompleted
            → [Video + enabled/extract_audio] → ExtractAudio → ChunkAudio → ...
            → [Video + disabled/fail] → HandleFailure
            → [Invalid format] → HandleFailure
          All task states have Catch → HandleFailure
        """

        # Common retry configuration for Lambda-invoked tasks
        # Only retry recoverable errors (throttling, transient failures)
        lambda_retry = [
            {
                "ErrorEquals": [
                    "Lambda.ServiceException",
                    "Lambda.AWSLambdaException",
                    "Lambda.TooManyRequestsException",
                    "States.Timeout",
                ],
                "IntervalSeconds": 2,
                "BackoffRate": 2.0,
                "MaxAttempts": 3,
                "JitterStrategy": "FULL",
            }
        ]

        # Retry for MediaConvert (longer initial interval, only transient errors)
        mediaconvert_retry = [
            {
                "ErrorEquals": [
                    "Lambda.ServiceException",
                    "Lambda.AWSLambdaException",
                    "Lambda.TooManyRequestsException",
                    "States.Timeout",
                ],
                "IntervalSeconds": 30,
                "BackoffRate": 2.0,
                "MaxAttempts": 3,
                "JitterStrategy": "FULL",
            }
        ]

        # Retry for Bedrock embedding calls (only throttling/transient)
        bedrock_retry = [
            {
                "ErrorEquals": [
                    "Lambda.ServiceException",
                    "Lambda.AWSLambdaException",
                    "Lambda.TooManyRequestsException",
                    "States.Timeout",
                ],
                "IntervalSeconds": 5,
                "BackoffRate": 2.0,
                "MaxAttempts": 3,
                "JitterStrategy": "FULL",
            }
        ]

        # Retry for DynamoDB operations (only transient/throttling)
        dynamodb_retry = [
            {
                "ErrorEquals": [
                    "DynamoDB.ProvisionedThroughputExceededException",
                    "DynamoDB.ThrottlingException",
                    "DynamoDB.InternalServerError",
                    "States.Timeout",
                ],
                "IntervalSeconds": 1,
                "BackoffRate": 2.0,
                "MaxAttempts": 3,
                "JitterStrategy": "FULL",
            }
        ]

        # Common catch configuration routing errors to HandleFailure
        common_catch = [
            {
                "ErrorEquals": ["States.ALL"],
                "Next": "HandleFailure",
                "ResultPath": "$.error_info",
            }
        ]

        definition = {
            "Comment": "Preparation Workflow - Standard Workflow for audio/video processing pipeline",
            "StartAt": "UnwrapInput",
            "States": {
                "UnwrapInput": {
                    "Type": "Pass",
                    "Comment": "EventBridge Pipe sends SQS messages as an array. Extract the first element.",
                    "InputPath": "$[0]",
                    "Next": "LoadConfig",
                },
                "LoadConfig": {
                    "Type": "Task",
                    "Resource": "arn:aws:states:::lambda:invoke",
                    "Parameters": {
                        "FunctionName": self.load_config_fn.function_arn,
                        "Payload.$": "$",
                    },
                    "ResultPath": "$.config",
                    "ResultSelector": {
                        "value.$": "$.Payload",
                    },
                    "Retry": lambda_retry,
                    "Catch": common_catch,
                    "Next": "ParseMessage",
                },
                "ParseMessage": {
                    "Type": "Task",
                    "Resource": "arn:aws:states:::lambda:invoke",
                    "Parameters": {
                        "FunctionName": self.parse_message_fn.function_arn,
                        "Payload": {
                            "message_body.$": "$.body",
                        },
                    },
                    "ResultPath": "$.parsed_message",
                    "ResultSelector": {
                        "value.$": "$.Payload",
                    },
                    "Retry": lambda_retry,
                    "Catch": common_catch,
                    "Next": "UpdateStatusProcessing",
                },
                "UpdateStatusProcessing": {
                    "Type": "Task",
                    "Resource": "arn:aws:states:::dynamodb:updateItem",
                    "Parameters": {
                        "TableName": f"{self.resource_prefix}-submissions",
                        "Key": {
                            "submission_id": {
                                "S.$": "$.parsed_message.value.message.submission_id",
                            },
                        },
                        "UpdateExpression": "SET processing_status = :status",
                        "ExpressionAttributeValues": {
                            ":status": {"S": "Processing"},
                        },
                    },
                    "ResultPath": "$.dynamodb_update_processing",
                    "Retry": dynamodb_retry,
                    "Catch": common_catch,
                    "Next": "ValidateFileFormat",
                },
                "ValidateFileFormat": {
                    "Type": "Task",
                    "Resource": "arn:aws:states:::lambda:invoke",
                    "Parameters": {
                        "FunctionName": self.validate_format_fn.function_arn,
                        "Payload": {
                            "original_file_name.$": "$.parsed_message.value.message.original_file_name",
                            "video_processing_enabled.$": "$.config.value.video_processing_enabled",
                        },
                    },
                    "ResultPath": "$.validation_result",
                    "ResultSelector": {
                        "value.$": "$.Payload",
                    },
                    "Retry": lambda_retry,
                    "Catch": common_catch,
                    "Next": "CheckVideoFlag",
                },
                "CheckVideoFlag": {
                    "Type": "Choice",
                    "Choices": [
                        {
                            "Variable": "$.validation_result.value.decision",
                            "StringEquals": "embed",
                            "Next": "TranscribeAudio",
                        },
                        {
                            "Variable": "$.validation_result.value.decision",
                            "StringEquals": "extract_audio",
                            "Next": "ExtractAudio",
                        },
                        {
                            "Variable": "$.validation_result.value.decision",
                            "StringEquals": "fail",
                            "Next": "HandleFailure",
                        },
                    ],
                    "Default": "HandleFailure",
                },
                "ExtractAudio": {
                    "Type": "Task",
                    "Resource": "arn:aws:states:::lambda:invoke",
                    "Parameters": {
                        "FunctionName": self.extract_audio_fn.function_arn,
                        "Payload": {
                            "s3_bucket.$": "$.parsed_message.value.message.s3_bucket",
                            "s3_file_key.$": "$.parsed_message.value.message.s3_file_key",
                            "user_id.$": "$.parsed_message.value.message.user_id",
                            "submission_id.$": "$.parsed_message.value.message.submission_id",
                            "config.$": "$.config.value",
                        },
                    },
                    "ResultPath": "$.extraction_result",
                    "ResultSelector": {
                        "value.$": "$.Payload",
                    },
                    "Retry": mediaconvert_retry,
                    "Catch": common_catch,
                    "Next": "TranscribeAudio",
                },
                "TranscribeAudio": {
                    "Type": "Task",
                    "Resource": "arn:aws:states:::lambda:invoke",
                    "Parameters": {
                        "FunctionName": self.transcribe_audio_fn.function_arn,
                        "Payload": {
                            "submission_id.$": "$.parsed_message.value.message.submission_id",
                            "s3_bucket.$": "$.parsed_message.value.message.s3_bucket",
                            "s3_file_key.$": "$.parsed_message.value.message.s3_file_key",
                            "config.$": "$.config.value",
                        },
                    },
                    "ResultPath": "$.transcribe_result",
                    "ResultSelector": {
                        "value.$": "$.Payload",
                    },
                    "Retry": lambda_retry,
                    "Catch": common_catch,
                    "Next": "CheckEmbeddingsEnabled",
                },
                "CheckEmbeddingsEnabled": {
                    "Type": "Choice",
                    "Choices": [
                        {
                            "Variable": "$.config.value.embeddings_enabled",
                            "BooleanEquals": True,
                            "Next": "ChunkAudio",
                        },
                    ],
                    "Default": "SetDefaultsForSkippedEmbeddings",
                },
                "SetDefaultsForSkippedEmbeddings": {
                    "Type": "Pass",
                    "Comment": "Set empty defaults for store_result and chunks when embeddings are disabled",
                    "Result": {
                        "value": {
                            "vector_store_location": "",
                            "chunk_count": 0,
                        }
                    },
                    "ResultPath": "$.store_result",
                    "Next": "SetDefaultChunks",
                },
                "SetDefaultChunks": {
                    "Type": "Pass",
                    "Result": {
                        "value": {
                            "chunk_count": 0,
                        }
                    },
                    "ResultPath": "$.chunks",
                    "Next": "PublishHandoff",
                },
                "ChunkAudio": {
                    "Type": "Task",
                    "Resource": "arn:aws:states:::lambda:invoke",
                    "Parameters": {
                        "FunctionName": self.chunk_audio_fn.function_arn,
                        "Payload": {
                            "s3_bucket.$": "$.parsed_message.value.message.s3_bucket",
                            "s3_file_key.$": "$.parsed_message.value.message.s3_file_key",
                            "user_id.$": "$.parsed_message.value.message.user_id",
                            "submission_id.$": "$.parsed_message.value.message.submission_id",
                            "config.$": "$.config.value",
                        },
                    },
                    "ResultPath": "$.chunks",
                    "ResultSelector": {
                        "value.$": "$.Payload",
                    },
                    "Retry": lambda_retry,
                    "Catch": common_catch,
                    "Next": "CreateEmbeddings",
                },
                "CreateEmbeddings": {
                    "Type": "Map",
                    "ItemsPath": "$.chunks.value.chunks",
                    "MaxConcurrency": 10,
                    "Parameters": {
                        "chunk.$": "$$.Map.Item.Value",
                        "config.$": "$.config.value",
                        "submission_id.$": "$.parsed_message.value.message.submission_id",
                        "user_id.$": "$.parsed_message.value.message.user_id",
                    },
                    "Iterator": {
                        "StartAt": "ProcessChunkEmbedding",
                        "States": {
                            "ProcessChunkEmbedding": {
                                "Type": "Task",
                                "Resource": "arn:aws:states:::lambda:invoke",
                                "Parameters": {
                                    "FunctionName": self.create_embedding_fn.function_arn,
                                    "Payload.$": "$",
                                },
                                "ResultSelector": {
                                    "value.$": "$.Payload",
                                },
                                "Retry": bedrock_retry,
                                "End": True,
                            },
                        },
                    },
                    "ResultPath": "$.embeddings",
                    "Catch": common_catch,
                    "Next": "StoreVectors",
                },
                "StoreVectors": {
                    "Type": "Task",
                    "Resource": "arn:aws:states:::lambda:invoke",
                    "Parameters": {
                        "FunctionName": self.store_vectors_fn.function_arn,
                        "Payload": {
                            "embeddings.$": "$.embeddings",
                            "submission_id.$": "$.parsed_message.value.message.submission_id",
                            "user_id.$": "$.parsed_message.value.message.user_id",
                            "config.$": "$.config.value",
                        },
                    },
                    "ResultPath": "$.store_result",
                    "ResultSelector": {
                        "value.$": "$.Payload",
                    },
                    "Retry": lambda_retry,
                    "Catch": common_catch,
                    "Next": "PublishHandoff",
                },
                "PublishHandoff": {
                    "Type": "Task",
                    "Resource": "arn:aws:states:::lambda:invoke",
                    "Parameters": {
                        "FunctionName": self.publish_handoff_fn.function_arn,
                        "Payload": {
                            "submission_id.$": "$.parsed_message.value.message.submission_id",
                            "user_id.$": "$.parsed_message.value.message.user_id",
                            "s3_file_key.$": "$.parsed_message.value.message.s3_file_key",
                            "presentation_title.$": "$.parsed_message.value.message.presentation_title",
                            "transcript_result.$": "$.transcribe_result.value",
                            "store_result.$": "$.store_result.value",
                            "chunks.$": "$.chunks.value",
                            "config.$": "$.config.value",
                        },
                    },
                    "ResultPath": "$.handoff_result",
                    "ResultSelector": {
                        "value.$": "$.Payload",
                    },
                    "Retry": lambda_retry,
                    "Catch": common_catch,
                    "Next": "UpdateStatusCompleted",
                },
                "UpdateStatusCompleted": {
                    "Type": "Task",
                    "Resource": "arn:aws:states:::dynamodb:updateItem",
                    "Parameters": {
                        "TableName": f"{self.resource_prefix}-submissions",
                        "Key": {
                            "submission_id": {
                                "S.$": "$.parsed_message.value.message.submission_id",
                            },
                        },
                        "UpdateExpression": "SET processing_status = :status",
                        "ExpressionAttributeValues": {
                            ":status": {"S": "Completed"},
                        },
                    },
                    "ResultPath": "$.dynamodb_update_completed",
                    "Retry": dynamodb_retry,
                    "Catch": common_catch,
                    "End": True,
                },
                "HandleFailure": {
                    "Type": "Task",
                    "Resource": "arn:aws:states:::lambda:invoke",
                    "Parameters": {
                        "FunctionName": self.handle_failure_fn.function_arn,
                        "Payload": {
                            "execution_input.$": "$",
                            "error_info.$": "$.error_info",
                        },
                    },
                    "ResultSelector": {
                        "value.$": "$.Payload",
                    },
                    "End": True,
                },
            },
        }

        return definition

    def _create_state_machine(self) -> None:
        """Create Step Functions Standard Workflow state machine."""

        # Build the full ASL definition
        state_machine_definition = self._build_state_machine_definition()

        # IAM role for the state machine
        self.state_machine_role = iam.Role(
            self,
            "StateMachineRole",
            assumed_by=iam.ServicePrincipal("states.amazonaws.com"),
            description="Execution role for Preparation Workflow state machine",
        )

        # Lambda invoke permissions for all handler functions
        self.state_machine_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["lambda:InvokeFunction"],
                resources=[
                    self.load_config_fn.function_arn,
                    self.parse_message_fn.function_arn,
                    self.validate_format_fn.function_arn,
                    self.extract_audio_fn.function_arn,
                    self.transcribe_audio_fn.function_arn,
                    self.chunk_audio_fn.function_arn,
                    self.create_embedding_fn.function_arn,
                    self.store_vectors_fn.function_arn,
                    self.publish_handoff_fn.function_arn,
                    self.handle_failure_fn.function_arn,
                ],
            )
        )

        # DynamoDB permissions for direct SDK integrations
        self.state_machine_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["dynamodb:UpdateItem"],
                resources=[
                    f"arn:aws:dynamodb:{self.region}:{self.account}:table/{self.resource_prefix}-submissions"
                ],
            )
        )

        # CloudWatch Logs for state machine execution logging
        self.state_machine_log_group = logs.LogGroup(
            self,
            "StateMachineLogGroup",
            log_group_name=f"/aws/stepfunctions/prescoach-{self.env_name}-preparation-workflow",
            retention=logs.RetentionDays.TWO_WEEKS,
            removal_policy=RemovalPolicy.DESTROY,
        )

        self.state_machine_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "logs:CreateLogDelivery",
                    "logs:GetLogDelivery",
                    "logs:UpdateLogDelivery",
                    "logs:DeleteLogDelivery",
                    "logs:ListLogDeliveries",
                    "logs:PutResourcePolicy",
                    "logs:DescribeResourcePolicies",
                    "logs:DescribeLogGroups",
                ],
                resources=["*"],
            )
        )

        # State machine (Standard Workflow)
        self.state_machine = sfn.CfnStateMachine(
            self,
            "PreparationWorkflow",
            state_machine_name=f"prescoach-{self.env_name}-preparation-workflow",
            state_machine_type="STANDARD",
            definition_string=json.dumps(state_machine_definition),
            role_arn=self.state_machine_role.role_arn,
            logging_configuration=sfn.CfnStateMachine.LoggingConfigurationProperty(
                destinations=[
                    sfn.CfnStateMachine.LogDestinationProperty(
                        cloud_watch_logs_log_group=sfn.CfnStateMachine.CloudWatchLogsLogGroupProperty(
                            log_group_arn=self.state_machine_log_group.log_group_arn,
                        )
                    )
                ],
                include_execution_data=True,
                level="ALL",
            ),
        )

    def _create_ssm_parameters(self) -> None:
        """Create SSM Parameter Store parameters under /prescoach/{env}/preparation-workflow/."""

        parameters = {
            "embedding-model-id": {
                "value": "amazon.nova-2-multimodal-embeddings-v1:0",
                "description": "Bedrock model identifier for embedding creation",
            },
            "chunk-size-seconds": {
                "value": "30",
                "description": "Audio chunk duration in seconds",
            },
            "chunk-overlap-seconds": {
                "value": "5",
                "description": "Overlap between consecutive audio chunks in seconds",
            },
            "max-retry-attempts": {
                "value": "3",
                "description": "Maximum retry count for service calls",
            },
            "video-processing-enabled": {
                "value": "false",
                "description": "Feature flag for video file processing",
            },
            "vector-store-endpoint": {
                "value": f"prescoach-{self.env_name}-kiro-uploads",
                "description": "Vector store S3 bucket name",
            },
            "vector-store-type": {
                "value": "s3",
                "description": "Vector store type (s3, opensearch, etc.)",
            },
            "batch-size": {
                "value": "10",
                "description": "Number of chunks per batch embedding call",
            },
            "batch-processing-enabled": {
                "value": "false",
                "description": "Feature flag for batch embedding processing",
            },
            "embeddings-enabled": {
                "value": "false",
                "description": "Feature flag to enable/disable audio embedding creation",
            },
        }

        self.ssm_parameters = {}
        for param_name, config in parameters.items():
            self.ssm_parameters[param_name] = ssm.StringParameter(
                self,
                f"Param{param_name.replace('-', '').title()}",
                parameter_name=f"{self.ssm_prefix}/{param_name}",
                string_value=config["value"],
                description=config["description"],
            )

    def _create_eventbridge_pipe(self) -> None:
        """Create EventBridge Pipe from SQS Input Queue to Step Functions."""

        # IAM role for the EventBridge Pipe
        pipe_role = iam.Role(
            self,
            "PipeRole",
            assumed_by=iam.ServicePrincipal("pipes.amazonaws.com"),
            description="Execution role for EventBridge Pipe (SQS to Step Functions)",
        )

        # Allow pipe to read from SQS Input Queue
        pipe_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "sqs:ReceiveMessage",
                    "sqs:DeleteMessage",
                    "sqs:GetQueueAttributes",
                ],
                resources=[self.input_queue.queue_arn],
            )
        )

        # Allow pipe to start Step Functions execution
        pipe_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["states:StartExecution"],
                resources=[self.state_machine.attr_arn],
            )
        )

        # EventBridge Pipe: SQS Input Queue → Step Functions
        # The pipe sends SQS messages as an array to Step Functions.
        # The state machine's first state (UnwrapInput) extracts the first element.
        self.pipe = pipes.CfnPipe(
            self,
            "InputToStepFunctionsPipe",
            name=f"prescoach-{self.env_name}-prep-input-to-sfn",
            role_arn=pipe_role.role_arn,
            source=self.input_queue.queue_arn,
            source_parameters=pipes.CfnPipe.PipeSourceParametersProperty(
                sqs_queue_parameters=pipes.CfnPipe.PipeSourceSqsQueueParametersProperty(
                    batch_size=1,
                    maximum_batching_window_in_seconds=0,
                ),
            ),
            target=self.state_machine.attr_arn,
            target_parameters=pipes.CfnPipe.PipeTargetParametersProperty(
                step_function_state_machine_parameters=pipes.CfnPipe.PipeTargetStateMachineParametersProperty(
                    invocation_type="FIRE_AND_FORGET",
                ),
            ),
        )
