# CI/CD Pipeline Installation — Preparation Workflow

## Overview

This document walks you through deploying the CI/CD pipelines for the **Preparation Workflow** from CloudShell. These pipelines automate testing and deployment of the Step Functions workflow, Lambda functions, SQS queues, and all supporting infrastructure.

**What gets created:**
- `prescoach-dev-kiro-prep-workflow-test` — runs property, unit, and integration tests
- `prescoach-dev-kiro-prep-workflow-deploy` — deploys preparation-workflow infrastructure via CDK
- `prescoach-dev-kiro-prep-workflow-full-deploy` — runs tests first, then deploys (recommended)

---

## Prerequisites

- The **Webapp & Upload Service** stack is already deployed (the preparation workflow shares the DynamoDB table and S3 bucket created by upload-service)
- The GitHub token is already stored in Secrets Manager as `github-token` (done during webapp-upload pipeline installation)
- CDK bootstrap has been run for the target account/region

---

## Step 1: Verify Prerequisites

```bash
# Verify GitHub token exists
aws secretsmanager get-secret-value \
  --secret-id "github-token" \
  --query 'Name' \
  --output text \
  --region us-east-1

# Verify CDK bootstrap exists
aws cloudformation describe-stacks \
  --stack-name CDKToolkit \
  --region us-east-1 \
  --query 'Stacks[0].StackStatus' \
  --output text
```

Both commands should succeed. If either fails, follow the Webapp & Upload Service pipeline installation first (`PIPELINE-INSTALL.md`).

---

## Step 2: Get the Latest Code

```bash
cd ~/prescoach
git fetch origin
git reset --hard origin/main
```

---

## Step 3: Set Up the Virtual Environment

```bash
cd ~/prescoach/cicd/preparation-workflow

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install CDK Python dependencies
pip install -r requirements.txt --no-cache-dir
```

---

## Step 4: Set Environment Variables

```bash
export CDK_DEFAULT_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
export CDK_DEFAULT_REGION="us-east-1"
```

---

## Step 5: Deploy the Pipeline Stack

```bash
cdk deploy \
  -c appName=prescoach \
  -c envName=dev \
  -c instanceId=kiro \
  -c githubRepo="michaelgeiser/kiro-agentcore-app" \
  -c githubBranch="main"
```

Type `y` when prompted to approve IAM changes.

**Expected output:**

```
Outputs:
prescoach-dev-kiro-preparation-workflow-cicd.TestPipelineName = prescoach-dev-kiro-prep-workflow-test
prescoach-dev-kiro-preparation-workflow-cicd.DeployPipelineName = prescoach-dev-kiro-prep-workflow-deploy
prescoach-dev-kiro-preparation-workflow-cicd.FullDeployPipelineName = prescoach-dev-kiro-prep-workflow-full-deploy
```

---

## Step 6: Verify Pipelines Exist

```bash
aws codepipeline list-pipelines \
  --region us-east-1 \
  --query 'pipelines[?contains(name, `prep-workflow`)].name' \
  --output table
```

Should show:

```
+-------------------------------------------------------+
|  prescoach-dev-kiro-prep-workflow-test                |
|  prescoach-dev-kiro-prep-workflow-deploy              |
|  prescoach-dev-kiro-prep-workflow-full-deploy         |
+-------------------------------------------------------+
```

---

## Step 7: Test — Trigger Full Deploy

```bash
aws codepipeline start-pipeline-execution \
  --name prescoach-dev-kiro-prep-workflow-full-deploy \
  --region us-east-1
```

---

## Step 8: Monitor Progress

```bash
# Watch stages
aws codepipeline get-pipeline-state \
  --name prescoach-dev-kiro-prep-workflow-full-deploy \
  --region us-east-1 \
  --query 'stageStates[*].{Stage:stageName,Status:latestExecution.status}' \
  --output table
```

Expected progression:
```
+---------+-----------------------+
|  Stage  |  Status               |
+---------+-----------------------+
|  Source |  Succeeded            |
|  Test   |  InProgress → Succeeded |
|  Deploy |  InProgress → Succeeded |
+---------+-----------------------+
```

---

## Step 9: Verify in AWS Console

1. Go to: https://us-east-1.console.aws.amazon.com/codesuite/codepipeline/pipelines?region=us-east-1
2. Click `prescoach-dev-kiro-prep-workflow-full-deploy`
3. Watch Source → Test → Deploy stages turn green

After successful deployment, verify the Step Functions state machine exists:
```bash
aws stepfunctions list-state-machines \
  --region us-east-1 \
  --query 'stateMachines[?contains(name, `preparation-workflow`)].name' \
  --output text
```

---

## After This Is Done

You can now:
- Run `prescoach-dev-kiro-prep-workflow-full-deploy` for safe test-then-deploy
- Run `prescoach-dev-kiro-prep-workflow-test` to validate changes without deploying
- Run `prescoach-dev-kiro-prep-workflow-deploy` for deploy-only (when you're confident)

See `RUN-PREP-WORKFLOW-PIPELINE.md` for detailed run instructions.

---

## Troubleshooting

### "No space left on device" during pip install

```bash
# Free space from previous installs
rm -rf ~/prescoach/cicd/webapp-upload/.venv
rm -rf ~/prescoach/cicd/preparation-workflow/.venv
rm -rf ~/.cache/pip

# Retry
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt --no-cache-dir
```

### CDK bootstrap error

If you haven't bootstrapped this account/region:
```bash
cdk bootstrap aws://$CDK_DEFAULT_ACCOUNT/$CDK_DEFAULT_REGION \
  -c appName=prescoach -c envName=dev -c instanceId=kiro
```

### "github-token" secret not found

The token was set up during the webapp-upload pipeline installation. Verify:
```bash
aws secretsmanager list-secrets --region us-east-1 --query 'SecretList[*].Name' --output table
```

### Pipeline deploys but Step Function has errors

Check SSM parameters are set correctly:
```bash
aws ssm get-parameters-by-path \
  --path "/prescoach/dev/preparation-workflow/" \
  --region us-east-1 \
  --query 'Parameters[*].{Name:Name,Value:Value}' \
  --output table
```

### Tests pass locally but fail in pipeline

Common cause: The pipeline runs from the repo root, so relative paths must account for `cd preparation-workflow`. Check the buildspec `commands` order.
