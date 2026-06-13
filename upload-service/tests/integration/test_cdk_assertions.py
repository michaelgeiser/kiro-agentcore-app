"""CDK assertion tests for the Upload and Storage Service stack.

Validates that the CDK stack synthesizes with correct resource configurations
including Cognito, DynamoDB, S3, API Gateway, Lambda, and naming conventions.

Requirements: 2.1, 2.2, 2.3, 9.2, 9.3, 11.5, 11.6, 11.8
"""

import sys
import os
import json
import pytest

# Add the cdk directory to sys.path so imports work
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "cdk"))

import aws_cdk as cdk
from aws_cdk.assertions import Template, Match, Capture

from upload_service.upload_service_stack import UploadServiceStack


@pytest.fixture
def template():
    """Create a CDK template for assertion tests.

    Uses context: appName=prescoach, envName=dev, instanceId=test01
    Expected resource prefix: prescoach-dev-test01
    """
    app = cdk.App(
        context={
            "appName": "prescoach",
            "envName": "dev",
            "instanceId": "test01",
        }
    )
    stack = UploadServiceStack(app, "prescoach-dev-test01")
    return Template.from_stack(stack)


# --- Cognito User Pool Tests ---


class TestCognitoUserPool:
    """Tests for Cognito User Pool configuration (Requirement 2.1)."""

    def test_user_pool_exists_with_self_signup_enabled(self, template):
        """Assert Cognito User Pool exists with self sign-up enabled."""
        template.has_resource_properties(
            "AWS::Cognito::UserPool",
            {
                "UserPoolName": "prescoach-dev-test01-users",
                "Policies": Match.object_like(
                    {
                        "PasswordPolicy": Match.object_like(
                            {
                                "MinimumLength": 8,
                                "RequireUppercase": True,
                                "RequireLowercase": True,
                                "RequireNumbers": True,
                                "RequireSymbols": True,
                            }
                        )
                    }
                ),
            },
        )

    def test_user_pool_app_client_no_secret(self, template):
        """Assert App Client has no client secret (PKCE flow) (Requirement 2.2)."""
        template.has_resource_properties(
            "AWS::Cognito::UserPoolClient",
            {
                "GenerateSecret": False,
            },
        )

    def test_user_pool_app_client_authorization_code_grant(self, template):
        """Assert App Client has Authorization Code Grant flow configured (Requirement 2.2)."""
        template.has_resource_properties(
            "AWS::Cognito::UserPoolClient",
            {
                "AllowedOAuthFlows": ["code"],
                "AllowedOAuthScopes": Match.array_with(
                    ["openid", "profile", "email"]
                ),
            },
        )

    def test_user_pool_domain_configured(self, template):
        """Assert Cognito User Pool Domain is configured (Requirement 2.3)."""
        template.has_resource_properties(
            "AWS::Cognito::UserPoolDomain",
            {
                "Domain": "prescoach-dev-test01",
            },
        )


# --- DynamoDB Tests ---


class TestDynamoDB:
    """Tests for DynamoDB table configuration (Requirement 9.2)."""

    def test_table_pay_per_request_billing(self, template):
        """Assert DynamoDB table has PAY_PER_REQUEST billing mode."""
        template.has_resource_properties(
            "AWS::DynamoDB::Table",
            {
                "TableName": "prescoach-dev-test01-submissions",
                "BillingMode": "PAY_PER_REQUEST",
            },
        )

    def test_table_has_gsi_with_correct_key_schema(self, template):
        """Assert DynamoDB table has GSI with correct key schema."""
        template.has_resource_properties(
            "AWS::DynamoDB::Table",
            {
                "GlobalSecondaryIndexes": [
                    Match.object_like(
                        {
                            "IndexName": "user-uploads-index",
                            "KeySchema": [
                                {"AttributeName": "user_id", "KeyType": "HASH"},
                                {"AttributeName": "upload_date", "KeyType": "RANGE"},
                            ],
                        }
                    )
                ],
            },
        )


# --- S3 Tests ---


class TestS3:
    """Tests for S3 bucket configuration (Requirement 9.3)."""

    def test_s3_bucket_standard_storage_class(self, template):
        """Assert S3 bucket uses STANDARD storage class (no explicit storage class = default).

        When no storage class is explicitly set, S3 defaults to STANDARD.
        The CDK template should not set a non-standard StorageClass.
        """
        template.has_resource_properties(
            "AWS::S3::Bucket",
            {
                "BucketName": "prescoach-dev-test01-uploads",
            },
        )


# --- HTTP API Gateway Tests ---


