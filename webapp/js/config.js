// Generated from CDK stack outputs after deployment
// Run: scripts/generate-frontend-config.sh <stack-name> to populate actual values
export const CONFIG = {
  // From CfnOutput "CognitoDomain" - Cognito Hosted UI Domain URL
  cognitoDomain: 'https://your-prefix.auth.us-east-1.amazoncognito.com',

  // From CfnOutput "CognitoAppClientId" - Cognito User Pool App Client ID
  clientId: 'your-cognito-client-id',

  // From CfnOutput "ApiEndpoint" - HTTP API Gateway endpoint URL
  apiBaseUrl: 'https://your-api-id.execute-api.us-east-1.amazonaws.com',
};
