# CI/CD Pipeline Installation — Step by Step

## Overview

This document walks you through deploying the CI/CD pipelines (CodePipeline + CodeBuild) from CloudShell. These pipelines automate future deployments so you never need to manually run CDK from CloudShell again.

**What gets created:**
- `prescoach-dev-kiro-frontend` — deploys only the webapp
- `prescoach-dev-kiro-backend` — deploys only the upload-service via CDK
- `prescoach-dev-kiro-full-deploy` — deploys backend then frontend (auto-triggers on push to `main`)

---

## Prerequisites

- You have already deployed the upload-service stack at least once (the backend must exist for the frontend pipeline to read CDK outputs)
- You have access to the AWS Console with sufficient permissions (see `INSTALL.md` Section 0)
- The repo is https://github.com/michaelgeiser/kiro-agentcore-app (public)

---

## Step 1: Create a GitHub Personal Access Token

Even though the repo is public, CodePipeline needs a token to create webhooks and use the GitHub API.

1. Go to https://github.com/settings/tokens
2. Click **"Generate new token (classic)"**
3. Settings:
   - **Name:** `prescoach-codepipeline`
   - **Expiration:** 90 days (or "No expiration" if you prefer)
   - **Scopes:** check only **`repo`** (Full control of private repositories — needed for webhook creation even on public repos)
4. Click **Generate token**
5. **Copy the token immediately** (starts with `ghp_...`) — you won't see it again

---

## Step 2: Store the Token in AWS Secrets Manager

Open CloudShell in your target AWS account and run:

```bash
aws secretsmanager create-secret \
  --name "github-token" \
  --secret-string "ghp_PASTE_YOUR_TOKEN_HERE" \
  --region us-east-1
```

If the secret already exists (from a previous attempt):

```bash
aws secretsmanager update-secret \
  --secret-id "github-token" \
  --secret-string "ghp_PASTE_YOUR_TOKEN_HERE" \
  --region us-east-1
```

Verify it stored:

```bash
aws secretsmanager get-secret-value \
  --secret-id "github-token" \
  --query 'SecretString' \
  --output text \
  --region us-east-1
```

---

## Step 3: Free CloudShell Disk Space

CloudShell has only 1 GB. The CI/CD CDK stack needs ~60 MB for its virtual environment. If you previously installed the upload-service dependencies, you need to free space first.

```bash
# Check current disk usage
df -h ~
du -sh ~/* 2>/dev/null | sort -rh | head -10

# Delete previous upload-service artifacts (not needed for CI/CD stack)
rm -rf ~/prescoach/upload-service/cdk/.venv
rm -rf ~/prescoach/upload-service/cdk/cdk.out
rm -rf ~/prescoach/upload-service/src/pydantic*
rm -rf ~/prescoach/upload-service/src/annotated_types*
rm -rf ~/prescoach/upload-service/src/typing_extensions*
rm -rf ~/prescoach/upload-service/src/*.dist-info
rm -rf ~/prescoach/upload-service/src/boto3*
rm -rf ~/prescoach/upload-service/src/botocore*
rm -rf ~/prescoach/upload-service/src/s3transfer*
rm -rf ~/prescoach/upload-service/src/urllib3*
rm -rf ~/prescoach/upload-service/src/jmespath*
rm -rf ~/prescoach/webapp/node_modules

# Clear caches
rm -rf ~/.cache/pip
rm -rf ~/.npm/_cacache

# Verify you have enough space (need ~100 MB free)
df -h ~
```

---

## Step 4: Deactivate Any Previous Virtual Environment

If you were previously in the upload-service venv, deactivate it:

```bash
deactivate 2>/dev/null || true
```

---

## Step 5: Get the Latest Code

```bash
cd ~/prescoach
git fetch origin
git reset --hard origin/main
```

---

## Step 6: Install CDK CLI

```bash
# Ensure npm global path is set up
mkdir -p ~/.npm-global
npm config set prefix '~/.npm-global'
export PATH=~/.npm-global/bin:$PATH

# Install latest CDK
npm install -g aws-cdk@latest

# Verify
cdk --version
```

---

## Step 7: Set Up the CI/CD CDK Virtual Environment

