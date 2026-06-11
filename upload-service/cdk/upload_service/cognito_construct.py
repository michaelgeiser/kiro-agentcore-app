"""Cognito User Pool and App Client construct for the Upload Service.

Provisions a Cognito User Pool with email sign-in, self sign-up, and an
OAuth 2.0 App Client configured for Authorization Code Grant with PKCE.

Requirements: 2.1, 2.2, 2.3, 11.1, 11.4
"""

from aws_cdk import (
    CfnOutput,
    Duration,
    aws_cognito as cognito,
)
from constructs import Construct


class CognitoConstruct(Construct):
    """Cognito User Pool, Domain, and App Client for the Upload Service."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        resource_prefix: str,
    ) -> None:
        """Create the Cognito resources.

        Args:
            scope: CDK scope.
            construct_id: Logical ID for this construct.
            resource_prefix: Combined prefix ({appName}-{envName}-{instanceId}).
        """
        super().__init__(scope, construct_id)

        # --- User Pool ---
        self.user_pool = cognito.UserPool(
            self,
            "UserPool",
            user_pool_name=f"{resource_prefix}-users",
            self_sign_up_enabled=True,
            sign_in_aliases=cognito.SignInAliases(email=True),
            auto_verify=cognito.AutoVerifiedAttrs(email=True),
            standard_attributes=cognito.StandardAttributes(
                email=cognito.StandardAttribute(required=True, mutable=True),
            ),
            password_policy=cognito.PasswordPolicy(
                min_length=8,
                require_uppercase=True,
                require_lowercase=True,
                require_digits=True,
                require_symbols=True,
            ),
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
            mfa=cognito.Mfa.OPTIONAL,
            mfa_second_factor=cognito.MfaSecondFactor(otp=True, sms=False),
        )

        # --- Hosted UI Domain ---
        self.user_pool_domain = self.user_pool.add_domain(
            "UserPoolDomain",
            cognito_domain=cognito.CognitoDomainOptions(
                domain_prefix=resource_prefix,
            ),
        )

        # --- App Client (PKCE, no secret) ---
        self.user_pool_client = self.user_pool.add_client(
            "AppClient",
            generate_secret=False,
            auth_flows=cognito.AuthFlow(
                user_srp=True,
                user_password=False,
                custom=False,
            ),
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(
                    authorization_code_grant=True,
                    implicit_code_grant=False,
                ),
                scopes=[
                    cognito.OAuthScope.OPENID,
                    cognito.OAuthScope.PROFILE,
                    cognito.OAuthScope.EMAIL,
                ],
                callback_urls=[
                    "https://kiro.geiserai.com",
                    "http://localhost:5500",
                ],
                logout_urls=[
                    "https://kiro.geiserai.com",
                    "http://localhost:5500",
                ],
            ),
            access_token_validity=Duration.hours(1),
            refresh_token_validity=Duration.days(30),
            id_token_validity=Duration.hours(1),
        )

        # --- CDK Outputs ---
        CfnOutput(
            self,
            "CognitoUserPoolId",
            value=self.user_pool.user_pool_id,
            description="Cognito User Pool ID",
        )

        CfnOutput(
            self,
            "CognitoAppClientId",
            value=self.user_pool_client.user_pool_client_id,
            description="Cognito App Client ID",
        )

        CfnOutput(
            self,
            "CognitoDomain",
            value=self.user_pool_domain.base_url(),
            description="Cognito Hosted UI Domain URL",
        )
