# CI/CD Pipeline Setup & Architecture — Webapp & Upload Service

## Overview

The project uses **AWS CodePipeline + CodeBuild** for CI/CD. The Webapp & Upload Service pipelines are defined in `cicd/webapp-upload/`:

| Pipeline | Purpose | Auto-Trigger |
|----------|---------|--------------|
| **Webapp** (`prescoach-dev-kiro-webapp`) | Deploys webapp to S3 + invalidates CloudFront | No — manual only |
| **Upload Service** (`prescoach-dev-kiro-upload-service`) | Runs CDK deploy for upload-service (Lambdas, API Gateway, etc.) | No — manual only |
| **Full Deploy** (`prescoach-dev-kiro-webapp-upload-full-deploy`) | Runs Upload Service first, then Webapp | No — manual only |

## Architecture Diagram

```
GitHub (main branch)
        │
        ▼ (manual or CLI trigger)
┌─────────────────────────────────────────────┐
│  Webapp & Upload Service Full Deploy        │
│                                             │
│  Stage 1: Source (GitHub checkout)          │
│  Stage 2: Deploy Upload Service (CDK)      │
│  Stage 3: Deploy Webapp (S3 + CloudFront)  │
└─────────────────────────────────────────────┘

┌─────────────────────────┐    ┌──────────────────────────────┐
│  Webapp Pipeline        │    │  Upload Service Pipeline     │
│  (manual trigger only)  │    │  (manual trigger only)       │
│                         │    │                              │
│  Source → Deploy to S3  │    │  Source → CDK deploy         │
└─────────────────────────┘    └──────────────────────────────┘
```

## Where to Find Pipelines in the AWS Console

### CodePipeline Console

1. Open the AWS Console
2. Navigate to **Services → Developer Tools → CodePipeline**
3. Or use this direct URL (replace region if needed):
   ```
   https://us-east-1.console.aws.amazon.com/codesuite/codepipeline/pipelines?region=us-east-1
   ```
4. You will see three pipelines:
   - `prescoach-dev-kiro-webapp`
   - `prescoach-dev-kiro-upload-service`
   - `prescoach-dev-kiro-webapp-upload-full-deploy`

### Viewing Pipeline Status

Click any pipeline name to see:
- **Source** — Shows the last commit pulled from GitHub
- **Deploy** — Shows CodeBuild execution status (In Progress, Succeeded, Failed)
- Click "Details" on any stage action to open the CodeBuild logs

### CodeBuild Projects

1. Navigate to **Services → Developer Tools → CodeBuild**
2. Or: `https://us-east-1.console.aws.amazon.com/codesuite/codebuild/projects?region=us-east-1`
3. Build projects:
   - `prescoach-dev-kiro-webapp-build` — Handles S3 sync and CloudFront invalidation
   - `prescoach-dev-kiro-upload-service-build` — Handles CDK deploy for upload-service

Click a build project → **Build history** to see past runs and their logs.

### Secrets Manager (GitHub Token)

1. Navigate to **Services → Security → Secrets Manager**
2. Or: `https://us-east-1.console.aws.amazon.com/secretsmanager/listsecrets?region=us-east-1`
3. Look for the secret named `github-token`
4. This stores the GitHub Personal Access Token used by CodePipeline to pull your repo

## Pipeline Configuration Values

These were set when the CI/CD stack was deployed and are stored as CodeBuild environment variables:

| Variable | Value | Set During |
|----------|-------|------------|
| `APP_NAME` | `prescoach` | CDK deploy (`-c appName=...`) |
| `ENV_NAME` | `dev` | CDK deploy (`-c envName=...`) |
| `INSTANCE_ID` | `kiro` | CDK deploy (`-c instanceId=...`) |
| `STACK_NAME` | `prescoach-dev-kiro` | Derived from above |
| `S3_BUCKET` | `<YOUR_WEBAPP_S3_BUCKET>` | CDK deploy (`-c s3Bucket=...`) |
| `CLOUDFRONT_DIST_ID` | `<YOUR_CLOUDFRONT_DIST_ID>` | CDK deploy (`-c cloudfrontDistId=...`) |

## Updating Pipeline Configuration

If you need to change any parameters (e.g., point to a different CloudFront distribution, change environment name):

```bash
cd cicd/webapp-upload
source .venv/bin/activate

cdk deploy \
  -c appName=prescoach \
  -c envName=prod \
  -c instanceId=main \
  -c githubRepo="michaelgeiser/kiro-agentcore-app" \
  -c githubBranch="main" \
  -c cloudfrontDistId="YOUR_NEW_DIST_ID" \
  -c s3Bucket="your-new-bucket-name"
```

The existing pipelines update in place — no need to delete and recreate.

## How the GitHub Webhook Works

When you deployed the Full Deploy pipeline with `trigger=WEBHOOK`:
1. CDK registered a webhook with your GitHub repository
2. Every push to `main` triggers a POST to an AWS endpoint
3. CodePipeline starts the Full Deploy pipeline automatically

To verify the webhook exists:
1. Go to GitHub → your repo → **Settings → Webhooks**
2. You should see a webhook pointing to `https://...amazonaws.com/...`

If the webhook is missing, you can manually trigger from the console or re-deploy the CI/CD stack.

## Costs

- **CodePipeline**: $1/month per active pipeline (free tier: 1 pipeline)
- **CodeBuild**: $0.005/minute (build.general1.small), $0.01/minute (build.general1.medium)
- Typical full deploy: ~3-5 minutes = ~$0.03-0.05 per run
- GitHub webhook triggers are free
