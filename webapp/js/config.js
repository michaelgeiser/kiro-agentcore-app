// Generated from CDK stack outputs after deployment
// Run: scripts/generate-frontend-config.sh <stack-name> to populate actual values
export const CONFIG = {
  // Cognito auth requests proxied through CloudFront to avoid SChannel TLS issues
  // on Windows clients connecting directly to *.amazoncognito.com endpoints.
  // See: documentation/cloudfront-cognito-proxy-fix.md
  cognitoDomain: 'https://kiro.geiserai.com/cognito',

  // From CfnOutput "CognitoAppClientId" - Cognito User Pool App Client ID
  clientId: 'your-cognito-client-id',

  // From CfnOutput "ApiEndpoint" - HTTP API Gateway endpoint URL
  apiBaseUrl: 'https://your-api-id.execute-api.us-east-1.amazonaws.com',
};
