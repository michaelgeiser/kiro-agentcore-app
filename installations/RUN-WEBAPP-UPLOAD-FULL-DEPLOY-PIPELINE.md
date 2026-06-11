# Run Full Deploy Pipeline

Deploys **both upload-service and webapp** in the correct order: Upload Service first, then Frontend.

This is the **recommended way to deploy** when you have changes to both `upload-service/` and `webapp/`, or when you want a complete, consistent deployment.

---

## What It Does

1. Pulls latest code from `main` branch on GitHub
2. **Stage 2 — Deploy Upload Service**: Installs deps, runs `cdk deploy` (Lambda, API Gateway, DynamoDB, etc.)
3. **Stage 3 — Deploy Webapp**: Generates config.js from CDK outputs, syncs to S3, invalidates CloudFront

Upload Service deploys first so that any new API endpoints or Lambda changes are live before the frontend starts referencing them.

---

## Automatic Trigger

This pipeline **automatically triggers on every push to `main`**. You don't need to do anything — just push your code:

```bash
git add .
git commit -m "your changes"
git push origin main
```

The pipeline will start within 30 seconds of your push.

---

## Option A: Run Manually from AWS Console

1. Open the CodePipeline console:
   ```
   https://us-east-1.console.aws.amazon.com/codesuite/codepipeline/pipelines?region=us-east-1
   ```

2. Click on **`prescoach-dev-kiro-webapp-upload-full-deploy`**

3. Click the **"Release change"** button (top right, orange)

4. Confirm when prompted

5. Watch the stages turn green in order:
   - **Source** — Pulls from GitHub (30-60 seconds)
   - **DeployUploadService** — CDK deploy (3-5 minutes)
   - **DeployWebapp** — S3 sync + CloudFront invalidation (1-2 minutes)

6. Done. Both upload-service and webapp are updated.

---

## Option B: Run from CLI (CloudShell or terminal)

```bash
aws codepipeline start-pipeline-execution \
  --name prescoach-dev-kiro-webapp-upload-full-deploy \
  --region us-east-1
```

### Check status

```bash
aws codepipeline get-pipeline-state \
  --name prescoach-dev-kiro-webapp-upload-full-deploy \
  --region us-east-1 \
  --query 'stageStates[*].{Stage:stageName,Status:latestExecution.status}' \
  --output table
```

Expected output during execution:

```
-------------------------------------------
|          GetPipelineState               |
+-----------------+-----------------------+
|      Stage      |        Status         |
+-----------------+-----------------------+
|  Source         |  Succeeded            |
|  DeployUploadService  |  InProgress           |
|  DeployWebapp |  (not yet started)    |
+-----------------+-----------------------+
```

### Watch logs

```bash
# Backend build logs
BUILD_ID=$(aws codebuild list-builds-for-project \
  --project-name prescoach-dev-kiro-upload-service-build \
  --query 'ids[0]' --output text)
echo "Backend logs:"
aws codebuild batch-get-builds --ids $BUILD_ID \
  --query 'builds[0].logs.deepLink' --output text

# Frontend build logs
BUILD_ID=$(aws codebuild list-builds-for-project \
  --project-name prescoach-dev-kiro-webapp-build \
  --query 'ids[0]' --output text)
echo "Frontend logs:"
aws codebuild batch-get-builds --ids $BUILD_ID \
  --query 'builds[0].logs.deepLink' --output text
```

---

## Option C: Run from Windows (CMD or PowerShell with AWS CLI)

### Trigger the pipeline

```cmd
aws codepipeline start-pipeline-execution --name prescoach-dev-kiro-webapp-upload-full-deploy --region us-east-1
```

### Check status

```cmd
aws codepipeline get-pipeline-state --name prescoach-dev-kiro-webapp-upload-full-deploy --region us-east-1 --query "stageStates[*].{Stage:stageName,Status:latestExecution.status}" --output table
```

### Get build logs URLs