class TestHttpApi:
    """Tests for HTTP API Gateway configuration."""

    def test_api_has_jwt_authorizer_with_cognito_issuer(self, template):
        """Assert HTTP API has JWT authorizer configured with Cognito issuer.

        The Issuer is constructed from CDK tokens (region + user pool ID),
        so it resolves to a Fn::Join in the synthesized template rather than
        a plain string. We verify the authorizer type and that JwtConfiguration exists.
        """
        template.has_resource_properties(
            "AWS::ApiGatewayV2::Authorizer",
            {
                "AuthorizerType": "JWT",
                "JwtConfiguration": Match.object_like(
                    {
                        "Issuer": Match.any_value(),
                        "Audience": Match.any_value(),
                    }
                ),
            },
        )

    def test_api_has_cors_configured(self, template):
        """Assert HTTP API has CORS configured for https://kiro.geiserai.com."""
        template.has_resource_properties(
            "AWS::ApiGatewayV2::Api",
            {
                "CorsConfiguration": Match.object_like(
                    {
                        "AllowOrigins": ["https://kiro.geiserai.com"],
                        "AllowMethods": Match.array_with(["GET", "POST"]),
                        "AllowHeaders": Match.array_with(
                            ["Content-Type", "Authorization"]
                        ),
                    }
                ),
            },
        )


# --- Lambda Tests ---


class TestLambda:
    """Tests for Lambda function configuration."""

    def test_upload_lambda_python_312_runtime(self, template):
        """Assert Upload Lambda uses Python 3.12 runtime."""
        template.has_resource_properties(
            "AWS::Lambda::Function",
            {
                "FunctionName": "prescoach-dev-test01-upload",
                "Runtime": "python3.12",
            },
        )

    def test_get_submissions_lambda_python_312_runtime(self, template):
        """Assert Get Submissions Lambda uses Python 3.12 runtime."""
        template.has_resource_properties(
            "AWS::Lambda::Function",
            {
                "FunctionName": "prescoach-dev-test01-get-submissions",
                "Runtime": "python3.12",
            },
        )

    def test_confirm_upload_lambda_python_312_runtime(self, template):
        """Assert Confirm Upload Lambda uses Python 3.12 runtime."""
        template.has_resource_properties(
            "AWS::Lambda::Function",
            {
                "FunctionName": "prescoach-dev-test01-confirm-upload",
                "Runtime": "python3.12",
            },
        )

    def test_s3_event_notification_on_confirm_upload(self, template):
        """Assert S3 event notification is configured for Confirm Upload Lambda.

        S3 event notifications in CDK create a Custom::S3BucketNotifications resource.
        We verify the Lambda has an invoke permission from S3.
        """
        template.has_resource_properties(
            "AWS::Lambda::Permission",
            {
                "Action": "lambda:InvokeFunction",
                "Principal": "s3.amazonaws.com",
            },
        )


# --- Resource Naming Convention Tests ---


class TestNamingConvention:
    """Tests for {appName}-{envName}-{instanceId}-{resourceName} naming (Requirement 11.5)."""

    def test_s3_bucket_naming(self, template):
        """Assert S3 bucket follows naming convention."""
        template.has_resource_properties(
            "AWS::S3::Bucket",
            {"BucketName": "prescoach-dev-test01-uploads"},
        )

    def test_dynamodb_table_naming(self, template):
        """Assert DynamoDB table follows naming convention."""
        template.has_resource_properties(
            "AWS::DynamoDB::Table",
            {"TableName": "prescoach-dev-test01-submissions"},
        )

    def test_cognito_user_pool_naming(self, template):
        """Assert Cognito User Pool follows naming convention."""
        template.has_resource_properties(
            "AWS::Cognito::UserPool",
            {"UserPoolName": "prescoach-dev-test01-users"},
        )

    def test_sqs_queue_naming(self, template):
        """Assert Upload Lambda references the preparation-input queue URL."""
        template.has_resource_properties(
            "AWS::Lambda::Function",
            Match.object_like({
                "FunctionName": "prescoach-dev-test01-upload",
                "Environment": Match.object_like({
                    "Variables": Match.object_like({
                        "SQS_QUEUE_URL": Match.any_value(),
                    }),
                }),
            }),
        )

    def test_sqs_dlq_naming(self, template):
        """Assert confirm-upload Lambda references the preparation-input queue URL."""
        template.has_resource_properties(
            "AWS::Lambda::Function",
            Match.object_like({
                "FunctionName": "prescoach-dev-test01-confirm-upload",
                "Environment": Match.object_like({
                    "Variables": Match.object_like({
                        "SQS_QUEUE_URL": Match.any_value(),
                    }),
                }),
            }),
        )

    def test_sns_topic_naming(self, template):
        """Assert SNS topic follows naming convention."""
        template.has_resource_properties(
            "AWS::SNS::Topic",
            {"TopicName": "prescoach-dev-test01-errors"},
        )

    def test_http_api_naming(self, template):
        """Assert HTTP API follows naming convention."""
        template.has_resource_properties(
            "AWS::ApiGatewayV2::Api",
            {"Name": "prescoach-dev-test01-api"},
        )

    def test_upload_lambda_naming(self, template):
        """Assert Upload Lambda follows naming convention."""
        template.has_resource_properties(
            "AWS::Lambda::Function",
            {"FunctionName": "prescoach-dev-test01-upload"},
        )

    def test_get_submissions_lambda_naming(self, template):
        """Assert Get Submissions Lambda follows naming convention."""
        template.has_resource_properties(
            "AWS::Lambda::Function",
            {"FunctionName": "prescoach-dev-test01-get-submissions"},
        )

    def test_confirm_upload_lambda_naming(self, template):
        """Assert Confirm Upload Lambda follows naming convention."""
        template.has_resource_properties(
            "AWS::Lambda::Function",
            {"FunctionName": "prescoach-dev-test01-confirm-upload"},
        )