```bash
cd ~/prescoach/cicd/cdk

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install CDK Python dependencies
pip install -r requirements.txt --no-cache-dir
```

---

## Step 8: Set Environment Variables

```bash
export CDK_DEFAULT_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
export CDK_DEFAULT_REGION="us-east-1"
```

---

## Step 9: Bootstrap CDK (if not already done)

If you've already bootstrapped this account/region for the upload-service, skip this step.

```bash
cdk bootstrap aws://$CDK_DEFAULT_ACCOUNT/$CDK_DEFAULT_REGION \
  -c appName=prescoach \
  -c envName=dev \
  -c instanceId=kiro
```

---

## Step 10: Deploy the Pipeline Stack

```bash
cdk deploy \
  -c appName=prescoach \
  -c envName=dev \
  -c instanceId=kiro \
  -c githubRepo="michaelgeiser/kiro-agentcore-app" \
  -c githubBranch="main" \
  -c cloudfrontDistId="E2TQOVHAA67VP5" \
  -c s3Bucket="kiro-aiapp-514917275675-us-east-1-an"
```

Type `y` when prompted to approve IAM changes.

**Expected output:**

```
Outputs:
prescoach-dev-kiro-cicd.FrontendPipelineName = prescoach-dev-kiro-frontend
prescoach-dev-kiro-cicd.BackendPipelineName = prescoach-dev-kiro-backend
prescoach-dev-kiro-cicd.FullPipelineName = prescoach-dev-kiro-full-deploy
```

---

## Step 11: Verify Pipelines Exist

```bash
aws codepipeline list-pipelines \
  --region us-east-1 \
  --query 'pipelines[*].name' \
  --output table
```

Should show:

```
-----------------------------------------
|            ListPipelines              |
+---------------------------------------+
|  prescoach-dev-kiro-frontend          |
|  prescoach-dev-kiro-backend           |
|  prescoach-dev-kiro-full-deploy       |
+---------------------------------------+
```

---

## Step 12: Test — Trigger Full Deploy

```bash
aws codepipeline start-pipeline-execution \
  --name prescoach-dev-kiro-full-deploy \
  --region us-east-1
```

Or just push a commit to `main` — the webhook will trigger it automatically.

---

## Step 13: Verify in AWS Console

1. Go to: https://us-east-1.console.aws.amazon.com/codesuite/codepipeline/pipelines?region=us-east-1
2. Click `prescoach-dev-kiro-full-deploy`
3. Watch Source → DeployBackend → DeployFrontend stages turn green

---

## After This Is Done

You never need to manually `cdk deploy` from CloudShell again. Just:
- Push to `main` → full deploy runs automatically
- Or trigger individual pipelines from the console or CLI (see `RUN-FRONTEND-PIPELINE.md`, `RUN-BACKEND-PIPELINE.md`)

---

## Troubleshooting

### "No space left on device" during pip install

```bash
# Check what's using space
du -sh ~/* 2>/dev/null | sort -rh | head -10

# Nuclear option: delete everything and re-clone
rm -rf ~/prescoach
git clone https://github.com/michaelgeiser/kiro-agentcore-app.git ~/prescoach
```

### "github-token" secret not found

```bash
aws secretsmanager list-secrets --region us-east-1 --query 'SecretList[*].Name' --output table
```

If not listed, re-run Step 2.

### CDK bootstrap error "envName is required"

Always pass the `-c` context flags, even for bootstrap:

```bash
cdk bootstrap aws://$CDK_DEFAULT_ACCOUNT/$CDK_DEFAULT_REGION \
  -c appName=prescoach -c envName=dev -c instanceId=kiro
```

### "CDK CLI version mismatch"

```bash
npm install -g aws-cdk@latest
cdk --version
```

### Webhook not triggering

1. Go to GitHub repo → Settings → Webhooks
2. Check the webhook URL and recent deliveries
3. If missing, redeploy the CI/CD stack (Step 10)

### Pipeline fails at Source stage

The GitHub token might be expired or have wrong permissions. Update it:

```bash
aws secretsmanager update-secret \
  --secret-id "github-token" \
  --secret-string "ghp_YOUR_NEW_TOKEN" \
  --region us-east-1
```