```cmd
for /f "tokens=*" %i in ('aws codebuild list-builds-for-project --project-name prescoach-dev-kiro-upload-service-build --query "ids[0]" --output text') do set BUILD_ID=%i
echo Backend logs:
aws codebuild batch-get-builds --ids %BUILD_ID% --query "builds[0].logs.deepLink" --output text

for /f "tokens=*" %i in ('aws codebuild list-builds-for-project --project-name prescoach-dev-kiro-webapp-build --query "ids[0]" --output text') do set BUILD_ID=%i
echo Frontend logs:
aws codebuild batch-get-builds --ids %BUILD_ID% --query "builds[0].logs.deepLink" --output text
```

**PowerShell version:**

```powershell
aws codepipeline start-pipeline-execution --name prescoach-dev-kiro-webapp-upload-full-deploy --region us-east-1

# Check status
aws codepipeline get-pipeline-state --name prescoach-dev-kiro-webapp-upload-full-deploy --region us-east-1 --query "stageStates[*].{Stage:stageName,Status:latestExecution.status}" --output table

# Backend build logs
$BuildId = aws codebuild list-builds-for-project --project-name prescoach-dev-kiro-upload-service-build --query "ids[0]" --output text
Write-Host "Backend logs:"
aws codebuild batch-get-builds --ids $BuildId --query "builds[0].logs.deepLink" --output text

# Frontend build logs
$BuildId = aws codebuild list-builds-for-project --project-name prescoach-dev-kiro-webapp-build --query "ids[0]" --output text
Write-Host "Frontend logs:"
aws codebuild batch-get-builds --ids $BuildId --query "builds[0].logs.deepLink" --output text
```

> **Note:** Ensure your AWS CLI is configured with the correct profile/credentials for your account. If using IAM Identity Center SSO: `aws sso login --profile your-profile-name`

---

## Expected Duration

| Stage | Time |
|-------|------|
| Source (GitHub pull) | ~30 seconds |
| Deploy Upload Service (CDK) | ~3-5 minutes |
| Deploy Webapp (S3 + CF) | ~1-2 minutes |
| **Total** | **~5-8 minutes** |

---

## Execution Order Guarantee

The stages execute **sequentially**, not in parallel:

```
Source → DeployUploadService → DeployWebapp
```

If the Upload Service stage fails, the Webapp stage **will not run**. This prevents deploying a frontend that references an API endpoint or feature that doesn't exist yet.

---

## When to Use Each Pipeline

| Scenario | Pipeline to Use |
|----------|----------------|
| Changed only `webapp/` CSS or JS | Webapp pipeline |
| Changed only `upload-service/` handler logic | Upload Service pipeline |
| Changed both frontend and backend | **Full Deploy** (or just push to main) |
| First deployment / not sure | **Full Deploy** |
| Want to force a complete redeploy | **Full Deploy** |

---

## Troubleshooting

### Pipeline didn't trigger after push to main
1. Check the GitHub webhook exists: **GitHub repo → Settings → Webhooks**
2. Look for a webhook URL pointing to `amazonaws.com`
3. Check "Recent Deliveries" on the webhook — if status is not 200, the webhook may need re-registration
4. Fix: Redeploy the CI/CD stack (`cd cicd/webapp-upload && cdk deploy ...`)

### Upload Service succeeded but Webapp failed
Most common cause: `generate-frontend-config.sh` couldn't find the stack outputs. Check that the stack name (`STACK_NAME` env var) matches the deployed CloudFormation stack name.

### Both stages failed
Check Source stage first — if GitHub token is expired or invalid, nothing will work. Rotate the token in Secrets Manager:
```bash
aws secretsmanager update-secret \
  --secret-id "github-token" \
  --secret-string "ghp_YOUR_NEW_TOKEN" \
  --region us-east-1
```

### I need to roll back
CodePipeline doesn't have built-in rollback. Instead:
1. Revert your commit: `git revert HEAD && git push origin main`
2. The pipeline will auto-trigger and deploy the reverted code
3. Or manually start the pipeline after reverting

### Pipeline is stuck "In Progress"
Builds have a default timeout of 60 minutes. If stuck longer:
1. Go to **CodeBuild → Build history**
2. Find the running build
3. Click **"Stop build"**
4. Investigate the logs to see where it hung
