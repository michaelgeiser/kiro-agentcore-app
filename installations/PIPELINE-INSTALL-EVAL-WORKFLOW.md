# CI/CD Pipeline Installation — Agentic Evaluation

## Overview

This document walks you through deploying the CI/CD pipelines for the **Agentic Evaluation** module. These pipelines automate testing and deployment of the evaluation agents, report generation, and supporting infrastructure.

**What gets created:**
- `prescoach-dev-kiro-eval-workflow-test` — runs property, unit, and integration tests (238 tests)
- `prescoach-dev-kiro-eval-workflow-deploy` — deploys agentic-evaluation infrastructure via CDK
- `prescoach-dev-kiro-eval-workflow-full-deploy` — runs tests first, then deploys (recommended)

---

## Prerequisites

- The **Webapp & Upload Service** stack is already deployed (agentic-evaluation shares the DynamoDB submissions table and S3 bucket)
- The **Preparation Workflow** stack is already deployed (provides the handoff FIFO queue that triggers evaluation)
- The GitHub token is already stored in Secrets Manager as `github-token`
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

# Verify preparation-workflow handoff queue exists
aws sqs get-queue-url \
  --queue-name prescoach-dev-kiro-preparation-handoff.fifo \
  --region us-east-1
```

---

## Step 2: Push Latest Code from Laptop

The agentic-evaluation module was developed locally. Push it to GitHub first:

```bash
# From your local machine (laptop)
cd c:\Users\mgeis\Downloads\Agentic-compare\Kiro\kiro-agentcore-app
git push origin main
```

---

## Step 3: Pull Latest Code on CloudShell

```bash
cd ~/prescoach
git fetch origin
git reset --hard origin/main
```

This pulls the new `agentic-evaluation/` module and `cicd/agentic-evaluation/` pipeline definition.

---

## Step 4: Set Up the Virtual Environment

```bash
cd ~/prescoach/cicd/agentic-evaluation

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install CDK Python dependencies
pip install -r requirements.txt --no-cache-dir
```

---

## Step 5: Set Environment Variables

```bash
export CDK_DEFAULT_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
export CDK_DEFAULT_REGION="us-east-1"
```

---

## Step 6: Install CDK CLI (if not already available)

```bash
mkdir -p ~/.npm-global
npm config set prefix '~/.npm-global'
export PATH=~/.npm-global/bin:$PATH
npm install -g aws-cdk@latest
cdk --version
```

---

## Step 7: Deploy the Pipeline Stack

```bash
cd ~/prescoach/cicd/agentic-evaluation
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
prescoach-dev-kiro-agentic-evaluation-cicd.TestPipelineName = prescoach-dev-kiro-eval-workflow-test
prescoach-dev-kiro-agentic-evaluation-cicd.DeployPipelineName = prescoach-dev-kiro-eval-workflow-deploy
prescoach-dev-kiro-agentic-evaluation-cicd.FullDeployPipelineName = prescoach-dev-kiro-eval-workflow-full-deploy
```

---

## Step 8: Verify Pipelines Exist

```bash
aws codepipeline list-pipelines \
  --region us-east-1 \
  --query 'pipelines[?contains(name, `eval-workflow`)].name' \
  --output table
```

Should show:

```
+-------------------------------------------------------+
|  prescoach-dev-kiro-eval-workflow-test                |
|  prescoach-dev-kiro-eval-workflow-deploy              |
|  prescoach-dev-kiro-eval-workflow-full-deploy         |
+-------------------------------------------------------+
```

---

## Step 7: Test — Trigger Full Deploy

```bash
aws codepipeline start-pipeline-execution \
  --name prescoach-dev-kiro-eval-workflow-full-deploy \
  --region us-east-1
```

---

## Step 8: Monitor Progress

```bash
aws codepipeline get-pipeline-state \
  --name prescoach-dev-kiro-eval-workflow-full-deploy \
  --region us-east-1 \
  --query 'stageStates[*].{Stage:stageName,Status:latestExecution.status}' \
  --output table
```

---

## Re-running the Pipeline (Idempotency)

The pipeline is fully idempotent:
- **CDK deploy** uses CloudFormation create-or-update semantics — existing resources update in place, new resources are created
- **SQS queues**: Created if they don't exist, configuration updated if they do
- **SSM parameters**: Overwritten with latest values (PUT semantics)
- **S3 buckets**: Retained across stack updates (RemovalPolicy.RETAIN)
- **DynamoDB table**: Shared with upload-service, not recreated — only table access policies are updated

You can re-run the pipeline at any time without worrying about duplicate resources or state conflicts.

---

## Troubleshooting

### Tests fail in the Test stage
Check the CodeBuild logs:
```bash
BUILD_ID=$(aws codebuild list-builds-for-project \
  --project-name prescoach-dev-kiro-eval-workflow-test \
  --query 'ids[0]' --output text)
aws codebuild batch-get-builds --ids $BUILD_ID \
  --query 'builds[0].logs.deepLink' --output text
```

### CDK deploy fails with "Resource already exists"
This should not happen with CDK's create-or-update semantics. If it does, the resource was created outside of CloudFormation. Import it:
```bash
aws cloudformation import-stack-resources ...
```

### "No space left on device" in CloudShell
```bash
rm -rf ~/prescoach/cicd/agentic-evaluation/.venv
rm -rf ~/.cache/pip
```
