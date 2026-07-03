"""CDK assertion tests for admin infrastructure.

Validates that the admin Lambda functions, API Gateway routes, IAM policies,
and CORS configuration are correctly provisioned in the CDK stack.

Requirements: 8.5, 9.5
"""

import aws_cdk as cdk
from aws_cdk.assertions import Template, Match

from upload_service.upload_service_stack import UploadServiceStack


def _create_template() -> Template:
    """Synthesize the stack with test context and return a Template."""
    app = cdk.App(
        context={
            "appName": "prescoach",
            "envName": "test",
            "instanceId": "test01",
        }
    )
    stack = UploadServiceStack(app, "TestStack")
    return Template.from_stack(stack)


class TestAdminLambdaFunctions:
    """Test admin Lambda functions are created with correct environment variables."""

    def test_admin_env_vars_lambda_created_with_correct_env(self):
        template = _create_template()
        template.has_resource_properties(
            "AWS::Lambda::Function",
            {
                "FunctionName": "prescoach-test-test01-admin-env-vars",
                "Handler": "handlers.admin_env_vars.handler",
                "Runtime": "python3.12",
                "Environment": {
                    "Variables": {
                        "SSM_PREFIX": "/prescoach/test/admin/env-vars/",
                        "ECS_CLUSTER": "prescoach-test-test01-eval-cluster",
                        "ECS_SERVICE": "prescoach-test-test01-eval-service",
                        "TASK_FAMILY": "prescoach-test-test01-eval-task",
                    }
                },
            },
        )

    def test_admin_feature_flags_lambda_created_with_correct_env(self):
        template = _create_template()
        template.has_resource_properties(
            "AWS::Lambda::Function",
            {
                "FunctionName": "prescoach-test-test01-admin-feature-flags",
                "Handler": "handlers.admin_feature_flags.handler",
                "Runtime": "python3.12",
                "Environment": {
                    "Variables": {
                        "SSM_PREFIX": "/prescoach/test/feature-flags/",
                    }
                },
            },
        )


class TestAdminApiGatewayRoutes:
    """Test API Gateway routes are created for all 4 admin endpoints."""

    def test_get_admin_env_vars_route(self):
        template = _create_template()
        template.has_resource_properties(
            "AWS::ApiGatewayV2::Route",
            {
                "RouteKey": "GET /admin/environment-variables",
                "AuthorizationType": "JWT",
                "AuthorizerId": Match.any_value(),
            },
        )

    def test_put_admin_env_vars_route(self):
        template = _create_template()
        template.has_resource_properties(
            "AWS::ApiGatewayV2::Route",
            {
                "RouteKey": "PUT /admin/environment-variables",
                "AuthorizationType": "JWT",
                "AuthorizerId": Match.any_value(),
            },
        )

    def test_get_admin_feature_flags_route(self):
        template = _create_template()
        template.has_resource_properties(
            "AWS::ApiGatewayV2::Route",
            {
                "RouteKey": "GET /admin/feature-flags",
                "AuthorizationType": "JWT",
                "AuthorizerId": Match.any_value(),
            },
        )

    def test_put_admin_feature_flag_route(self):
        template = _create_template()
        template.has_resource_properties(
            "AWS::ApiGatewayV2::Route",
            {
                "RouteKey": "PUT /admin/feature-flags/{flag-name}",
                "AuthorizationType": "JWT",
                "AuthorizerId": Match.any_value(),
            },
        )


