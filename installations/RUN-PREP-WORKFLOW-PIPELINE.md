# Run Preparation Workflow Pipeline

Deploys the **Preparation Workflow** infrastructure (Step Functions, Lambda functions, SQS queues, SSM parameters, EventBridge Pipe, SNS topic) via CDK.

---

## Pipelines

| Pipeline | Name Pattern | What It Does |
|----------|-------------|--------------|
| **Test** | `{prefix}-prep-workflow-test` | Runs property tests, unit tests, and integration tests |
| **Deploy** | `{prefix}-prep-workflow-deploy` | Installs deps, runs `cdk deploy` for preparation-workflow infra |
| **Full Deploy** | `{prefix}-prep-workflow-full-deploy` | Runs Tests first, then Deploy (recommended) |

---

## Option A: Run from AWS Console

1. Open the CodePipeline console:
   ```
   https://us-east-1.console.aws.amazon.com/codesuite/codepipeline/pipelines?region=us-east-1
   ```

2. Click on **`prescoach-dev-kiro-prep-workflow-full-deploy`**

3. Click the **"Release change"** button (top right, orange)

4. Confirm when prompted

5. Watch the stages turn green:
   - **Source** — Pulls from GitHub (30-60 seconds)
   - **Test** — Runs property/unit/integration tests (1-3 minutes)
   - **Deploy** — CDK synthesizes and deploys CloudFormation (3-5 minutes)

6. Done. The Step Functions workflow, Lambda functions, SQS queues, and all supporting resources are updated.

---

## Option B: Run from CLI

### Run full deploy (test + deploy)
```bash
aws codepipeline start-pipeline-execution \
  --name prescoach-dev-kiro-prep-workflow-full-deploy \
  --region us-east-1
```

### Run tests only
```bash
aws codepipeline start-pipeline-execution \
  --name prescoach-dev-kiro-prep-workflow-test \
  --region us-east-1
```

### Run deploy only (skip tests)
```bash
aws codepipeline start-pipeline-execution \
  --name prescoach-dev-kiro-prep-workflow-deploy \
  --region us-east-1
```

### Check status
```bash
aws codepipeline get-pipeline-state \
  --name prescoach-dev-kiro-prep-workflow-full-deploy \
  --region us-east-1 \
  --query 'stageStates[*].{Stage:stageName,Status:latestExecution.status}' \
  --output table
```

### View build logs
```bash
# Test build logs
BUILD_ID=$(aws codebuild list-builds-for-project \
  --project-name prescoach-dev-kiro-prep-workflow-test \
  --query 'ids[0]' --output text)
aws codebuild batch-get-builds --ids $BUILD_ID \
  --query 'builds[0].logs.deepLink' --output text

# Deploy build logs
BUILD_ID=$(aws codebuild list-builds-for-project \
  --project-name prescoach-dev-kiro-prep-workflow-deploy \
  --query 'ids[0]' --output text)
aws codebuild batch-get-builds --ids $BUILD_ID \
  --query 'builds[0].logs.deepLink' --output text
```

---

## Option C: Run from Windows (CMD or PowerShell)

### CMD
```cmd
aws codepipeline start-pipeline-execution --name prescoach-dev-kiro-prep-workflow-full-deploy --region us-east-1
```

```cmd
aws codepipeline get-pipeline-state --name prescoach-dev-kiro-prep-workflow-full-deploy --region us-east-1 --query "stageStates[*].{Stage:stageName,Status:latestExecution.status}" --output table
```

### PowerShell
```powershell
aws codepipeline start-pipeline-execution --name prescoach-dev-kiro-prep-workflow-full-deploy --region us-east-1

# Check status
aws codepipeline get-pipeline-state --name prescoach-dev-kiro-prep-workflow-full-deploy --region us-east-1 --query "stageStates[*].{Stage:stageName,Status:latestExecution.status}" --output table

# Test build logs
$BuildId = aws codebuild list-builds-for-project --project-name prescoach-dev-kiro-prep-workflow-test --query "ids[0]" --output text
aws codebuild batch-get-builds --ids $BuildId --query "builds[0].logs.deepLink" --output text

# Deploy build logs
$BuildId = aws codebuild list-builds-for-project --project-name prescoach-dev-kiro-prep-workflow-deploy --query "ids[0]" --output text
aws codebuild batch-get-builds --ids $BuildId --query "builds[0].logs.deepLink" --output text
```

---

## Expected Duration

| Stage | Time |
|-------|------|
| Source (GitHub pull) | ~30 seconds |
| Test (pytest property + unit + integration) | ~1-3 minutes |
| Deploy (CDK synth + CloudFormation) | ~3-5 minutes |
| **Total (Full Deploy)** | **~5-9 minutes** |

---

## What Gets Deployed

The CDK stack creates/updates:

| Resource | Description |
|----------|-------------|
| Step Functions Standard Workflow | 12-state orchestration (parse → validate → extract → embed → store → handoff) |
| 9 Lambda functions | load_config, parse_message, validate_format, extract_audio, chunk_audio, create_embedding, store_vectors, publish_handoff, handle_failure |
| SQS Input Queue + DLQ | Standard queue with maxReceiveCount=3 |
| SQS Handoff Queue + DLQ | FIFO queue for Agentic Processing handoff |
| SNS Error Topic | Operational error notifications |
| SSM Parameters (9) | Runtime configuration under /prescoach/{env}/preparation-workflow/ |
| EventBridge Pipe | SQS Input Queue → Step Functions trigger |
| CloudWatch Log Group | Execution logging for the state machine |

---

## Pipeline Execution Order (Full Deploy)

```
Source → Test (property + unit + integration) → Deploy (CDK)
```

If tests fail, the Deploy stage **will not run**. This prevents deploying broken code.

---

## When to Use Each Pipeline

| Scenario | Pipeline to Use |
|----------|----------------|
| Changed handler code or models | **Full Deploy** (tests + deploy) |
| Changed only CDK infra (IAM, queues, etc.) | Deploy only |
| Want to validate tests without deploying | Test only |
| First deployment of preparation workflow | **Full Deploy** |

---

## Troubleshooting

### Tests fail in the Test stage
Check the CodeBuild logs for the test project. Common issues:
- Missing dependency: update `requirements-dev.txt`
- Hypothesis test timeout: increase `deadline` setting
- Moto mock setup issue: ensure `@mock_aws` decorator is present

### CDK deploy fails with "Stack not found"
The preparation-workflow stack hasn't been bootstrapped. Run CDK bootstrap first (see installation guide).

### Lambda "Module not found" after deploy
The `pip install -r requirements.txt -t src/` step must complete before `cdk deploy`. Check install phase logs.

### "Access Denied" errors
The CodeBuild role needs broad permissions for Step Functions, Lambda, SQS, SNS, SSM, etc. Redeploy the CI/CD stack if permissions are missing.
