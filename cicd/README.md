# CI/CD Pipelines

Three AWS CodePipeline pipelines for deploying the Presentation Coaching Platform.

## Pipelines

| Pipeline | Name Pattern | Trigger | What It Does |
|----------|-------------|---------|--------------|
| **Frontend** | `{prefix}-frontend` | Manual / CLI | Generates config.js from CDK outputs, syncs webapp/ to S3, invalidates CloudFront |
| **Backend** | `{prefix}-backend` | Manual / CLI | Installs Lambda deps, runs `cdk deploy` for upload-service |
| **Full Deploy** | `{prefix}-full-deploy` | Push to `main` | Runs Backend first, then Frontend (in sequence) |

## Prerequisites

### 1. Store GitHub Token in Secrets Manager

The pipelines need a GitHub Personal Access Token (classic) with `repo` scope to pull your code.

```bash
aws secretsmanager create-secret \
  --name "github-token" \
  --secret-string "ghp_YOUR_GITHUB_PERSONAL_ACCESS_TOKEN" \
  --region us-east-1
```

> Generate a token at: https://github.com/settings/tokens (classic) with `repo` scope.

### 2. Set Environment Variables

```bash
export CDK_DEFAULT_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
export CDK_DEFAULT_REGION=us-east-1
export APP_NAME="prescoach"
export ENV_NAME="dev"
export INSTANCE_ID="kiro"
```

## Deploy the CI/CD Stack

```bash
cd cicd/cdk

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Deploy pipelines
cdk bootstrap aws://$CDK_DEFAULT_ACCOUNT/$CDK_DEFAULT_REGION \
  -c appName=$APP_NAME \
  -c envName=$ENV_NAME \
  -c instanceId=$INSTANCE_ID \
  -c githubRepo="michaelgeiser/kiro-agentcore-app" \
  -c githubBranch="main" \
  -c cloudfrontDistId="E2TQOVHAA67VP5" \
  -c s3Bucket="kiro-aiapp-514917275675-us-east-1-an"

cdk deploy \
  -c appName=$APP_NAME \
  -c envName=$ENV_NAME \
  -c instanceId=$INSTANCE_ID \
  -c githubRepo="michaelgeiser/kiro-agentcore-app" \
  -c githubBranch="main" \
  -c cloudfrontDistId="E2TQOVHAA67VP5" \
  -c s3Bucket="kiro-aiapp-514917275675-us-east-1-an"
```

## Running Pipelines Manually

### Deploy only Frontend
```bash
aws codepipeline start-pipeline-execution \
  --name prescoach-dev-kiro-frontend \
  --region us-east-1
```

### Deploy only Backend
```bash
aws codepipeline start-pipeline-execution \
  --name prescoach-dev-kiro-backend \
  --region us-east-1
```

### Deploy both (Full)
```bash
aws codepipeline start-pipeline-execution \
  --name prescoach-dev-kiro-full-deploy \
  --region us-east-1
```

Or just push to `main` — the full-deploy pipeline triggers automatically.

## Pipeline Execution Order (Full Deploy)

```
Source (GitHub main) → Deploy Backend (CDK) → Deploy Frontend (S3 + CloudFront)
```

Backend deploys first so that any new API changes or Lambda updates are live before the frontend references them.

## Configuration Parameters

All parameters are passed as CDK context (`-c`) flags during the CI/CD stack deployment. They're stored as CodeBuild environment variables:

| Parameter | CodeBuild Env Var | Description |
|-----------|-------------------|-------------|
| `appName` | `APP_NAME` | Application identifier |
| `envName` | `ENV_NAME` | Deployment environment |
| `instanceId` | `INSTANCE_ID` | Instance/tenant identifier |
| `cloudfrontDistId` | `CLOUDFRONT_DIST_ID` | CloudFront distribution ID |
| `s3Bucket` | `S3_BUCKET` | CloudFront origin S3 bucket |
| `githubRepo` | — | GitHub owner/repo |
| `githubBranch` | — | Branch to track |

## Updating Parameters

To change any parameter (e.g., switch from `dev` to `prod`), re-run `cdk deploy` with the new `-c` values. The pipelines will update in place.
