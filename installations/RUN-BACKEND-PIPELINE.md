# Run Backend Pipeline

Deploys **only the upload-service** backend (Lambda functions, API Gateway, DynamoDB, Cognito, etc.) via CDK.

Use this when you've made changes to `upload-service/` files (handlers, services, models, CDK infrastructure) and don't need to redeploy the frontend.

---

## What It Does

1. Pulls latest code from `main` branch on GitHub
2. Installs the CDK CLI (latest version)
3. Installs Lambda dependencies (`boto3`, `pydantic`) into `src/` for packaging
4. Installs CDK Python dependencies (`aws-cdk-lib`, `constructs`)
5. Runs `cdk deploy` with your configured `APP_NAME`, `ENV_NAME`, `INSTANCE_ID`
6. CloudFormation updates all backend resources (Lambda code, API Gateway config, etc.)

---

## Option A: Run from AWS Console

1. Open the CodePipeline console:
   ```
   https://us-east-1.console.aws.amazon.com/codesuite/codepipeline/pipelines?region=us-east-1
   ```

2. Click on **`prescoach-dev-kiro-backend`**

3. Click the **"Release change"** button (top right, orange)

4. Confirm when prompted

5. Watch the stages turn green:
   - **Source** — Pulls from GitHub (30-60 seconds)
   - **Deploy** — CDK synthesizes and deploys CloudFormation (3-5 minutes)

6. Done. The Lambda functions and API Gateway are updated.

---

## Option B: Run from CLI (CloudShell or terminal)

```bash
aws codepipeline start-pipeline-execution \
  --name prescoach-dev-kiro-backend \
  --region us-east-1
```

### Check status

```bash
aws codepipeline get-pipeline-state \
  --name prescoach-dev-kiro-backend \
  --region us-east-1 \
  --query 'stageStates[*].{Stage:stageName,Status:latestExecution.status}' \
  --output table
```

### Watch logs in real time

```bash
BUILD_ID=$(aws codebuild list-builds-for-project \
  --project-name prescoach-dev-kiro-backend-build \
  --query 'ids[0]' --output text)

aws codebuild batch-get-builds --ids $BUILD_ID \
  --query 'builds[0].logs.deepLink' --output text
```

Open the URL to see full CloudWatch logs.

---

## Option C: Run from Windows (CMD or PowerShell with AWS CLI)

### Trigger the pipeline

```cmd
aws codepipeline start-pipeline-execution --name prescoach-dev-kiro-backend --region us-east-1
```

### Check status

```cmd
aws codepipeline get-pipeline-state --name prescoach-dev-kiro-backend --region us-east-1 --query "stageStates[*].{Stage:stageName,Status:latestExecution.status}" --output table
```

### Get build logs URL

```cmd
for /f "tokens=*" %i in ('aws codebuild list-builds-for-project --project-name prescoach-dev-kiro-backend-build --query "ids[0]" --output text') do set BUILD_ID=%i
aws codebuild batch-get-builds --ids %BUILD_ID% --query "builds[0].logs.deepLink" --output text
```

**PowerShell version:**

```powershell
aws codepipeline start-pipeline-execution --name prescoach-dev-kiro-backend --region us-east-1

# Check status
aws codepipeline get-pipeline-state --name prescoach-dev-kiro-backend --region us-east-1 --query "stageStates[*].{Stage:stageName,Status:latestExecution.status}" --output table

# Get build logs URL
$BuildId = aws codebuild list-builds-for-project --project-name prescoach-dev-kiro-backend-build --query "ids[0]" --output text
aws codebuild batch-get-builds --ids $BuildId --query "builds[0].logs.deepLink" --output text
```

> **Note:** Ensure your AWS CLI is configured with the correct profile/credentials for your account. If using IAM Identity Center SSO: `aws sso login --profile your-profile-name`

---

## Expected Duration

| Stage | Time |
|-------|------|
| Source (GitHub pull) | ~30 seconds |
| Install (CDK CLI + pip) | ~1-2 minutes |
| Deploy (CDK synth + CloudFormation) | ~2-4 minutes |
| **Total** | **~4-6 minutes** |

---

## What Gets Updated

CDK is smart about changes. It only updates resources that actually changed:

| Change | Result |
|--------|--------|
| Modified Lambda handler code | Lambda function code updated (fast, ~30s) |
| New environment variable added | Lambda configuration updated |
| New API route added | API Gateway route + integration created |
| DynamoDB schema change | New GSI added (can take minutes) |
| No changes at all | "No changes" — stack unchanged |

---

## Troubleshooting

### "CDK CLI version mismatch"
The buildspec installs `aws-cdk@latest`. If the `aws-cdk-lib` pip package is newer than what npm provides, you'll get a schema mismatch. Fix: pin the CDK lib version in `upload-service/cdk/requirements.txt` to match.

### "Cannot find asset at .../src"
The CDK stack uses `Code.from_asset("../src")`. CodeBuild runs from the repo root, but the CDK app runs from `upload-service/cdk/`. Verify the buildspec `cd upload-service` then `cd cdk` commands are correct.

### "Stack is in ROLLBACK_COMPLETE state"
A previous deploy failed mid-way. Delete the stack in CloudFormation console, then re-run:
```bash
aws cloudformation delete-stack --stack-name prescoach-dev-kiro --region us-east-1
```
Wait for deletion to complete, then trigger the pipeline again.

### "Access Denied" on CloudFormation operations
The CodeBuild role needs broad permissions for CDK. The CI/CD stack grants `cloudformation:*`, `lambda:*`, `iam:*`, etc. If something is missing, redeploy the CI/CD stack.

### Lambda "Module not found" after deploy
The `pip install -r requirements.txt -t src/` step must run before `cdk deploy`. Check the CodeBuild logs to confirm the install phase completed successfully.