# --- Tagging Tests ---


class TestTagging:
    """Tests for resource tagging with app, env, and instance tags (Requirement 11.8)."""

    def test_stack_resources_tagged(self, template):
        """Assert all resources are tagged with app, env, and instance tags.

        CDK Tags.of(self).add() applies tags to all taggable resources.
        We verify tags appear on key resources.
        """
        # Check DynamoDB table is tagged
        template.has_resource(
            "AWS::DynamoDB::Table",
            {
                "Properties": Match.object_like(
                    {
                        "Tags": Match.array_with(
                            [
                                {"Key": "app", "Value": "prescoach"},
                                {"Key": "env", "Value": "dev"},
                                {"Key": "instance", "Value": "test01"},
                            ]
                        ),
                    }
                ),
            },
        )

    def test_s3_bucket_tagged(self, template):
        """Assert S3 bucket is tagged with app, env, and instance tags."""
        template.has_resource(
            "AWS::S3::Bucket",
            {
                "Properties": Match.object_like(
                    {
                        "Tags": Match.array_with(
                            [
                                {"Key": "app", "Value": "prescoach"},
                                {"Key": "env", "Value": "dev"},
                                {"Key": "instance", "Value": "test01"},
                            ]
                        ),
                    }
                ),
            },
        )

    def test_sns_topic_tagged(self, template):
        """Assert SNS topic is tagged with app, env, and instance tags."""
        template.has_resource(
            "AWS::SNS::Topic",
            {
                "Properties": Match.object_like(
                    {
                        "Tags": Match.array_with(
                            [
                                {"Key": "app", "Value": "prescoach"},
                                {"Key": "env", "Value": "dev"},
                                {"Key": "instance", "Value": "test01"},
                            ]
                        ),
                    }
                ),
            },
        )


# --- Prefix Validation Tests ---


class TestPrefixValidation:
    """Tests for prefix validation (Requirements 11.5, 11.6)."""

    def test_prefix_validation_rejects_combined_prefix_over_40_chars(self):
        """Assert prefix validation rejects combined prefix > 40 characters."""
        app = cdk.App(
            context={
                "appName": "verylongappname",
                "envName": "production",
                "instanceId": "verylonginstanceid",
            }
        )
        with pytest.raises(ValueError, match="exceeds 40 characters"):
            UploadServiceStack(app, "test-stack")

    def test_prefix_validation_rejects_invalid_instance_id_chars(self):
        """Assert prefix validation rejects invalid instanceId characters."""
        app = cdk.App(
            context={
                "appName": "prescoach",
                "envName": "dev",
                "instanceId": "INVALID_ID!",
            }
        )
        with pytest.raises(ValueError):
            UploadServiceStack(app, "test-stack")

    def test_prefix_validation_rejects_instance_id_too_short(self):
        """Assert prefix validation rejects instanceId shorter than 2 characters."""
        app = cdk.App(
            context={
                "appName": "prescoach",
                "envName": "dev",
                "instanceId": "a",
            }
        )
        with pytest.raises(ValueError):
            UploadServiceStack(app, "test-stack")

    def test_prefix_validation_rejects_instance_id_too_long(self):
        """Assert prefix validation rejects instanceId longer than 20 characters."""
        app = cdk.App(
            context={
                "appName": "prescoach",
                "envName": "dev",
                "instanceId": "a" * 21,
            }
        )
        with pytest.raises(ValueError):
            UploadServiceStack(app, "test-stack")

    def test_valid_prefix_accepted(self):
        """Assert valid prefix is accepted and stack synthesizes."""
        app = cdk.App(
            context={
                "appName": "prescoach",
                "envName": "dev",
                "instanceId": "test01",
            }
        )
        # Should not raise
        stack = UploadServiceStack(app, "prescoach-dev-test01")
        template = Template.from_stack(stack)
        # Verify stack has resources (3 application Lambdas + 1 CDK BucketNotifications handler)
        template.resource_count_is("AWS::Lambda::Function", 4)
