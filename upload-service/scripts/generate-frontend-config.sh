#!/usr/bin/env bash
#
# generate-frontend-config.sh
#
# Reads CDK stack outputs from CloudFormation and generates webapp/js/config.js
# with the actual deployed values for Cognito domain, client ID, and API endpoint.
#
# Usage:
#   ./scripts/generate-frontend-config.sh [stack-name]
#
# Arguments:
#   stack-name  (optional) CloudFormation stack name. Defaults to the CDK naming
#               convention: prescoach-dev-local01 (appName-envName-instanceId).
#               Override with your actual deployed stack name.
#
# Examples:
#   ./scripts/generate-frontend-config.sh prescoach-prod-acme123
#   ./scripts/generate-frontend-config.sh   # uses default

set -euo pipefail

STACK_NAME="${1:-prescoach-dev-local01}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONFIG_OUTPUT="${PROJECT_ROOT}/../webapp/js/config.js"

# --- Preflight checks ---

if ! command -v aws &> /dev/null; then
  echo "ERROR: AWS CLI is not installed or not in PATH." >&2
  echo "Install it from https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html" >&2
  exit 1
fi

if ! command -v jq &> /dev/null; then
  echo "ERROR: jq is not installed or not in PATH." >&2
  echo "Install it from https://stedolan.github.io/jq/download/" >&2
  exit 1
fi

# --- Fetch stack outputs ---

echo "Fetching outputs from CloudFormation stack: ${STACK_NAME}..."

OUTPUTS=$(aws cloudformation describe-stacks \
  --stack-name "${STACK_NAME}" \
  --query 'Stacks[0].Outputs' \
  --output json 2>&1) || {
  echo "ERROR: Failed to describe stack '${STACK_NAME}'." >&2
  echo "Ensure the stack exists and your AWS credentials are configured." >&2
  echo "Details: ${OUTPUTS}" >&2
  exit 1
}

if [ "${OUTPUTS}" = "null" ] || [ -z "${OUTPUTS}" ]; then
  echo "ERROR: Stack '${STACK_NAME}' has no outputs." >&2
  exit 1
fi

# --- Extract values from outputs ---

extract_output() {
  local key="$1"
  local value
  value=$(echo "${OUTPUTS}" | jq -r ".[] | select(.OutputKey==\"${key}\") | .OutputValue")
  if [ -z "${value}" ] || [ "${value}" = "null" ]; then
    echo "ERROR: Output '${key}' not found in stack '${STACK_NAME}'." >&2
    echo "Available outputs:" >&2
    echo "${OUTPUTS}" | jq -r '.[].OutputKey' >&2
    exit 1
  fi
  echo "${value}"
}

COGNITO_DOMAIN=$(extract_output "CognitoDomain")
COGNITO_CLIENT_ID=$(extract_output "CognitoAppClientId")
API_ENDPOINT=$(extract_output "ApiEndpoint")

# --- Generate config.js ---

mkdir -p "$(dirname "${CONFIG_OUTPUT}")"

cat > "${CONFIG_OUTPUT}" << EOF
// Generated from CDK stack outputs after deployment
// Stack: ${STACK_NAME}
// Run: scripts/generate-frontend-config.sh ${STACK_NAME} to regenerate
export const CONFIG = {
  // From CfnOutput "CognitoDomain" - Cognito Hosted UI Domain URL
  cognitoDomain: '${COGNITO_DOMAIN}',

  // From CfnOutput "CognitoAppClientId" - Cognito User Pool App Client ID
  clientId: '${COGNITO_CLIENT_ID}',

  // From CfnOutput "ApiEndpoint" - HTTP API Gateway endpoint URL
  apiBaseUrl: '${API_ENDPOINT}',
};
EOF

echo "Successfully generated: ${CONFIG_OUTPUT}"
echo "  cognitoDomain: ${COGNITO_DOMAIN}"
echo "  clientId:      ${COGNITO_CLIENT_ID}"
echo "  apiBaseUrl:    ${API_ENDPOINT}"
