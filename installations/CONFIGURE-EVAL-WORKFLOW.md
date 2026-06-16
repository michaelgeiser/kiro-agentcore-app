# Configuration Guide: Agentic Evaluation Module

## Overview

This document lists every parameter and prerequisite you need when setting up the Agentic Evaluation module in a new environment. It covers CDK context, environment variables, AWS prerequisites, and Bedrock model access.

---

## Prerequisites (Must Exist Before Deploying)

These resources are created by OTHER stacks and must exist first:

| Resource | Created By | Name Pattern | How to Verify |
|----------|-----------|--------------|---------------|
| SQS FIFO Queue | Preparation Workflow stack | `{appName}-{envName}-preparation-handoff.fifo` | `aws sqs get-queue-url --queue-name prescoach-dev-preparation-handoff.fifo` |
| SQS FIFO DLQ | Preparation Workflow stack | `{appName}-{envName}-preparation-handoff-dlq.fifo` | `aws sqs get-queue-url --queue-name prescoach-dev-preparation-handoff-dlq.fifo` |
| DynamoDB Table | Upload Service stack | `{appName}-{envName}-{instanceId}-submissions` | `aws dynamodb describe-table --table-name prescoach-dev-kiro-submissions` |
| S3 Bucket | Upload Service stack | `{appName}-{envName}-{instanceId}-uploads` | `aws s3 ls s3://prescoach-dev-kiro-uploads` |
| CDK Bootstrap | Any prior CDK deploy | `CDKToolkit` stack | `aws cloudformation describe-stacks --stack-name CDKToolkit` |
| GitHub Token | Secrets Manager | `github-token` | `aws secretsmanager get-secret-value --secret-id github-token --query Name` |
| Bedrock Model Access | AWS Console | Claude Sonnet | See "Bedrock Model Access" section below |

---

## Configuration Parameters

### CDK Context Parameters (passed as `-c` flags)

| Parameter | Description | Default | Constraints | Example |
|-----------|-------------|---------|-------------|---------|
| `appName` | Application identifier | `prescoach` | Lowercase, 3-15 chars | `prescoach` |
| `envName` | Deployment environment | `dev` | Short string (dev/staging/prod) | `prod` |
| `instanceId` | Instance/tenant identifier | `kiro` | Lowercase alphanum + hyphens, 2-20 chars | `main` |
| `githubRepo` | GitHub owner/repo | `michaelgeiser/kiro-agentcore-app` | Format: `owner/repo` | `myorg/myrepo` |
| `githubBranch` | Branch to deploy from | `main` | Valid git branch | `main` |

### Environment Variables (set before deploying)

```bash
# ============================================================
# PASTE THIS BLOCK INTO CLOUDSHELL BEFORE ANY DEPLOYMENT
# ============================================================

# CDK parameters
export APP_NAME="prescoach"
export ENV_NAME="dev"
export INSTANCE_ID="kiro"

# AWS environment
export CDK_DEFAULT_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
export CDK_DEFAULT_REGION="us-east-1"

# Derived (do not edit)
export STACK_NAME="${APP_NAME}-${ENV_NAME}-${INSTANCE_ID}"

# ============================================================
# Verify
# ============================================================
echo ""
echo "=== Agentic Evaluation Configuration ==="
echo "  App Name:       $APP_NAME"
echo "  Environment:    $ENV_NAME"
echo "  Instance ID:    $INSTANCE_ID"
echo "  Stack Name:     $STACK_NAME"
echo "  AWS Account:    $CDK_DEFAULT_ACCOUNT"
echo "  AWS Region:     $CDK_DEFAULT_REGION"
echo "========================================="
```

---

## ECS Task Runtime Environment Variables

These are set automatically by the CDK stack in the ECS task definition. You only need to change them if overriding defaults:

| Variable | Description | Default | Set By |
|----------|-------------|---------|--------|
| `SQS_QUEUE_URL` | Handoff FIFO queue URL | Computed from account/region/queue name | CDK stack |
| `SQS_DLQ_URL` | Dead letter queue URL | Computed from account/region/queue name | CDK stack |
| `DYNAMODB_TABLE_NAME` | Submissions table name | `{appName}-{envName}-{instanceId}-submissions` | CDK stack |
| `S3_BUCKET_NAME` | Evaluation results + reports bucket | `{appName}-{envName}-{instanceId}-uploads` | CDK stack |
| `SNS_TOPIC_ARN` | Error notification topic | Created by this stack | CDK stack |
| `AWS_DEFAULT_REGION` | AWS region for API calls | `us-east-1` | CDK stack |
| `LOCAL_MODE` | Run agents via Strands local (not AgentCore) | `true` | CDK stack |
| `IDLE_TIMEOUT_MINUTES` | Minutes of inactivity before task exits | `30` | CDK stack |
| `MAX_CONCURRENT_EVALUATIONS` | Max parallel message processing | `5` | CDK stack |

### To change idle timeout or concurrency:

