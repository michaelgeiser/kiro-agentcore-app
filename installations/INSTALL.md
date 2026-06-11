# Installation & Deployment Guide

## Presentation Coaching Platform — Backend (Upload & Storage) + Frontend SPA

This guide walks you through deploying the complete platform from scratch. It assumes:

- You have an existing CloudFront distribution serving `https://kiro.geiserai.com`
- You have an AWS account with appropriate permissions
- You are starting from a fresh clone of this repository

---

## Table of Contents

0. [AWS IAM Identity Center (IDC) Setup](#0-aws-iam-identity-center-idc-setup)
1. [Configuration Parameters Reference](#1-configuration-parameters-reference)
2. [Prerequisites — What You Need Installed](#2-prerequisites--what-you-need-installed)
3. [Where to Run CDK: Windows Laptop vs CloudShell](#3-where-to-run-cdk-windows-laptop-vs-cloudshell)
4. [Backend Deployment (upload-service)](#4-backend-deployment-upload-service)
5. [Frontend Deployment (webapp)](#5-frontend-deployment-webapp)
6. [Post-Deployment Verification](#6-post-deployment-verification)
7. [Local Development Setup](#7-local-development-setup)
8. [Troubleshooting](#8-troubleshooting)

---

## 0. AWS IAM Identity Center (IDC) Setup

Before deploying anything, the IDC user (or group) running the deployment needs the correct AWS managed policies attached to their Permission Set. This section lists everything required.

### 0.1 — Minimum Permission Set Policies

Attach these **AWS managed policies** to the Permission Set assigned to your IDC group:

| # | Policy Name | Why It's Needed |
|---|-------------|-----------------|
| 1 | `AdministratorAccess` | **OR** use the granular policies below. If you want a single policy that covers everything, this is it. Skip the rest of this table. |

If you prefer least-privilege over `AdministratorAccess`, attach ALL of the following instead:

| # | Policy Name | Why It's Needed |
|---|-------------|-----------------|
| 1 | `AWSCloudFormationFullAccess` | CDK deploys CloudFormation stacks. Needs create/update/delete/describe on stacks, change sets, and stack resources. |
| 2 | `AmazonS3FullAccess` | Creates the uploads bucket, manages bucket policies/notifications, syncs frontend files to CloudFront origin bucket. |
| 3 | `AmazonDynamoDBFullAccess` | Creates the submissions table with GSI, sets billing mode, manages table policies. |
| 4 | `AmazonSQSFullAccess` | Creates the processing queue and dead-letter queue, manages queue policies. |
| 5 | `AmazonSNSFullAccess` | Creates the errors topic, manages topic policies and subscriptions. |
| 6 | `AWSLambda_FullAccess` | Creates Lambda functions, manages function configurations, layers, and permissions. |
| 7 | `AmazonCognitoPowerUser` | Creates User Pool, App Client, Hosted UI Domain. Does not need the `Admin` policy variant. |
| 8 | `AmazonAPIGatewayAdministrator` | Creates HTTP API, routes, integrations, authorizers, stages. |
| 9 | `IAMFullAccess` | CDK creates IAM roles for Lambda execution and grants resource permissions (S3, DynamoDB, SQS, SNS). Also creates the CDK bootstrap roles. |
| 10 | `AmazonSSMReadOnlyAccess` | CDK reads SSM parameters during bootstrap and asset publishing. |
| 11 | `AmazonEC2ContainerRegistryFullAccess` | CDK bootstrap creates an ECR repository for Docker image assets (even if you're not using containers — the bootstrap template includes it). |
| 12 | `CloudFrontFullAccess` | Creating CloudFront invalidations after frontend deploy. Only needed if you're deploying frontend from the same role. |
| 13 | `AmazonBedrockFullAccess` | Required if the downstream Preparation Workflow uses Bedrock for AI analysis. Not strictly needed for the upload-and-storage service alone, but needed for the full platform. |

### 0.2 — CDK Bootstrap-Specific Permissions

The first-time `cdk bootstrap` command creates a CloudFormation stack named `CDKToolkit` that provisions:
- An S3 bucket for CDK assets (Lambda code zips)
- An ECR repository (for Docker-based assets)
- IAM roles for CDK deployment operations

The policies above cover this. If you hit permissions errors during bootstrap, ensure `IAMFullAccess`, `AmazonS3FullAccess`, and `AWSCloudFormationFullAccess` are attached.

### 0.3 — Inline Policy for CDK Asset Publishing (if not using IAMFullAccess)

If you refuse to grant `IAMFullAccess` and want the absolute minimum for IAM, create this custom inline policy on the Permission Set:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "CDKRoleManagement",
      "Effect": "Allow",
      "Action": [
        "iam:CreateRole",
        "iam:DeleteRole",
        "iam:AttachRolePolicy",
        "iam:DetachRolePolicy",
        "iam:PutRolePolicy",
        "iam:DeleteRolePolicy",
        "iam:GetRole",
        "iam:GetRolePolicy",
        "iam:ListRolePolicies",
        "iam:ListAttachedRolePolicies",
        "iam:PassRole",
        "iam:TagRole",
        "iam:UntagRole"
      ],
      "Resource": [
        "arn:aws:iam::*:role/cdk-*",
        "arn:aws:iam::*:role/prescoach-*"
      ]
    },
    {
      "Sid": "CDKAssetPublishing",
      "Effect": "Allow",
      "Action": [
        "sts:AssumeRole"
      ],
      "Resource": [
        "arn:aws:iam::*:role/cdk-*"
      ]
    }
  ]
}
```

### 0.4 — How to Apply in IAM Identity Center

1. Go to **IAM Identity Center** → **Permission Sets**
2. Create a new Permission Set (or edit your existing one), e.g., `PresCoach-Deploy`
3. Under **AWS managed policies**, attach the policies from the table above
4. If using the custom inline policy (Section 0.3), add it under **Customer managed policies** or **Inline policy**
5. Go to **AWS accounts** → select your target account → **Assign users or groups**
6. Assign your IDC group to the account with the `PresCoach-Deploy` Permission Set
7. Your IDC users can now assume this role via the AWS access portal

### 0.5 — Verifying Permissions Before Deployment

After assigning the Permission Set, verify your IDC user can access the account:

```bash
# From CloudShell or after SSO login:
aws sts get-caller-identity
```

Expected output:
```json
{
  "UserId": "AROA...:your-email@example.com",
  "Account": "123456789012",
  "Arn": "arn:aws:sts::123456789012:assumed-role/AWSReservedSSO_PresCoach-Deploy_.../your-email@example.com"
}
```

### 0.6 — Summary: Quick vs Secure

| Approach | Policies | Risk Level | Use When |
|----------|----------|------------|----------|
| **Quick** | `AdministratorAccess` only | High (full account access) | Dev/test accounts, personal experimentation |
| **Granular** | 12-13 specific policies listed above | Medium (broad but scoped to services) | Shared accounts, team environments |
| **Minimal** | Granular + custom inline (Section 0.3) instead of `IAMFullAccess` | Lower (IAM actions scoped to CDK/app roles) | Production accounts with strict governance |

> **Recommendation:** For your first deployment, use `AdministratorAccess`. Once you've confirmed everything works, narrow down to the granular set. CDK permission errors are cryptic and hard to debug — get it working first, then lock it down.

---

## 1. Configuration Parameters Reference

These are ALL the values you need to decide before deploying. Everything else is derived automatically.

| Parameter | Description | Constraints | Example | How It's Used |
|-----------|-------------|-------------|---------|---------------|
| `appName` | Application identifier | Lowercase, 3-15 chars | `prescoach` | CDK context flag (`-c appName=prescoach`) |
| `envName` | Deployment environment | Any short string (e.g., `dev`, `prod`) | `prod` | CDK context flag (`-c envName=prod`) |
| `instanceId` | Unique instance/tenant ID | Lowercase alphanumeric + hyphens, 2-20 chars | `main` | CDK context flag (`-c instanceId=main`) |
| `AWS Account ID` | Your 12-digit AWS account number | Numeric | `123456789012` | Environment variable `CDK_DEFAULT_ACCOUNT` |
| `AWS Region` | Region for all resources | Valid AWS region code | `us-east-1` | Environment variable `CDK_DEFAULT_REGION` |
| `Frontend Domain` | Your CloudFront URL | Must match CORS config | `https://kiro.geiserai.com` | Hardcoded in CDK stack (CORS) and Cognito callback URLs |
| `CloudFront Origin Bucket` | S3 bucket that CloudFront serves from | Must exist already | `my-site-origin-bucket` | Used in `aws s3 sync` command for frontend deploy |
| `CloudFront Distribution ID` | Your existing CloudFront distribution | Must exist already | `E1A2B3C4D5E6F7` | Used in `aws cloudfront create-invalidation` command |

### How to Set Them (copy-paste into CloudShell before deploying)

Set these environment variables once at the start of your session. Every command in this guide uses them — no manual find-and-replace needed.

```bash
# ============================================================
# EDIT THESE VALUES — then paste the whole block into CloudShell
# ============================================================

# CDK deployment parameters (passed as -c flags)
export APP_NAME="prescoach"
export ENV_NAME="prod"
export INSTANCE_ID="main"

# AWS environment (CDK uses these to target account/region)
export CDK_DEFAULT_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
export CDK_DEFAULT_REGION="us-east-1"

# Frontend deployment targets (your existing infrastructure)
export CLOUDFRONT_BUCKET="your-cloudfront-origin-bucket-name"
export CLOUDFRONT_DIST_ID="your-cloudfront-distribution-id"

# Derived values (do not edit — computed from above)
export STACK_NAME="${APP_NAME}-${ENV_NAME}-${INSTANCE_ID}"

# ============================================================
# Verify what you set
# ============================================================
echo ""
echo "=== Deployment Configuration ==="
echo "  App Name:       $APP_NAME"
echo "  Environment:    $ENV_NAME"
echo "  Instance ID:    $INSTANCE_ID"
echo "  Stack Name:     $STACK_NAME"
echo "  AWS Account:    $CDK_DEFAULT_ACCOUNT"
echo "  AWS Region:     $CDK_DEFAULT_REGION"
echo "  CF Bucket:      $CLOUDFRONT_BUCKET"
echo "  CF Dist ID:     $CLOUDFRONT_DIST_ID"
echo "================================="
```

> **Important:** All commands later in this guide reference these variables (e.g., `$STACK_NAME`, `$APP_NAME`). If you start a new CloudShell session, re-paste this block.

### Naming convention applied to all resources:
```
{appName}-{envName}-{instanceId}-{resourceName}
```

### Example with the defaults:
```
prescoach-prod-main-uploads        (S3 bucket)
prescoach-prod-main-submissions    (DynamoDB table)
prescoach-prod-main-users          (Cognito User Pool)
prescoach-prod-main-api            (HTTP API Gateway)
prescoach-prod-main-upload         (Lambda function)
```

**Constraint:** The combined prefix `{appName}-{envName}-{instanceId}` must not exceed 40 characters.

---

## 2. Prerequisites — What You Need Installed

### For CDK Deployment (wherever you run it)

| Tool | Minimum Version | Install Command / Link | CloudShell Verify Command |
|------|-----------------|------------------------|---------------------------|
| Python | 3.12+ | https://python.org/downloads/ | `python3 --version` |
| pip | Latest | Comes with Python | `pip3 --version` |
| Node.js | 18+ | https://nodejs.org/ | `node --version` |
| npm | 9+ | Comes with Node.js | `npm --version` |
| AWS CDK CLI | 2.100+ | `npm install -g aws-cdk` | `cdk --version` |
| AWS CLI | 2.x | https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html | `aws --version` |
| jq | 1.6+ | https://stedolan.github.io/jq/download/ | `jq --version` |
| git | Any | Pre-installed on CloudShell | `git --version` |

### Quick Verify Script (paste this into CloudShell)

Run this one-liner to confirm all tools are present and meet minimum versions:

```bash
echo "=== Prerequisite Check ===" && \
python3 --version && \
pip3 --version && \
node --version && \
npm --version && \
aws --version && \
jq --version && \
git --version && \
(cdk --version 2>/dev/null || echo "CDK CLI: NOT INSTALLED — run: npm install -g aws-cdk") && \
echo "=== All checks complete ==="
```

Expected output (versions may be higher):

```
=== Prerequisite Check ===
Python 3.12.x
pip 23.x.x from /usr/lib/python3/dist-packages/pip (python 3.12)
v18.x.x
9.x.x
aws-cli/2.x.x Python/3.11.x Linux/...
jq-1.6
git version 2.x.x
2.1xx.0 (build xxxxxxx)
=== All checks complete ===
```

If CDK CLI is missing, install it:

```bash
npm install -g aws-cdk
```

### For Frontend Only (if just deploying static files)

| Tool | Version | Purpose | CloudShell Verify Command |
|------|---------|---------|---------------------------|
| AWS CLI | 2.x | S3 sync to CloudFront origin bucket | `aws --version` |
| jq | 1.6+ | Parse CDK outputs for config generation | `jq --version` |

---

## 3. Where to Run CDK: Windows Laptop vs CloudShell

### Recommendation: Use CloudShell

**Use AWS CloudShell** in the target account. Here's why:

| Factor | Windows Laptop | CloudShell |
|--------|---------------|------------|
| AWS credentials | Must configure profiles, MFA, assume-role | Already authenticated to the console account |
| Python 3.12 | Must install manually | Pre-installed |
| Node.js / npm | Must install manually | Pre-installed |
| AWS CDK CLI | Must install via npm | `npm install -g aws-cdk` (one command) |
| Network latency | Uploads CDK assets over internet | Same-region, near-zero latency |
| IAM permissions | Requires long-lived credentials or SSO | Inherits your console session role |
| Cost | Free | Free (1 GB persistent storage) |
| Disk space | Unlimited | 1 GB persistent (enough for this project) |

**The one case for Windows laptop:** If you want to run tests locally before deploying, use your laptop for development and testing, then deploy from CloudShell.

### CloudShell Limitations to Know

- Session times out after 20 minutes of inactivity (files persist)
- 1 GB storage limit (this project is well under that)
- No Docker (not needed here — we use CDK asset bundling)
- Available in most but not all regions

---

## 4. Backend Deployment (upload-service)

### Step 4.1 — Open CloudShell (or your terminal)

1. Sign in to the AWS Console in the account where you want to deploy
2. Click the CloudShell icon (terminal icon) in the top navigation bar
3. Wait for the shell to initialize

### Step 4.2 — Clone the Repository

```bash
git clone <your-repo-url> prescoach
cd prescoach/kiro-agentcore-app
```

### Step 4.3 — Install or Upgrade CDK CLI

```bash
# Check if CDK is installed and what version
cdk --version
```

If CDK is not installed, or you get a schema version mismatch error like:
```
Cloud assembly schema version mismatch: Maximum schema version supported is 53.x.x, but found 54.0.0
```

Install/upgrade using a local npm prefix (avoids CloudShell permissions issues):

```bash
# Set up a local npm global directory (one-time setup)
mkdir -p ~/.npm-global
npm config set prefix '~/.npm-global'
export PATH=~/.npm-global/bin:$PATH

# Make the PATH change persistent across CloudShell sessions
echo 'export PATH=~/.npm-global/bin:$PATH' >> ~/.bashrc

# Install latest CDK CLI
npm install -g aws-cdk@latest
```

Verify it worked:

```bash
cdk --version
# Should show 2.1126.0 or higher
```

> **Why this happens:** The `aws-cdk-lib` Python package (from pip) and the `aws-cdk` CLI (from npm) must be compatible versions. If the Python library is newer than the CLI, CDK will refuse to run with a schema mismatch error. Always install the latest CLI.

### Step 4.4 — Set Up Python Virtual Environment

```bash
cd upload-service/cdk

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install CDK dependencies
pip install -r requirements.txt
```

### Step 4.5 — Install Lambda Dependencies

The Lambda functions need their dependencies packaged. Create a deployment layer:

```bash
cd ../  # back to upload-service/
pip install -r requirements.txt -t src/
```

> **Note:** This installs `boto3` and `pydantic` into the `src/` directory so they're bundled with the Lambda code. In production you may want a Lambda Layer instead, but for initial deployment this works.

### Step 4.6 — Bootstrap CDK (first time only)

If you've never used CDK in this account/region:

```bash
cd cdk/
cdk bootstrap aws://$CDK_DEFAULT_ACCOUNT/$CDK_DEFAULT_REGION \
  -c appName=$APP_NAME \
  -c envName=$ENV_NAME \
  -c instanceId=$INSTANCE_ID
```

> **Why the context flags?** `cdk bootstrap` synthesizes your app first to discover assets, which triggers the stack validation that requires `envName` and `instanceId`. Always pass `-c` flags for any CDK command.

### Step 4.7 — Deploy the Stack

```bash
# Deploy with context parameters (uses env vars from Section 1)
cdk deploy \
  -c appName=$APP_NAME \
  -c envName=$ENV_NAME \
  -c instanceId=$INSTANCE_ID
```

CDK will show you a summary of resources to be created and ask for confirmation. Type `y` to proceed.

**Expected outputs after deployment:**

```
Outputs:
prescoach-prod-main.ApiEndpoint = https://abc123def.execute-api.us-east-1.amazonaws.com
prescoach-prod-main.CognitoUserPoolId = us-east-1_AbCdEfGhI
prescoach-prod-main.CognitoAppClientId = 1a2b3c4d5e6f7g8h9i0j
prescoach-prod-main.CognitoDomain = https://prescoach-prod-main.auth.us-east-1.amazoncognito.com
```

These values are automatically captured by the config generation script in the next section — no need to copy them manually.

### Step 4.8 — Verify Backend Deployment

```bash
# Test that the API endpoint responds (should return 401 — no auth token)
API_URL=$(aws cloudformation describe-stacks --stack-name $STACK_NAME \
  --query 'Stacks[0].Outputs[?OutputKey==`ApiEndpoint`].OutputValue' --output text)
curl -s $API_URL/submissions | jq .
```

Expected response: `{"message":"Unauthorized"}` — this confirms the API is live and the JWT authorizer is working.

---

## 5. Frontend Deployment (webapp)

### Step 5.1 — Generate Frontend Configuration

From the `upload-service` directory, run the config generation script:

```bash
# Make script executable (if not already)
chmod +x scripts/generate-frontend-config.sh

# Generate config from CDK outputs (uses $STACK_NAME from Section 1)
./scripts/generate-frontend-config.sh $STACK_NAME
```

This reads the CloudFormation stack outputs and writes `webapp/js/config.js` with actual values:

```javascript
export const CONFIG = {
  cognitoDomain: 'https://prescoach-prod-main.auth.us-east-1.amazoncognito.com',
  clientId: '1a2b3c4d5e6f7g8h9i0j',
  apiBaseUrl: 'https://abc123def.execute-api.us-east-1.amazonaws.com',
};
```

### Step 5.2 — Manual Configuration (alternative to script)

If you can't run the script, manually edit `webapp/js/config.js`:

```javascript
export const CONFIG = {
  cognitoDomain: '<CognitoDomain output from Step 4.7>',
  clientId: '<CognitoAppClientId output from Step 4.7>',
  apiBaseUrl: '<ApiEndpoint output from Step 4.7>',
};
```

### Step 5.3 — Deploy Frontend to S3 (CloudFront Origin)

```bash
cd ../webapp

# Sync all frontend files to your S3 origin bucket (uses $CLOUDFRONT_BUCKET from Section 1)
aws s3 sync . s3://$CLOUDFRONT_BUCKET/ \
  --exclude "node_modules/*" \
  --exclude "tests/*" \
  --exclude "package*.json" \
  --exclude "vitest.config.js" \
  --delete
```

### Step 5.4 — Invalidate CloudFront Cache

```bash
# Uses $CLOUDFRONT_DIST_ID from Section 1
aws cloudfront create-invalidation \
  --distribution-id $CLOUDFRONT_DIST_ID \
  --paths "/*"
```

### Step 5.5 — Verify Frontend

Open `https://kiro.geiserai.com` in your browser. You should see:
1. The app loads
2. You're redirected to the Cognito login page
3. You can sign up with an email address
4. After verifying your email and logging in, you see the submissions list (empty)

---

## 6. Post-Deployment Verification

### Checklist

| Step | Test | Expected Result |
|------|------|-----------------|
| 1 | Visit `https://kiro.geiserai.com` | App loads, redirects to Cognito login |
| 2 | Click "Sign Up" on Cognito hosted UI | Registration form appears |
| 3 | Register with email + strong password | Verification code sent to email |
| 4 | Enter verification code | Redirected back to app, logged in |
| 5 | Navigate to Upload page | File upload form renders |
| 6 | Upload a small .mp3 file with title | 201 response, presigned URL upload succeeds |
| 7 | Navigate to List page | Your submission appears with "Pending" status |

### Verify S3 Upload Landed

```bash
aws s3 ls s3://prescoach-prod-main-uploads/uploads/ --recursive
```

### Verify DynamoDB Record

```bash
aws dynamodb scan \
  --table-name prescoach-prod-main-submissions \
  --limit 5 | jq '.Items[0]'
```

---

## 7. Local Development Setup

For running the frontend locally during development:

### Frontend (webapp)

```bash
cd webapp

# Install test dependencies
npm install

# Run tests
npm test

# Serve locally (any static server works)
npx http-server . -p 5500 -c-1
```

Then open `http://localhost:5500`. The Cognito callback URLs already include `http://localhost:5500`.

### Backend (upload-service)

```bash
cd upload-service

# Create virtual environment
python -m venv .venv

# Activate (Windows)
.venv\Scripts\activate

# Activate (Linux/macOS/CloudShell)
source .venv/bin/activate

# Install all dependencies
pip install -r requirements.txt -r requirements-dev.txt

# Run tests
python -m pytest tests/ -v
```

---

## 8. Troubleshooting

### "CDK bootstrap required"

```
Error: This stack uses assets, so the toolkit stack must be deployed
```

**Fix:** Run `cdk bootstrap aws://ACCOUNT_ID/REGION` (see Step 4.6).

### "Cognito domain prefix already exists"

```
Error: Domain already associated with another user pool
```

**Fix:** The domain prefix `{appName}-{envName}-{instanceId}` must be globally unique across all AWS accounts. Change your `instanceId` to something unique.

### "S3 bucket already exists"

```
Error: prescoach-prod-main-uploads already exists
```

**Fix:** S3 bucket names are globally unique. Either:
- Delete the existing bucket (if it's yours from a previous deployment)
- Change your `instanceId` to create a different bucket name

### CORS errors in the browser console

```
Access to fetch blocked by CORS policy
```

**Fix:** The API Gateway is configured to allow `https://kiro.geiserai.com`. Ensure:
1. You're accessing the app via `https://kiro.geiserai.com` (not `http://`)
2. The CORS origin in the CDK stack matches your exact domain (no trailing slash)

### "Unauthorized" when making API calls after login

1. Check that the API Gateway JWT authorizer audience matches your Cognito App Client ID
2. Verify the issuer URL is correct: `https://cognito-idp.{region}.amazonaws.com/{user_pool_id}`
3. Ensure the access token hasn't expired (1 hour validity)

### Lambda "Module not found" errors

```
Unable to import module 'handlers/upload': No module named 'pydantic'
```

**Fix:** Lambda dependencies weren't packaged correctly. Re-run:
```bash
cd upload-service
pip install -r requirements.txt -t src/
```

Then redeploy: `cd cdk && cdk deploy -c appName=$APP_NAME -c envName=$ENV_NAME -c instanceId=$INSTANCE_ID`

### CloudShell times out during deployment

CDK deploy can take 3-5 minutes. If CloudShell times out:
1. Reconnect to CloudShell (your files are preserved)
2. Re-paste the environment variables block from Section 1
3. Re-activate the virtual environment: `cd prescoach/kiro-agentcore-app/upload-service/cdk && source .venv/bin/activate`
4. Run `cdk deploy` again — CDK is idempotent and will skip already-created resources

---

## Quick Reference: Complete Deploy in One Go

For an experienced user who just wants the commands. Paste the env var block from Section 1 first, then:

```bash
# Clone and navigate
git clone <repo-url> prescoach && cd prescoach/kiro-agentcore-app

# Backend
cd upload-service
pip install -r requirements.txt -t src/
cd cdk
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cdk bootstrap aws://$CDK_DEFAULT_ACCOUNT/$CDK_DEFAULT_REGION \
  -c appName=$APP_NAME -c envName=$ENV_NAME -c instanceId=$INSTANCE_ID
cdk deploy -c appName=$APP_NAME -c envName=$ENV_NAME -c instanceId=$INSTANCE_ID --require-approval never

# Frontend config
cd ..
chmod +x scripts/generate-frontend-config.sh
./scripts/generate-frontend-config.sh $STACK_NAME

# Frontend deploy
cd ../webapp
aws s3 sync . s3://$CLOUDFRONT_BUCKET/ --exclude "node_modules/*" --exclude "tests/*" --exclude "package*.json" --exclude "vitest.config.js" --delete
aws cloudfront create-invalidation --distribution-id $CLOUDFRONT_DIST_ID --paths "/*"
```
