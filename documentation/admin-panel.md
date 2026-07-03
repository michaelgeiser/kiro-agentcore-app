# Administration Panel

## Overview

The Administration Panel is a role-gated feature of the Presentation Coaching Platform that provides administrators with the ability to view and modify runtime environment variables and toggle feature flags — all without requiring a code redeployment.

**Who can access it:** Only users belonging to the Cognito `administrators` group. The panel is invisible to all other authenticated users, both in the UI and at the API level.

**What it does:**
- Displays and edits runtime environment variables (model IDs, timeouts, concurrency limits)
- Toggles feature flags on/off for platform capabilities
- Persists all changes to AWS SSM Parameter Store
- Triggers ECS service redeployment when environment variables change

**Visual distinction:** Administration pages use a medium dark gray background (instead of the standard black) so administrators immediately know they are in an admin context.

---

## API Endpoints

All administration endpoints are served by API Gateway v2 (HTTP API) and protected by a Cognito JWT authorizer. The base path is `/admin`.

### GET /admin/environment-variables

Retrieves all configurable environment variables with current values, descriptions, and input type hints.

**Request:** No body required. Authorization header with valid JWT from an administrators group member.

**Response (200):**

```json
{
  "variables": [
    {
      "name": "SESSION_SUPERVISOR_MODEL_ID",
      "value": "us.anthropic.claude-sonnet-4-6",
      "description": "Foundation model used by the Session Supervisor agent",
      "inputType": "model-dropdown"
    },
    {
      "name": "COACHING_SUPERVISOR_MODEL_ID",
      "value": "us.anthropic.claude-sonnet-4-6",
      "description": "Foundation model used by the Coaching Supervisor agent",
      "inputType": "model-dropdown"
    },
    {
      "name": "EVALUATION_MODEL_ID",
      "value": "us.amazon.nova-pro-v1:0",
      "description": "Foundation model used by the individual evaluation agents",
      "inputType": "model-dropdown"
    },
    {
      "name": "IDLE_TIMEOUT_MINUTES",
      "value": "30",
      "description": "Minutes of inactivity before the ECS evaluation task exits",
      "inputType": "text"
    },
    {
      "name": "MAX_CONCURRENT_EVALUATIONS",
      "value": "5",
      "description": "Maximum number of submissions processed simultaneously",
      "inputType": "concurrency-dropdown"
    },
    {
      "name": "COGNITO_USER_POOL_NAME",
      "value": "prescoach-user-pool",
      "description": "Name of the Cognito User Pool for user lookups",
      "inputType": "text"
    }
  ]
}
```

**Input types:**
- `model-dropdown` — renders as a `<select>` populated with the hardcoded MODEL_OPTIONS list
- `concurrency-dropdown` — renders as a `<select>` with options [1, 2, 3, 5, 10]
- `text` — renders as a free-text `<input>`

---

### PUT /admin/environment-variables

Persists changed environment variables to SSM, updates the ECS task definition, and triggers a force-new-deployment.

**Request:**

```json
{
  "variables": {
    "SESSION_SUPERVISOR_MODEL_ID": "us.amazon.nova-pro-v1:0",
    "IDLE_TIMEOUT_MINUTES": "45"
  }
}
```

Only include variables that have actually changed. The backend validates variable names and model IDs against the allowed lists.

**Response (200):**

```json
{
  "updatedVars": ["SESSION_SUPERVISOR_MODEL_ID", "IDLE_TIMEOUT_MINUTES"],
  "deploymentStatus": "triggered",
  "message": "Configuration saved. ECS service redeployment triggered — new tasks will use updated values within minutes."
}
```

**Possible `deploymentStatus` values:**
- `"triggered"` — force-new-deployment was successfully initiated
- `"skipped_no_running_tasks"` — SSM and task definition updated, but no ECS deployment triggered because desired_count is 0

**Error responses:**
- `400` — Invalid variable name or invalid model ID
- `403` — Caller is not in the administrators group

---

### GET /admin/feature-flags

Retrieves all feature flags with their current boolean state and descriptions.

**Request:** No body required. Authorization header with valid JWT.

**Response (200):**

```json
{
  "flags": [
    {
      "name": "video-processing-enabled",
      "enabled": true,
      "description": "Allow video file uploads to be processed (audio extraction via MediaConvert)"
    },
    {
      "name": "batch-processing-enabled",
      "enabled": false,
      "description": "Enable batch processing mode for embedding creation"
    },
    {
      "name": "embeddings-enabled",
      "enabled": true,
      "description": "Create vector embeddings from audio chunks during preparation (when disabled, evaluation uses transcript only)"
    },
    {
      "name": "local-mode",
      "enabled": false,
      "description": "Run evaluation agents in local mode (in-process Bedrock calls) vs. AgentCore managed mode"
    }
  ]
}
```

