# CI/CD Pipelines

AWS CodePipeline definitions for deploying the Presentation Coaching Platform components.

## Directory Structure

```
cicd/
├── README.md                          # This file
├── webapp-upload/                     # Pipelines for Webapp (frontend) + Upload Service (backend)
│   ├── app.py
│   ├── cdk.json
│   ├── requirements.txt
│   └── webapp_upload_pipeline_stack.py
└── preparation-workflow/              # Pipelines for Preparation Workflow (Step Functions, Lambdas)
    ├── app.py
    ├── cdk.json
    ├── requirements.txt
    └── preparation_workflow_pipeline_stack.py
```

## Webapp & Upload Service Pipelines

Located in `cicd/webapp-upload/`. Defines three CodePipeline pipelines:

| Pipeline | Name Pattern | Trigger | What It Does |
|----------|-------------|---------|--------------|
| **Webapp** | `{prefix}-webapp` | Manual / CLI | Generates config.js from CDK outputs, syncs webapp/ to S3, invalidates CloudFront |
| **Upload Service** | `{prefix}-upload-service` | Manual / CLI | Installs Lambda deps, runs `cdk deploy` for upload-service |
| **Full Deploy** | `{prefix}-webapp-upload-full-deploy` | Manual / CLI | Runs Upload Service first, then Webapp (in sequence) |

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

## Deploy the Webapp & Upload Service CI/CD Stack

```bash
cd cicd/webapp-upload

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

### Deploy only Webapp
```bash
aws codepipeline start-pipeline-execution \
  --name prescoach-dev-kiro-webapp \
  --region us-east-1
```

### Deploy only Upload Service
```bash
aws codepipeline start-pipeline-execution \
  --name prescoach-dev-kiro-upload-service \
  --region us-east-1
```

### Deploy both (Full)
```bash
aws codepipeline start-pipeline-execution \
  --name prescoach-dev-kiro-webapp-upload-full-deploy \
  --region us-east-1
```

## Pipeline Execution Order (Full Deploy)

```
Source (GitHub) → Deploy Upload Service (CDK) → Deploy Webapp (S3 + CloudFront)
```

Upload Service deploys first so that any new API changes or Lambda updates are live before the webapp references them.

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

---

## Preparation Workflow Pipelines

Located in `cicd/preparation-workflow/`. Defines three CodePipeline pipelines:

| Pipeline | Name Pattern | Trigger | What It Does |
|----------|-------------|---------|--------------|
| **Test** | `{prefix}-prep-workflow-test` | Manual / CLI | Runs property, unit, and integration tests |
| **Deploy** | `{prefix}-prep-workflow-deploy` | Manual / CLI | Runs `cdk deploy` for preparation-workflow (Step Functions, Lambda, SQS, etc.) |
| **Full Deploy** | `{prefix}-prep-workflow-full-deploy` | Manual / CLI | Runs Tests first, then Deploy (recommended) |

### Deploy the Preparation Workflow CI/CD Stack

```bash
cd cicd/preparation-workflow

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cdk deploy \
  -c appName=$APP_NAME \
  -c envName=$ENV_NAME \
  -c instanceId=$INSTANCE_ID \
  -c githubRepo="michaelgeiser/kiro-agentcore-app" \
  -c githubBranch="main"
```

### Running Preparation Workflow Pipelines

```bash
# Full deploy (test then deploy — recommended)
aws codepipeline start-pipeline-execution \
  --name prescoach-dev-kiro-prep-workflow-full-deploy \
  --region us-east-1

# Test only
aws codepipeline start-pipeline-execution \
  --name prescoach-dev-kiro-prep-workflow-test \
  --region us-east-1

# Deploy only (skip tests)
aws codepipeline start-pipeline-execution \
  --name prescoach-dev-kiro-prep-workflow-deploy \
  --region us-east-1
```
