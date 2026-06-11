"""CDK Stack for the Upload and Storage Service.

Provisions S3, DynamoDB, SQS, SNS, Lambda functions, HTTP API Gateway v2
with native JWT authorizer (Cognito), and CORS configuration.

Requirements: 1.1, 2.1, 2.2, 2.3, 3.1, 4.1, 5.1, 7.1, 8.1, 9.1, 9.2, 9.3, 9.4,
              11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.8
"""

import re

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
    Tags,
    aws_dynamodb as dynamodb,
    aws_iam as iam,
    aws_lambda as _lambda,
    aws_s3 as s3,
    aws_s3_notifications as s3n,
    aws_sns as sns,
    aws_sqs as sqs,
    aws_apigatewayv2 as apigwv2,
)
from constructs import Construct

from upload_service.cognito_construct import CognitoConstruct


class UploadServiceStack(Stack):
    """Main CDK stack for the Upload and Storage Service."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # --- Read CDK context parameters ---
        app_name: str = self.node.try_get_context("appName") or "prescoach"
        env_name: str = self.node.try_get_context("envName")
        instance_id: str = self.node.try_get_context("instanceId")

        if not env_name:
            raise ValueError("CDK context parameter 'envName' is required.")
        if not instance_id:
            raise ValueError("CDK context parameter 'instanceId' is required.")

        # --- Validate instanceId format ---
        if not re.match(r"^[a-z0-9][a-z0-9\-]{0,18}[a-z0-9]$", instance_id):
            if len(instance_id) < 2 or len(instance_id) > 20:
                raise ValueError(
                    f"instanceId must be 2-20 characters, got {len(instance_id)}."
                )
            raise ValueError(
                "instanceId must be lowercase alphanumeric characters and hyphens only."
            )

        # --- Construct resource prefix ---
        resource_prefix = f"{app_name}-{env_name}-{instance_id}"

        if len(resource_prefix) > 40:
            raise ValueError(
                f"Combined prefix '{resource_prefix}' exceeds 40 characters "
                f"({len(resource_prefix)} chars). Shorten appName, envName, or instanceId."
            )

        # --- Apply tags to all resources ---
        Tags.of(self).add("app", app_name)
        Tags.of(self).add("env", env_name)
        Tags.of(self).add("instance", instance_id)

        # --- Cognito (from construct 8.1) ---
        cognito = CognitoConstruct(
            self,
            "Cognito",
            resource_prefix=resource_prefix,
        )

        # --- S3 Bucket ---
        uploads_bucket = s3.Bucket(
            self,
            "UploadsBucket",
            bucket_name=f"{resource_prefix}-uploads",
            versioned=False,  # Versioning disabled for MVP
            removal_policy=RemovalPolicy.RETAIN,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            cors=[
                s3.CorsRule(
                    allowed_origins=["https://kiro.geiserai.com"],
                    allowed_methods=[s3.HttpMethods.PUT, s3.HttpMethods.POST, s3.HttpMethods.GET],
                    allowed_headers=["*"],
                    max_age=3600,
                )
            ],
        )

        # --- DynamoDB Table ---
        submissions_table = dynamodb.Table(
            self,
            "SubmissionsTable",
            table_name=f"{resource_prefix}-submissions",
            partition_key=dynamodb.Attribute(
                name="submission_id",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
        )

        submissions_table.add_global_secondary_index(
            index_name="user-uploads-index",
            partition_key=dynamodb.Attribute(
                name="user_id",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="upload_date",
                type=dynamodb.AttributeType.STRING,
            ),
        )

        # --- SQS Queues ---
        processing_dlq = sqs.Queue(
            self,
            "ProcessingDLQ",
            queue_name=f"{resource_prefix}-processing-dlq",
        )

        processing_queue = sqs.Queue(
            self,
            "ProcessingQueue",
            queue_name=f"{resource_prefix}-processing-queue",
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=3,
                queue=processing_dlq,
            ),
        )

        # --- SNS Topic ---
        errors_topic = sns.Topic(
            self,
            "ErrorsTopic",
            topic_name=f"{resource_prefix}-errors",
        )

        # --- Lambda Functions ---
        # Package src/ as the Lambda root. Handler paths use forward-slash notation.
        # All internal imports must NOT use "src." prefix (they're at the root).
        lambda_code = _lambda.Code.from_asset("../src")

        # Upload Lambda
        upload_lambda = _lambda.Function(
            self,
            "UploadLambda",
            function_name=f"{resource_prefix}-upload",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="handlers.upload.handler",
            code=lambda_code,
            environment={
                "S3_BUCKET_NAME": uploads_bucket.bucket_name,
                "DYNAMODB_TABLE_NAME": submissions_table.table_name,
                "SNS_TOPIC_ARN": errors_topic.topic_arn,
                "SQS_QUEUE_URL": processing_queue.queue_url,
            },
            timeout=Duration.seconds(30),
        )

        # Get Submissions Lambda
        get_submissions_lambda = _lambda.Function(
            self,
            "GetSubmissionsLambda",
            function_name=f"{resource_prefix}-get-submissions",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="handlers.get_submissions.handler",
            code=lambda_code,
            environment={
                "DYNAMODB_TABLE_NAME": submissions_table.table_name,
            },
            timeout=Duration.seconds(30),
        )

        # Confirm Upload Lambda
        confirm_upload_lambda = _lambda.Function(
            self,
            "ConfirmUploadLambda",
            function_name=f"{resource_prefix}-confirm-upload",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="handlers.confirm_upload.handler",
            code=lambda_code,
            environment={
                "DYNAMODB_TABLE_NAME": submissions_table.table_name,
                "SQS_QUEUE_URL": processing_queue.queue_url,
                "SNS_TOPIC_ARN": errors_topic.topic_arn,
            },
            timeout=Duration.seconds(30),
        )

        # --- IAM Permissions ---
        uploads_bucket.grant_read_write(upload_lambda)
        uploads_bucket.grant_read(confirm_upload_lambda)
        submissions_table.grant_read_write_data(upload_lambda)
        submissions_table.grant_read_data(get_submissions_lambda)
        submissions_table.grant_read_write_data(confirm_upload_lambda)
        processing_queue.grant_send_messages(upload_lambda)
        processing_queue.grant_send_messages(confirm_upload_lambda)
        errors_topic.grant_publish(upload_lambda)
        errors_topic.grant_publish(confirm_upload_lambda)

        # --- S3 Event Notification (PutObject on uploads/ prefix) ---
        uploads_bucket.add_event_notification(
            s3.EventType.OBJECT_CREATED_PUT,
            s3n.LambdaDestination(confirm_upload_lambda),
            s3.NotificationKeyFilter(prefix="uploads/"),
        )

        # --- HTTP API Gateway v2 ---
        http_api = apigwv2.CfnApi(
            self,
            "HttpApi",
            name=f"{resource_prefix}-api",
            protocol_type="HTTP",
            cors_configuration=apigwv2.CfnApi.CorsProperty(
                allow_origins=["https://kiro.geiserai.com"],
                allow_methods=["GET", "POST"],
                allow_headers=["Content-Type", "Authorization"],
                max_age=86400,  # 1 day in seconds
            ),
        )

        # Default stage with auto-deploy
        api_stage = apigwv2.CfnStage(
            self,
            "HttpApiStage",
            api_id=http_api.ref,
            stage_name="$default",
            auto_deploy=True,
        )

        # JWT Authorizer referencing Cognito User Pool
        jwt_authorizer = apigwv2.CfnAuthorizer(
            self,
            "JwtAuthorizer",
            api_id=http_api.ref,
            authorizer_type="JWT",
            name=f"{resource_prefix}-jwt-auth",
            identity_source=["$request.header.Authorization"],
            jwt_configuration=apigwv2.CfnAuthorizer.JWTConfigurationProperty(
                issuer=f"https://cognito-idp.{self.region}.amazonaws.com/{cognito.user_pool.user_pool_id}",
                audience=[cognito.user_pool_client.user_pool_client_id],
            ),
        )

        # --- Lambda Integrations ---
        upload_integration = apigwv2.CfnIntegration(
            self,
            "UploadIntegration",
            api_id=http_api.ref,
            integration_type="AWS_PROXY",
            integration_uri=upload_lambda.function_arn,
            payload_format_version="2.0",
        )

        get_submissions_integration = apigwv2.CfnIntegration(
            self,
            "GetSubmissionsIntegration",
            api_id=http_api.ref,
            integration_type="AWS_PROXY",
            integration_uri=get_submissions_lambda.function_arn,
            payload_format_version="2.0",
        )

        # --- Routes ---
        apigwv2.CfnRoute(
            self,
            "PostSubmissionsRoute",
            api_id=http_api.ref,
            route_key="POST /submissions",
            authorization_type="JWT",
            authorizer_id=jwt_authorizer.ref,
            target=f"integrations/{upload_integration.ref}",
        )

        apigwv2.CfnRoute(
            self,
            "GetSubmissionsRoute",
            api_id=http_api.ref,
            route_key="GET /submissions",
            authorization_type="JWT",
            authorizer_id=jwt_authorizer.ref,
            target=f"integrations/{get_submissions_integration.ref}",
        )

        # --- Grant API Gateway permission to invoke Lambdas ---
        upload_lambda.add_permission(
            "ApiGwInvokeUpload",
            principal=iam.ServicePrincipal("apigateway.amazonaws.com"),
            source_arn=f"arn:aws:execute-api:{self.region}:{self.account}:{http_api.ref}/*/*/submissions",
        )

        get_submissions_lambda.add_permission(
            "ApiGwInvokeGetSubmissions",
            principal=iam.ServicePrincipal("apigateway.amazonaws.com"),
            source_arn=f"arn:aws:execute-api:{self.region}:{self.account}:{http_api.ref}/*/*/submissions",
        )

        # --- Outputs ---
        CfnOutput(
            self,
            "ApiEndpoint",
            value=f"https://{http_api.ref}.execute-api.{self.region}.amazonaws.com",
            description="HTTP API Gateway endpoint URL",
        )
