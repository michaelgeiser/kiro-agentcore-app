# Model Configuration Reference

## Overview

This document lists every AI/ML model used across the Presentation Coaching Platform, where each model ID is defined, and how to change it when models are deprecated or upgraded.

Models have short production lifecycles. This document ensures you can locate and update every model reference when a migration is needed.

---

## Models In Use

| Model ID | Provider | Purpose | Module |
|----------|----------|---------|--------|
| `anthropic.claude-sonnet-4-20250514` | Anthropic (via Bedrock) | Evaluation reasoning — all 7 evaluation agents + Coaching Supervisor | Agentic Evaluation |
| `amazon.nova-2-multimodal-embeddings-v1:0` | Amazon (via Bedrock) | Audio chunk embedding (vectorization) | Preparation Workflow |

---

## 1. Agentic Evaluation Module — Reasoning Models

### Coaching Supervisor

The Coaching Supervisor orchestrates evaluation agents and reasons about which dimensions to evaluate.

| Attribute | Value |
|-----------|-------|
| **Current Model** | `anthropic.claude-sonnet-4-20250514` |
| **Where Set (runtime)** | Environment variable `COACHING_SUPERVISOR_MODEL_ID` |
| **Where Set (infra-as-code)** | `agentic-evaluation/infra/agentic_evaluation_stack.py` → `environment` dict |
| **Where Set (config defaults)** | `agentic-evaluation/src/deployment/agentcore_config.py` → `_ENVIRONMENT_DEFAULTS` |
| **Code that reads it** | `agentic-evaluation/src/deployment/local_runner.py` → reads env var → passes to `CoachingSupervisor(model_id=...)` |
| **Code that uses it** | `agentic-evaluation/src/agents/coaching_supervisor.py` → `Agent(model_id=self._model_id)` |

### Evaluation Agents (7 agents)

Each evaluation agent (delivery, structure, executive_presence, technical_communication, audience_engagement, pacing, persuasion) uses the same model.

| Attribute | Value |
|-----------|-------|
| **Current Model** | `anthropic.claude-sonnet-4-20250514` |
| **Where Set (runtime)** | Environment variable `EVALUATION_MODEL_ID` |
| **Where Set (infra-as-code)** | `agentic-evaluation/infra/agentic_evaluation_stack.py` → `environment` dict |
| **Code that reads it** | Each evaluator file reads `os.environ.get("EVALUATION_MODEL_ID", "anthropic.claude-sonnet-4-20250514")` at module load |
| **Files that use it** | |
| | `agentic-evaluation/src/agents/delivery_evaluator.py` |
| | `agentic-evaluation/src/agents/structure_evaluator.py` |
| | `agentic-evaluation/src/agents/executive_presence_evaluator.py` |
| | `agentic-evaluation/src/agents/technical_communication_evaluator.py` |
| | `agentic-evaluation/src/agents/audience_engagement_evaluator.py` (if exists) |
| | `agentic-evaluation/src/agents/pacing_evaluator.py` (if exists) |
| | `agentic-evaluation/src/agents/persuasion_evaluator.py` (if exists) |

**Note:** The `audience_engagement_evaluator.py`, `pacing_evaluator.py`, and `persuasion_evaluator.py` files follow the same pattern as `delivery_evaluator.py`. If they don't yet have the `EVALUATION_MODEL_ID` variable, they use the Strands SDK default — which should be updated to match.

---

## 2. Preparation Workflow Module — Embedding Model

### Audio Chunk Embedding

Converts audio chunks into vector embeddings for the evaluation agents to retrieve.

| Attribute | Value |
|-----------|-------|
| **Current Model** | `amazon.nova-2-multimodal-embeddings-v1:0` |
| **Where Set (infra-as-code)** | `preparation-workflow/infra/preparation_workflow_stack.py` → `_create_ssm_parameters()` → `"embedding-model-id"` |
| **Where Stored (runtime)** | SSM Parameter Store: `/prescoach/{env}/preparation-workflow/embedding-model-id` |
| **Code that reads it** | `preparation-workflow/src/services/load_config.py` → Lambda reads SSM at runtime |
| **Code that uses it** | `preparation-workflow/src/services/embedding.py` → `bedrock_client.invoke_model(modelId=embedding_model_id)` |
| **Fallback default** | `preparation-workflow/src/services/embedding.py` line 25: `DEFAULT_MODEL_ID = "amazon.nova-2-multimodal-embeddings-v1:0"` |

---

## How to Change a Model

### Changing the Evaluation Reasoning Model (all agents)

**Scenario:** Anthropic releases Claude Sonnet 5, and you want all evaluation agents to use it.

1. **Update the infra stack** (single source of truth for deployment):
   ```python
   # agentic-evaluation/infra/agentic_evaluation_stack.py
   environment={
       ...
       "EVALUATION_MODEL_ID": "anthropic.claude-5-sonnet-20260101",
       "COACHING_SUPERVISOR_MODEL_ID": "anthropic.claude-5-sonnet-20260101",
       ...
   }
   ```

2. **Update the config defaults** (for local development):
   ```python
   # agentic-evaluation/src/deployment/agentcore_config.py
   # Update _ENVIRONMENT_DEFAULTS for each env (dev/staging/prod)
   "model_id": "anthropic.claude-5-sonnet-20260101",
   ```