Edit `agentic-evaluation/infra/agentic_evaluation_stack.py`, find the `environment` dict in the `add_container` call, and change the values. Redeploy.

---

## SSM Parameters (Created by CDK Stack)

The CDK stack creates these in SSM Parameter Store. They're used by the local runner for configuration discovery:

| Parameter Path | Value | Description |
|---------------|-------|-------------|
| `/{appName}/{envName}/agentic-evaluation/sqs-queue-url` | Queue URL | Handoff FIFO queue |
| `/{appName}/{envName}/agentic-evaluation/sqs-dlq-url` | DLQ URL | Dead letter queue |
| `/{appName}/{envName}/agentic-evaluation/dynamodb-table-name` | Table name | Submissions table |
| `/{appName}/{envName}/agentic-evaluation/s3-bucket-name` | Bucket name | Results/reports bucket |
| `/{appName}/{envName}/agentic-evaluation/sns-topic-arn` | Topic ARN | Error notifications |
| `/{appName}/{envName}/agentic-evaluation/dlq-threshold` | `10` | DLQ alert threshold |
| `/{appName}/{envName}/agentic-evaluation/retry-max-attempts` | `3` | S3 write retry attempts |
| `/{appName}/{envName}/agentic-evaluation/retry-base-delay-seconds` | `1.0` | Retry base delay |
| `/{appName}/{envName}/agentic-evaluation/retry-backoff-multiplier` | `2.0` | Exponential multiplier |
| `/{appName}/{envName}/agentic-evaluation/retry-max-delay-seconds` | `30.0` | Retry delay cap |

---

## Bedrock Model Access

The evaluation agents call Claude Sonnet via Bedrock. You must enable model access in your account:

1. Open the AWS Console → **Amazon Bedrock** → **Model access** (left sidebar)
2. Click **Manage model access**
3. Enable: **Anthropic → Claude 3.5 Sonnet** (or Claude Sonnet 4 if available)
4. Also enable: **Amazon → Nova Embed Multimodal v1** (used by preparation workflow for embeddings)
5. Click **Save changes**
6. Wait for status to show "Access granted" (usually immediate)

**Verify from CLI:**
```bash
aws bedrock list-foundation-models \
  --query 'modelSummaries[?contains(modelId, `claude`)].{id:modelId,status:modelLifecycle.status}' \
  --output table \
  --region us-east-1
```

---

## VPC / Networking Configuration

The ECS Fargate Spot task requires networking (subnets + security groups). The CDK stack uses `assignPublicIp=True` which means:

- The task runs in a **public subnet** with internet access
- No NAT Gateway needed
- No VPC endpoints needed (all AWS API calls go over the internet)

**If you're using a custom VPC**, you'll need to update the `eval-task-launcher` Lambda's environment variables:

| Lambda Env Var | Description | How to Find |
|---------------|-------------|-------------|
| `SUBNETS` | Comma-separated subnet IDs | `aws ec2 describe-subnets --filters "Name=map-public-ip-on-launch,Values=true" --query 'Subnets[*].SubnetId' --output text` |
| `SECURITY_GROUPS` | Comma-separated SG IDs | `aws ec2 describe-security-groups --filters "Name=group-name,Values=default" --query 'SecurityGroups[*].GroupId' --output text` |

If using the **default VPC** (most common for dev), the Lambda will use the account's default VPC subnets. You may need to populate these after the first deploy:

```bash
# Get default VPC subnets
SUBNETS=$(aws ec2 describe-subnets \
  --filters "Name=default-for-az,Values=true" \
  --query 'Subnets[*].SubnetId' \
  --output text | tr '\t' ',')

# Get default security group
SG=$(aws ec2 describe-security-groups \
  --filters "Name=group-name,Values=default" \
  --query 'SecurityGroups[0].GroupId' \
  --output text)

# Update the launcher Lambda
aws lambda update-function-configuration \
  --function-name prescoach-dev-kiro-eval-task-launcher \
  --environment "Variables={ECS_CLUSTER_ARN=<cluster-arn>,TASK_DEFINITION_ARN=<task-def-arn>,SUBNETS=$SUBNETS,SECURITY_GROUPS=$SG,CONTAINER_NAME=eval-container}" \
  --region us-east-1
```

The stack outputs provide the cluster and task definition ARNs after deploy.

---

## IAM Permissions Required

The deploying user needs these permissions (same as listed in `INSTALL.md` Section 0):

| Service | Permissions Needed | Why |
|---------|-------------------|-----|
| CloudFormation | `cloudformation:*` | CDK creates/updates stacks |
| IAM | `iam:*` | CDK creates ECS task roles, Lambda roles |
| ECS | `ecs:*` | Creates cluster, task definition, service |
| ECR | `ecr:*` | Creates repository, pushes Docker images |
| Lambda | `lambda:*` | Creates task-launcher function |
| EventBridge | `events:*` | Creates launch rule |
| CloudWatch | `logs:*`, `cloudwatch:*` | Creates log groups, alarms |
| SSM | `ssm:*` | Creates parameters |
| SNS | `sns:*` | Creates error topic |
| S3 | `s3:*` | CDK asset publishing |
| STS | `sts:AssumeRole` | CDK cross-account role assumption |