class TestAdminIamPolicies:
    """Test IAM policies grant least-privilege access."""

    def test_ssm_policy_for_admin_env_vars_prefix(self):
        template = _create_template()
        template.has_resource_properties(
            "AWS::IAM::Policy",
            {
                "PolicyDocument": {
                    "Statement": Match.array_with(
                        [
                            Match.object_like(
                                {
                                    "Action": ["ssm:GetParameter", "ssm:PutParameter"],
                                    "Effect": "Allow",
                                    "Resource": {
                                        "Fn::Join": Match.array_with(
                                            [
                                                Match.exact(""),
                                                Match.array_with(
                                                    [
                                                        Match.string_like_regexp(
                                                            ".*:parameter/prescoach/test/admin/env-vars/\\*"
                                                        ),
                                                    ]
                                                ),
                                            ]
                                        )
                                    },
                                }
                            )
                        ]
                    )
                }
            },
        )

    def test_ssm_policy_for_feature_flags_prefix(self):
        template = _create_template()
        template.has_resource_properties(
            "AWS::IAM::Policy",
            {
                "PolicyDocument": {
                    "Statement": Match.array_with(
                        [
                            Match.object_like(
                                {
                                    "Action": ["ssm:GetParameter", "ssm:PutParameter"],
                                    "Effect": "Allow",
                                    "Resource": {
                                        "Fn::Join": Match.array_with(
                                            [
                                                Match.exact(""),
                                                Match.array_with(
                                                    [
                                                        Match.string_like_regexp(
                                                            ".*:parameter/prescoach/test/feature-flags/\\*"
                                                        ),
                                                    ]
                                                ),
                                            ]
                                        )
                                    },
                                }
                            )
                        ]
                    )
                }
            },
        )

    def test_ecs_update_service_scoped_to_eval_cluster(self):
        template = _create_template()
        template.has_resource_properties(
            "AWS::IAM::Policy",
            {
                "PolicyDocument": {
                    "Statement": Match.array_with(
                        [
                            Match.object_like(
                                {
                                    "Action": [
                                        "ecs:UpdateService",
                                        "ecs:DescribeServices",
                                    ],
                                    "Effect": "Allow",
                                    "Resource": {
                                        "Fn::Join": Match.array_with(
                                            [
                                                Match.exact(""),
                                                Match.array_with(
                                                    [
                                                        Match.string_like_regexp(
                                                            ".*:service/prescoach-test-test01-eval-cluster/prescoach-test-test01-eval-service"
                                                        ),
                                                    ]
                                                ),
                                            ]
                                        )
                                    },
                                }
                            )
                        ]
                    )
                }
            },
        )

    def test_ecs_task_definition_permissions(self):
        template = _create_template()
        template.has_resource_properties(
            "AWS::IAM::Policy",
            {
                "PolicyDocument": {
                    "Statement": Match.array_with(
                        [
                            Match.object_like(
                                {
                                    "Action": [
                                        "ecs:DescribeTaskDefinition",
                                        "ecs:RegisterTaskDefinition",
                                    ],
                                    "Effect": "Allow",
                                    "Resource": "*",
                                }
                            )
                        ]
                    )
                }
            },
        )

    def test_iam_pass_role_scoped_to_ecs_tasks(self):
        template = _create_template()
        template.has_resource_properties(
            "AWS::IAM::Policy",
            {
                "PolicyDocument": {
                    "Statement": Match.array_with(
                        [
                            Match.object_like(
                                {
                                    "Action": "iam:PassRole",
                                    "Effect": "Allow",
                                    "Condition": {
                                        "StringEquals": {
                                            "iam:PassedToService": "ecs-tasks.amazonaws.com"
                                        }
                                    },
                                }
                            )
                        ]
                    )
                }
            },
        )


class TestCorsConfiguration:
    """Test CORS configuration includes PUT method."""

    def test_cors_includes_put_method(self):
        template = _create_template()
        template.has_resource_properties(
            "AWS::ApiGatewayV2::Api",
            {
                "CorsConfiguration": {
                    "AllowMethods": Match.array_with(["PUT"]),
                    "AllowOrigins": Match.array_with(["https://kiro.geiserai.com"]),
                    "AllowHeaders": Match.array_with(["Content-Type", "Authorization"]),
                }
            },
        )

    def test_cors_includes_all_required_methods(self):
        template = _create_template()
        template.has_resource_properties(
            "AWS::ApiGatewayV2::Api",
            {
                "CorsConfiguration": {
                    "AllowMethods": Match.array_with(
                        ["GET", "POST", "PUT", "DELETE"]
                    ),
                }
            },
        )