3. **Update the code defaults** (fallback values in evaluator files):
   ```python
   # In each evaluator file (delivery_evaluator.py, etc.)
   EVALUATION_MODEL_ID = os.environ.get(
       "EVALUATION_MODEL_ID", "anthropic.claude-5-sonnet-20260101"  # <-- update default
   )
   ```

4. **Redeploy:**
   ```bash
   aws codepipeline start-pipeline-execution \
     --name prescoach-dev-kiro-eval-workflow-deploy \
     --region us-east-1
   ```

**No code logic changes needed** — just model ID strings.

### Changing the Embedding Model

**Scenario:** Amazon releases a new Nova Embed model version.

1. **Update the SSM parameter** (instant, no redeploy needed):
   ```bash
   aws ssm put-parameter \
     --name "/prescoach/dev/preparation-workflow/embedding-model-id" \
     --value "amazon.nova-3-multimodal-embeddings-v1:0" \
     --type String \
     --overwrite \
     --region us-east-1
   ```
   Next Step Functions execution will use the new model immediately.

2. **Update the infra stack** (for consistency on fresh deploys):
   ```python
   # preparation-workflow/infra/preparation_workflow_stack.py
   "embedding-model-id": {
       "value": "amazon.nova-3-multimodal-embeddings-v1:0",
       ...
   }
   ```

3. **Update the code default** (fallback):
   ```python
   # preparation-workflow/src/services/embedding.py
   DEFAULT_MODEL_ID = "amazon.nova-3-multimodal-embeddings-v1:0"
   ```

### Using Different Models Per Environment

The `agentcore_config.py` supports per-environment model overrides:

```python
_ENVIRONMENT_DEFAULTS = {
    DeploymentEnvironment.DEV: {
        "session_supervisor": {"model_id": "anthropic.claude-sonnet-4-20250514"},
        "coaching_supervisor": {"model_id": "anthropic.claude-sonnet-4-20250514"},
    },
    DeploymentEnvironment.PROD: {
        "session_supervisor": {"model_id": "anthropic.claude-5-sonnet-20260101"},
        "coaching_supervisor": {"model_id": "anthropic.claude-5-sonnet-20260101"},
    },
}
```

Or override at runtime via environment variables without redeploying code:
```bash
# Update the ECS task definition environment directly
aws ecs update-service ...
```

---

## Model Configuration Hierarchy (Precedence)

```
1. Environment variable (highest priority)
   EVALUATION_MODEL_ID, COACHING_SUPERVISOR_MODEL_ID

2. CDK stack environment dict (set at deploy time)
   agentic-evaluation/infra/agentic_evaluation_stack.py

3. agentcore_config.py _ENVIRONMENT_DEFAULTS (per-environment)

4. Code-level default in each evaluator file (lowest priority)
   os.environ.get("EVALUATION_MODEL_ID", "<default-here>")
```

For the preparation workflow:
```
1. SSM Parameter Store value (highest priority, changeable without deploy)
   /prescoach/{env}/preparation-workflow/embedding-model-id

2. CDK stack parameter definition (set at deploy time)
   preparation-workflow/infra/preparation_workflow_stack.py

3. Code-level DEFAULT_MODEL_ID constant (lowest priority, fallback)
   preparation-workflow/src/services/embedding.py
```

---

## Verification Commands

### Check current model in use (evaluation agents):
```bash
# From ECS task definition
aws ecs describe-task-definition \
  --task-definition prescoach-dev-kiro-eval-task \
  --query 'taskDefinition.containerDefinitions[0].environment[?name==`EVALUATION_MODEL_ID`].value' \
  --output text --region us-east-1

aws ecs describe-task-definition \
  --task-definition prescoach-dev-kiro-eval-task \
  --query 'taskDefinition.containerDefinitions[0].environment[?name==`COACHING_SUPERVISOR_MODEL_ID`].value' \
  --output text --region us-east-1
```

### Check current model in use (embedding):
```bash
aws ssm get-parameter \
  --name "/prescoach/dev/preparation-workflow/embedding-model-id" \
  --query 'Parameter.Value' \
  --output text --region us-east-1
```

### List available Bedrock models:
```bash
# Anthropic models
aws bedrock list-foundation-models \
  --by-provider anthropic \
  --query 'modelSummaries[*].modelId' \
  --output table --region us-east-1

# Amazon embedding models
aws bedrock list-foundation-models \
  --by-provider amazon \
  --query 'modelSummaries[?contains(modelId, `embed`)].modelId' \
  --output table --region us-east-1
```

---

## Model Deprecation Checklist

When a model is announced as deprecated:

- [ ] Identify the replacement model ID from AWS documentation
- [ ] Test the new model locally (`EVALUATION_MODEL_ID=new-model python -m deployment.local_runner`)
- [ ] Update `agentic-evaluation/infra/agentic_evaluation_stack.py` (env vars)
- [ ] Update `agentic-evaluation/src/deployment/agentcore_config.py` (defaults)
- [ ] Update all evaluator files' default strings
- [ ] Update `preparation-workflow/infra/preparation_workflow_stack.py` (if embedding model)
- [ ] Update `preparation-workflow/src/services/embedding.py` DEFAULT_MODEL_ID
- [ ] Update SSM parameter via CLI (for immediate effect without redeploy)
- [ ] Run the full-deploy pipeline to propagate changes
- [ ] Verify with the verification commands above
- [ ] Update this document with the new model IDs