---

### PUT /admin/feature-flags/{flag-name}

Toggles a single feature flag.

**Request:**

```json
{
  "enabled": false
}
```

**Response (200):**

```json
{
  "name": "embeddings-enabled",
  "enabled": false
}
```

**Error responses:**
- `404` — Unknown flag name
- `403` — Caller is not in the administrators group

---

## Environment Variables

### Storage

Environment variables are stored in AWS SSM Parameter Store under the path prefix:

```
/prescoach/{env}/admin/env-vars/
```

Each variable is stored as a `String` type parameter:

| Parameter Name | Type | Description |
|---|---|---|
| `SESSION_SUPERVISOR_MODEL_ID` | Bedrock model ID | Foundation model for the Session Supervisor agent |
| `COACHING_SUPERVISOR_MODEL_ID` | Bedrock model ID | Foundation model for the Coaching Supervisor agent |
| `EVALUATION_MODEL_ID` | Bedrock model ID | Foundation model for individual evaluation agents |
| `IDLE_TIMEOUT_MINUTES` | Numeric string | Minutes of inactivity before ECS task exits |
| `MAX_CONCURRENT_EVALUATIONS` | Numeric string | Max simultaneous submission processing |
| `COGNITO_USER_POOL_NAME` | String | Cognito User Pool name for user lookups |

SSM Parameter Store is the **source of truth**. The GET endpoint reads from SSM (not from the ECS task definition), ensuring the displayed values are always current even during deployments.

### Persistence and Deployment Flow

When an administrator saves changes via `PUT /admin/environment-variables`:

1. **SSM Update** — Each changed variable is written to its SSM parameter via `PutParameter` (overwrite mode)
2. **Task Definition Update** — The Lambda calls `DescribeTaskDefinition` to get the current definition, then `RegisterTaskDefinition` with the updated environment variables, creating a new revision
3. **Force Deployment** — The Lambda calls `DescribeServices` to check `desiredCount`:
   - If `desiredCount > 0`: calls `UpdateService` with `forceNewDeployment=true` and the new task definition ARN
   - If `desiredCount == 0`: skips the force-deployment (no running tasks to replace)
4. **Response** — Returns the list of updated variables and deployment status

If any step after SSM write fails (e.g., ECS API error), the SSM values are already persisted. The next manual deployment will pick up the new values (eventual consistency).

---

## Feature Flags

### Storage

Feature flags are stored in SSM Parameter Store under the path prefix:

```
/prescoach/{env}/feature-flags/
```

Each flag is stored as a `String` with value `"true"` or `"false"`:

| Flag Name | Description |
|---|---|
| `video-processing-enabled` | Allow video file uploads to be processed (audio extraction via MediaConvert) |
| `batch-processing-enabled` | Enable batch processing mode for embedding creation |
| `embeddings-enabled` | Create vector embeddings from audio chunks during preparation |
| `local-mode` | Run evaluation agents in local mode vs. AgentCore managed mode |

### How Flags Take Effect

Feature flags do **not** trigger an ECS redeployment. Instead, they take effect through:

- **Lambda functions** — Flags are read from SSM at cold start. Changes take effect on the next cold start (typically within minutes as Lambda recycles instances, or immediately for new invocations that spin up fresh containers).
- **Step Functions executions** — New executions read the current flag values from SSM at the start of each execution. In-progress executions are not affected until they complete and a new execution begins.

This means flag changes propagate naturally without any redeployment, though there may be a brief window (seconds to minutes) where different Lambda instances serve different flag values during cold-start rotation.

---

## Security Model

The administration panel uses a layered security approach:

### Layer 1: Cognito Group Membership

Users must belong to the `administrators` group in the Cognito User Pool. This group membership is encoded in the JWT token's `cognito:groups` claim.

- Non-admin users never see the Administration menu in the UI
- Non-admin users cannot navigate to admin routes even via direct URL

### Layer 2: API Gateway JWT Authorizer

All `/admin/*` routes are protected by the existing API Gateway v2 JWT authorizer (Cognito). This verifies:
- Token signature validity
- Token expiration
- Token issuer matches the configured User Pool

