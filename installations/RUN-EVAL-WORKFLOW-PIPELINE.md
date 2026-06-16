# Run Agentic Evaluation Pipeline

Deploys the **Agentic Evaluation** infrastructure (SQS consumer, evaluation agents, report generator, DLQ monitor, SNS notifications) via CDK.

---

## Pipelines

| Pipeline | Name Pattern | What It Does |
|----------|-------------|--------------|
| **Test** | `{prefix}-eval-workflow-test` | Runs 238 tests (property + unit + integration) |
| **Deploy** | `{prefix}-eval-workflow-deploy` | Installs deps, runs `cdk deploy` for agentic-evaluation infra |
| **Full Deploy** | `{prefix}-eval-workflow-full-deploy` | Runs Tests first, then Deploy (recommended) |

---

## Option A: Run from AWS Console

1. Open the CodePipeline console:
   ```
   https://us-east-1.console.aws.amazon.com/codesuite/codepipeline/pipelines?region=us-east-1
   ```

2. Click on **`prescoach-dev-kiro-eval-workflow-full-deploy`**

3. Click the **"Release change"** button (top right, orange)

4. Confirm when prompted

5. Watch the stages turn green:
   - **Source** — Pulls from GitHub (30-60 seconds)
   - **Test** — Runs property/unit/integration tests (2-4 minutes)
   - **Deploy** — CDK synthesizes and deploys CloudFormation (3-5 minutes)

6. Done.

---

## Option B: Run from CLI

### Run full deploy (test + deploy)
```bash
aws codepipeline start-pipeline-execution \
  --name prescoach-dev-kiro-eval-workflow-full-deploy \
  --region us-east-1
```

### Run tests only
```bash
aws codepipeline start-pipeline-execution \
  --name prescoach-dev-kiro-eval-workflow-test \
  --region us-east-1
```

### Run deploy only (skip tests)
```bash
aws codepipeline start-pipeline-execution \
  --name prescoach-dev-kiro-eval-workflow-deploy \
  --region us-east-1
```

### Check status
```bash
aws codepipeline get-pipeline-state \
  --name prescoach-dev-kiro-eval-workflow-full-deploy \
  --region us-east-1 \
  --query 'stageStates[*].{Stage:stageName,Status:latestExecution.status}' \
  --output table
```

### View build logs
```bash
# Test build logs
BUILD_ID=$(aws codebuild list-builds-for-project \
  --project-name prescoach-dev-kiro-eval-workflow-test \
  --query 'ids[0]' --output text)
aws codebuild batch-get-builds --ids $BUILD_ID \
  --query 'builds[0].logs.deepLink' --output text

# Deploy build logs
BUILD_ID=$(aws codebuild list-builds-for-project \
  --project-name prescoach-dev-kiro-eval-workflow-deploy \
  --query 'ids[0]' --output text)
aws codebuild batch-get-builds --ids $BUILD_ID \
  --query 'builds[0].logs.deepLink' --output text
```

---

## Option C: Run from Windows (PowerShell)

```powershell
aws codepipeline start-pipeline-execution --name prescoach-dev-kiro-eval-workflow-full-deploy --region us-east-1

# Check status
aws codepipeline get-pipeline-state --name prescoach-dev-kiro-eval-workflow-full-deploy --region us-east-1 --query "stageStates[*].{Stage:stageName,Status:latestExecution.status}" --output table

# Test build logs
$BuildId = aws codebuild list-builds-for-project --project-name prescoach-dev-kiro-eval-workflow-test --query "ids[0]" --output text
aws codebuild batch-get-builds --ids $BuildId --query "builds[0].logs.deepLink" --output text

# Deploy build logs
$BuildId = aws codebuild list-builds-for-project --project-name prescoach-dev-kiro-eval-workflow-deploy --query "ids[0]" --output text
aws codebuild batch-get-builds --ids $BuildId --query "builds[0].logs.deepLink" --output text
```

---

## Expected Duration

| Stage | Time |
|-------|------|
| Source (GitHub pull) | ~30 seconds |
| Test (pytest property + unit + integration) | ~2-4 minutes |
| Deploy (CDK synth + CloudFormation) | ~3-5 minutes |
| **Total (Full Deploy)** | **~6-10 minutes** |

---

## What Gets Deployed

| Resource | Description |
|----------|-------------|
| SQS FIFO Queue consumption config | Consumer reads from preparation-workflow handoff queue |
| S3 paths | Evaluation results at `evaluations/`, reports at `reports/` |
| SNS Topic | Error notifications + DLQ threshold alerts |
| SSM Parameters | Runtime config under `/prescoach/{env}/agentic-evaluation/` |
| DynamoDB status updates | Uses existing submissions table (shared) |
| Bedrock AgentCore agents | Session Supervisor + Coaching Supervisor registration |

---

## Pipeline Execution Order (Full Deploy)

```
Source → Test (238 tests) → Deploy (CDK)
```

If tests fail, the Deploy stage **will not run**.

---

## When to Use Each Pipeline

| Scenario | Pipeline to Use |
|----------|----------------|
| Changed evaluation agent logic or models | **Full Deploy** (tests + deploy) |
| Changed only infra (queues, IAM, SSM) | Deploy only |
| Want to validate tests without deploying | Test only |
| First deployment of agentic-evaluation | **Full Deploy** |

---

## Troubleshooting

### Tests fail in the Test stage
Check the CodeBuild logs. Common issues:
- Missing dependency: update `requirements-dev.txt`
- Hypothesis test timeout: increase `deadline` setting
- Moto mock setup: ensure `@mock_aws` decorator is present

### CDK deploy fails
Check the deploy build logs. Common issues:
- Missing IAM permissions on CodeBuild role
- CDK bootstrap not run for this account/region
- CloudFormation stack in ROLLBACK_COMPLETE state (delete it manually first)

### Pipeline is stuck "In Progress"
1. Go to CodeBuild → Build history
2. Find the running build
3. Click "Stop build"
4. Investigate logs