**Simplest approach:** `AdministratorAccess` for dev accounts.

---

## Deployment Order (New Environment)

If setting up from scratch, deploy stacks in this order:

```
1. CDK Bootstrap (if not done)
2. Upload Service stack (creates DynamoDB table, S3 bucket, Cognito, API GW)
3. Preparation Workflow stack (creates Step Functions, SQS queues, Lambdas)
4. Agentic Evaluation CI/CD stack (creates CodePipeline pipelines)
5. Agentic Evaluation infra stack (creates ECS, ECR, Lambda launcher, EventBridge)
```

Steps 4 and 5 are handled by the CI/CD pipeline after step 4 is deployed. The pipeline's deploy stage runs step 5.

---

## Quick Deploy Sequence (Copy-Paste)

After prerequisites exist and environment variables are set:

```bash
# 1. Deploy the CI/CD pipeline stack (creates the pipelines)
cd ~/prescoach/cicd/agentic-evaluation
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt --no-cache-dir

cdk deploy \
  -c appName=$APP_NAME \
  -c envName=$ENV_NAME \
  -c instanceId=$INSTANCE_ID \
  -c githubRepo="michaelgeiser/kiro-agentcore-app" \
  -c githubBranch="main"

# 2. Trigger the deploy pipeline (builds Docker, deploys infra)
aws codepipeline start-pipeline-execution \
  --name ${STACK_NAME}-eval-workflow-deploy \
  --region $CDK_DEFAULT_REGION

# 3. Monitor progress
aws codepipeline get-pipeline-state \
  --name ${STACK_NAME}-eval-workflow-deploy \
  --region $CDK_DEFAULT_REGION \
  --query 'stageStates[*].{Stage:stageName,Status:latestExecution.status}' \
  --output table
```

---

## Changing Parameters for a New Environment

To deploy to `prod` instead of `dev`:

```bash
export ENV_NAME="prod"
export INSTANCE_ID="main"
# Re-run the deploy sequence above
```

All resources will be created with the `prescoach-prod-main-*` prefix. No conflicts with the dev environment.

---

## Tunable Parameters Reference

| Parameter | Where to Change | Effect | Restart Required |
|-----------|----------------|--------|-----------------|
| Idle timeout | `IDLE_TIMEOUT_MINUTES` in CDK stack | How long task stays alive without messages | Yes (redeploy) |
| Max concurrency | `MAX_CONCURRENT_EVALUATIONS` in CDK stack | Parallel submissions processed | Yes (redeploy) |
| DLQ threshold | SSM `dlq-threshold` or CDK stack | When DLQ alarm fires | No (SSM) / Yes (CDK) |
| Retry attempts | SSM `retry-max-attempts` | S3 write retry count | No (SSM) |
| Retry delay | SSM `retry-base-delay-seconds` | Initial retry wait | No (SSM) |
| Agent enable/disable | `src/agents/agents_manifest.json` | Which evaluators run | Yes (rebuild image) |
| ECS task size | CDK `cpu`/`memory_limit_mib` | Container resources | Yes (redeploy) |
| Fargate Spot vs On-Demand | CDK capacity provider strategy | Cost vs reliability | Yes (redeploy) |

---

## Verify Everything Is Working

After deployment, run this checklist:

```bash
# 1. ECR repo exists and has an image
aws ecr describe-images \
  --repository-name ${STACK_NAME}-agentic-evaluation \
  --query 'imageDetails[0].imageTags' \
  --output text \
  --region $CDK_DEFAULT_REGION

# 2. ECS cluster exists
aws ecs describe-clusters \
  --clusters ${STACK_NAME}-eval-cluster \
  --query 'clusters[0].status' \
  --output text \
  --region $CDK_DEFAULT_REGION

# 3. Task launcher Lambda exists
aws lambda get-function \
  --function-name ${STACK_NAME}-eval-task-launcher \
  --query 'Configuration.FunctionName' \
  --output text \
  --region $CDK_DEFAULT_REGION

# 4. SSM parameters created
aws ssm get-parameters-by-path \
  --path "/${APP_NAME}/${ENV_NAME}/agentic-evaluation/" \
  --query 'Parameters[*].Name' \
  --output table \
  --region $CDK_DEFAULT_REGION

# 5. SNS error topic exists
aws sns list-topics \
  --query "Topics[?contains(TopicArn, 'evaluation-errors')].TopicArn" \
  --output text \
  --region $CDK_DEFAULT_REGION

# 6. CloudWatch log group exists
aws logs describe-log-groups \
  --log-group-name-prefix "/ecs/prescoach" \
  --query 'logGroups[*].logGroupName' \
  --output text \
  --region $CDK_DEFAULT_REGION
```

All 6 should return valid responses. If any fail, check the pipeline deploy logs.