### Layer 3: Lambda Defense-in-Depth Verification

Each admin Lambda handler independently verifies that the `cognito:groups` claim in the JWT contains `"administrators"` before processing any request. This provides defense in depth — even if the API Gateway authorizer were misconfigured or bypassed, the Lambda itself rejects non-admin callers.

```python
# Simplified verification logic
claims = event["requestContext"]["authorizer"]["jwt"]["claims"]
groups = claims.get("cognito:groups", [])
if "administrators" not in groups:
    return {"statusCode": 403, "body": json.dumps({"error": "Forbidden"})}
```

### Layer 4: Least-Privilege IAM

The admin Lambda execution role is scoped to only the necessary permissions:
- `ssm:GetParameter`, `ssm:PutParameter` — restricted to `/prescoach/{env}/admin/env-vars/*` and `/prescoach/{env}/feature-flags/*` prefixes
- `ecs:DescribeTaskDefinition`, `ecs:RegisterTaskDefinition` — for the specific task family
- `ecs:UpdateService`, `ecs:DescribeServices` — for the specific cluster and service

No broad `*` permissions are granted.

---

## Supported Models

The following models are available in the model dropdown selectors. Models are listed with both a Cross-Region Inference (CRI) variant and a Single Region variant where applicable.

**CRI (Cross-Region Inference)** distributes Bedrock requests across multiple AWS regions within a geography for higher throughput and availability. CRI model IDs are prefixed with `us.`.

| Display Name | Model ID |
|---|---|
| Amazon Nova Pro CRI | `us.amazon.nova-pro-v1:0` |
| Amazon Nova Pro (Single Region) | `amazon.nova-pro-v1:0` |
| Amazon Nova Lite CRI | `us.amazon.nova-lite-v1:0` |
| Amazon Nova Lite (Single Region) | `amazon.nova-lite-v1:0` |
| Amazon Nova Micro CRI | `us.amazon.nova-micro-v1:0` |
| Amazon Nova Micro (Single Region) | `amazon.nova-micro-v1:0` |
| Claude Sonnet 4 CRI | `us.anthropic.claude-sonnet-4-6` |
| Claude Sonnet 4 (Single Region) | `anthropic.claude-sonnet-4-6` |
| Claude Haiku 3.5 CRI | `us.anthropic.claude-3-5-haiku-20241022-v1:0` |
| Claude Haiku 3.5 (Single Region) | `anthropic.claude-3-5-haiku-20241022-v1:0` |
| Claude Sonnet 3.5 v2 CRI | `us.anthropic.claude-3-5-sonnet-20241022-v2:0` |
| Claude Sonnet 3.5 v2 (Single Region) | `anthropic.claude-3-5-sonnet-20241022-v2:0` |

This list is hardcoded in the frontend (`webapp/js/views/env-vars.js` as `MODEL_OPTIONS`). When new models become available, update this list in the frontend code — no backend changes are required.

If a currently-set model ID does not match any entry in the list (e.g., a legacy model), the dropdown displays a placeholder indicating the value is unrecognized. The Save button is disabled until a valid model is selected.

---

## ECS Deployment

### How Force-New-Deployment Works

When environment variables are updated via the admin panel, the backend triggers an ECS service update with `forceNewDeployment=true`. This causes ECS to:

1. Launch new tasks using the updated task definition (with new environment variable values)
2. Wait for new tasks to reach a healthy state
3. Gracefully drain connections from old tasks
4. Stop old tasks once drained

This is a **rolling deployment** — the service remains available throughout the process. There is no downtime.

### Expected Timeline

- **Task definition registration:** Immediate (seconds)
- **New task launch:** 1–2 minutes (includes container image pull if not cached)
- **Health check passing:** 1–3 minutes (depends on health check configuration)
- **Old task drain and stop:** 1–2 minutes (depends on deregistration delay)
- **Total time to full rollout:** Typically **3–7 minutes**

The admin panel displays the message: *"Configuration saved. ECS service redeployment triggered — new tasks will use updated values within minutes."*

### desired_count = 0 Behavior

When the ECS service has `desiredCount` set to 0 (no tasks running), the backend:

1. Still updates SSM Parameter Store with the new values
2. Still registers a new task definition revision with the updated environment variables
3. **Skips** the `UpdateService` force-deployment call (there are no tasks to replace)
4. Returns `deploymentStatus: "skipped_no_running_tasks"` in the response

The next time the service is scaled up (manually or by auto-scaling), it will use the latest task definition revision which already contains the updated values.
