# Agentic Evaluation Processing Flow: Handoff Through Report Generation

## Overview

This document describes the complete processing flow from consuming a handoff message on the SQS FIFO queue through multi-agent evaluation and PDF coaching report generation. It covers every component, queue interaction, S3 object, DynamoDB write, agent invocation, and failure path along the way.

The Agentic Evaluation module is the intelligence layer of the Presentation Coaching Platform. It picks up where the Preparation Workflow left off — consuming the handoff message containing vector store references and orchestrating multiple AI evaluation agents to produce a comprehensive coaching report.

---

## 1. Handoff Message Arrives

The Preparation Workflow publishes a handoff message to the FIFO queue after successfully chunking audio and storing vector embeddings.

**Queue:** `prescoach-dev-preparation-handoff.fifo` (FIFO Queue)

**Message body:**
```json
{
  "submission_id": "sub-98765",
  "user_id": "abc123",
  "s3_file_key": "uploads/abc123/sub-98765/my-presentation.mp3",
  "vector_store_location": "s3://<VECTORS_BUCKET>/sub-98765/embeddings",
  "chunk_count": 3,
  "presentation_title": "Q4 Review"
}
```

**FIFO properties:**
- `MessageGroupId`: `sub-98765` (ensures per-submission ordering)
- FIFO ordering guarantee: messages within a group are processed in exact send order

---

## 2. Session Supervisor: Message Consumption and Lifecycle Management

### 2.1 Queue Polling and Concurrent Processing

The Session Supervisor runs as a containerized task on **ECS Fargate Spot**, consuming messages from the FIFO queue with concurrent processing support. Up to 5 messages (from different MessageGroupIds) are processed simultaneously using a thread pool.

**Concurrency model:**
- A `ThreadPoolExecutor` with `max_concurrent` workers (default: 5) dispatches messages to worker threads
- Each submission_id uses its own MessageGroupId, so ordering within a single submission is guaranteed naturally by SQS FIFO
- Different submissions are processed in parallel across separate threads
- The `MaxNumberOfMessages=1` per poll call ensures clean dispatching

**Configuration (environment variables):**
- `MAX_CONCURRENT_EVALUATIONS`: Max parallel messages (default: 5)
- `IDLE_TIMEOUT_MINUTES`: Inactivity timeout before graceful exit (default: 30)

### 2.1.1 Idle Timeout Behavior

When no messages are received for the configured idle timeout period (default: 30 minutes), the Session Supervisor:
1. Logs the idle timeout event
2. Waits for any in-progress evaluations to complete
3. Exits the process cleanly (exit code 0)

This allows the ECS Fargate Spot task to terminate when there is no work, minimizing cost. The EventBridge rule will launch a new task when messages arrive again.

### 2.1.2 SIGTERM Handling (Spot Reclamation)

When ECS sends a SIGTERM signal (e.g., Fargate Spot 2-minute reclamation warning):
1. The consumer stops accepting new messages immediately
2. In-progress evaluations continue to completion
3. Once all workers finish, the process exits cleanly
4. Any unprocessed messages remain on the queue and will be picked up by the next task

### 2.1.3 ECS Fargate Spot Architecture

The evaluation consumer runs as an ECS Fargate Spot task:
- **Capacity Provider:** FARGATE_SPOT (up to 70% cost savings vs on-demand)
- **Task Size:** 0.5 vCPU, 1 GB memory
- **Desired Count:** 0 (scaled on demand by EventBridge + Lambda)
- **Launch Trigger:** EventBridge rule detects messages on the queue via CloudWatch alarm, invokes a Lambda that checks for already-running tasks before launching a new one
- **Duplicate Prevention:** The `eval-task-launcher` Lambda calls `ecs:ListTasks` to verify no task is already running before calling `ecs:RunTask`
- **Logs:** `/ecs/prescoach-dev-kiro-agentic-evaluation` CloudWatch Log Group

### 2.2 Message Validation

The raw SQS message body is validated against the `HandoffMessage` Pydantic model:
- All string fields must be non-empty (min_length=1)
- `chunk_count` must be ≥ 1
- Internal SQS metadata keys (`_receipt_handle`, `_message_group_id`, `_sequence_number`) are stripped before validation

**On validation failure:**
1. Route original message to Dead Letter Queue (`prescoach-dev-preparation-handoff-dlq.fifo`)
2. Acknowledge (delete) the original message from the main queue
3. Publish error notification to SNS
4. Return `SessionResult` with `status=Failed`

### 2.3 Message Acknowledgment

On successful validation, the message is deleted from the queue before evaluation begins. This:
- Prevents redelivery during the (potentially long) evaluation process
- Unblocks the next message in the FIFO group for delivery
- Shifts responsibility for the submission to the Session Supervisor

### 2.4 Status Update: Evaluating

**DynamoDB Table:** `prescoach-dev-kiro-submissions`  
**Update:** `SET processing_status = "Evaluating", updated_at = <ISO 8601 timestamp>`

---

## 3. Coaching Supervisor: Agent Orchestration

### 3.1 Agent Registry Discovery

The Coaching Supervisor queries the Agent Registry (`agents_manifest.json`) to discover all enabled evaluation agents. The registry provides:

| Dimension | Agent ID | Description |
|-----------|----------|-------------|
| `delivery` | `delivery-evaluator-v1` | Vocal variety, pace, pauses, filler words, energy, projection |
| `structure` | `structure-evaluator-v1` | Logical flow, transitions, organization, intro/conclusion |
| `executive_presence` | `executive-presence-evaluator-v1` | Confidence, authority, gravitas, composure |
| `technical_communication` | `technical-communication-evaluator-v1` | Clarity, terminology, complexity management |
| `audience_engagement` | `audience-engagement-evaluator-v1` | Interaction, storytelling, attention-holding |
| `pacing` | `pacing-evaluator-v1` | Timing, rhythm, speed variation, pauses |
| `persuasion` | `persuasion-evaluator-v1` | Argument strength, evidence, call to action |

Disabled agents (via `enabled: false` in manifest) are excluded at runtime without code changes.

### 3.2 Evaluation Input Construction

For each dimension, an `EvaluationInput` is constructed:
```json
{
  "submission_id": "sub-98765",
  "s3_bucket": "prescoach-dev-kiro-uploads",
  "s3_key": "uploads/abc123/sub-98765/my-presentation.mp3",
  "dimension": "delivery",
  "user_id": "abc123"
}
```

### 3.3 Agent Invocation (Agents as Tools Pattern)

The Coaching Supervisor uses the Strands SDK "Agents as Tools" pattern:
1. Each evaluation agent is wrapped as a callable tool via `@tool` decorator
2. The Coaching Supervisor (a Strands Agent) reasons about which tools to invoke
3. Tools are invoked with JSON-serialized `EvaluationInput`
4. Each tool returns a JSON-serialized `EvaluationResult`

**Invocation flow per agent:**
1. Retrieve relevant embeddings from the S3 vector store
2. Pass embeddings + dimension-specific system prompt to a foundation model
3. Parse the model response into structured findings
4. Return `EvaluationResult` with score (0.0-10.0), findings, strengths, improvements

### 3.4 Iterative Invocation Pattern

After receiving results from initial evaluators, the Coaching Supervisor analyzes findings for keyword triggers that suggest additional dimensions should be evaluated:

| Keywords Found | Triggers Dimension |
|---------------|-------------------|
| "pacing", "pace", "too fast", "too slow" | `pacing` |
| "structure", "organization", "flow" | `structure` |
| "engagement", "audience", "interaction" | `audience_engagement` |
| "persuasion", "convincing", "argument" | `persuasion` |
| "technical", "jargon", "complexity" | `technical_communication` |
| "confidence", "authority", "presence" | `executive_presence` |
| "vocal", "energy", "delivery" | `delivery` |

Already-evaluated dimensions are never invoked a second time.

### 3.5 Agent Failure Handling

When an individual evaluation agent fails:
1. The exception is caught and logged with agent_id and error details
2. An `AgentFailure` record is created (dimension, agent_id, error message)
3. Processing continues with remaining agents
4. Partial results from successful agents are preserved

**Failure tracking:**
```python
AgentFailure(
    dimension="structure",
    agent_id="structure-evaluator-v1",
    error="RuntimeError: LLM invocation timeout after 30s"
)
```

### 3.6 Evaluation Result Structure

Each agent produces:
```json
{
  "dimension": "delivery",
  "score": 7.5,
  "findings": [
    {
      "category": "vocal_variety",
      "detail": "Monotone delivery in the introduction section",
      "severity": "medium",
      "suggestion": "Vary pitch and pace in the opening 30 seconds"
    }
  ],
  "strengths": ["Clear articulation", "Good energy throughout"],
  "improvements": ["Reduce filler words", "Add strategic pauses"],
  "agent_id": "delivery-evaluator-v1",
  "timestamp": "2026-06-16T14:30:22+00:00"
}
```

---

## 4. Result Storage in S3

### 4.1 Evaluation Results

Each `EvaluationResult` is stored as JSON in S3 with exponential backoff retry:

**S3 objects created:**
```
Bucket: prescoach-dev-kiro-uploads (or configured evaluation bucket)
Keys:
  evaluations/{submission_id}/{dimension}/result.json
```

Example:
```
s3://prescoach-dev-kiro-uploads/evaluations/sub-98765/delivery/result.json
s3://prescoach-dev-kiro-uploads/evaluations/sub-98765/structure/result.json
s3://prescoach-dev-kiro-uploads/evaluations/sub-98765/pacing/result.json
...
```

### 4.2 Retry Logic for S3 Writes

Each `put_object` call uses exponential backoff with jitter:
- **Max attempts:** 3
- **Base delay:** 1.0 seconds
- **Backoff multiplier:** 2.0×
- **Max delay:** 30 seconds
- **Jitter:** Random 0-50% of computed delay added

On retry exhaustion:
1. Error notification published to SNS (with `retry_count_exhausted=3`)
2. Failed dimension is skipped — remaining results continue storing
3. Processing continues (partial results are acceptable)

### 4.3 Completeness Verification

After all results are stored, `verify_completeness()` checks that every expected dimension has a corresponding file in S3 via `head_object`. This is used before report generation to confirm data integrity.

---

## 5. Status Update: Report_Generating

**DynamoDB Table:** `prescoach-dev-kiro-submissions`  
**Update:** `SET processing_status = "Report_Generating", updated_at = <ISO 8601 timestamp>`

---

## 6. Report Generation

### 6.1 PDF Construction

The Report Generator uses ReportLab to produce a structured PDF coaching report:

**Sections:**
1. **Title** — "Presentation Coaching Report" + submission ID
2. **Executive Summary** — Overall average score, dimension count, per-dimension scores
3. **Per-Dimension Detailed Feedback** — For each evaluated dimension:
   - Dimension name and score (x/10.0)
   - Findings (with severity, category, suggestion)
   - Strengths (bullet list)
   - Areas for Improvement (bullet list)
4. **Overall Coaching Assessment** — Narrative assessment based on score range:
   - 8.0+ → "Excellent presentation overall..."
   - 6.0-7.9 → "Good presentation with solid fundamentals..."
   - 4.0-5.9 → "The presentation shows promise..."
   - <4.0 → "The presentation has fundamental areas that need attention..."
   - Aggregated key strengths and priority improvements

### 6.2 PDF Storage

**S3 object created:**
```
Bucket: prescoach-dev-kiro-uploads (or configured evaluation bucket)
Key:    reports/{user_id}/{submission_id}/coaching_report.pdf
```

Example:
```
s3://prescoach-dev-kiro-uploads/reports/abc123/sub-98765/coaching_report.pdf
```

---

## 7. Status Update: Completed

**DynamoDB Table:** `prescoach-dev-kiro-submissions`  
**Update:** `SET processing_status = "Completed", report_path = "reports/abc123/sub-98765/coaching_report.pdf", updated_at = <ISO 8601 timestamp>`

**End of happy path.** The session completes.

---

## 8. Complete S3 Objects Created (Happy Path)

| Step | Bucket | Key Pattern | Content |
|------|--------|-------------|---------|
| Evaluation results | `prescoach-dev-kiro-uploads` | `evaluations/{submission_id}/{dimension}/result.json` | EvaluationResult JSON |
| Coaching report | `prescoach-dev-kiro-uploads` | `reports/{user_id}/{submission_id}/coaching_report.pdf` | PDF document |

---

## 9. DynamoDB State Transitions

The evaluation module extends the existing `processing_status` field progression:

```
... → Processing → Completed (Preparation Workflow)
                          ↓
                    Evaluating → Report_Generating → Completed
                          ↘                              ↗
                           Failed ──────────────────────
```

| State | Set By | When |
|-------|--------|------|
| `Evaluating` | Session Supervisor | Handoff message validated and acknowledged |
| `Report_Generating` | Session Supervisor | All evaluation results stored in S3 |
| `Completed` | Session Supervisor | PDF report generated and stored |
| `Failed` | Session Supervisor | Any unrecoverable error (all agents fail, report generation fails) |

---

## 10. Failure Handling

### 10.1 Partial Failure (Some Agents Fail)

If some evaluation agents fail but at least one succeeds:
- Report is **still generated** from available results
- `SessionResult` includes `agent_failures` list with details
- Status transitions to `Completed` (partial results with report)
- Warning logged listing which agents failed

### 10.2 Total Failure (All Agents Fail)

If all evaluation agents fail:
- No report is generated
- Status updates to `Failed` with detailed `failure_reason`
- Failure reason includes which dimensions failed and error details
- SNS notification published with complete failure context
- Stored results (if any) are preserved in S3

### 10.3 Report Generation Failure

If evaluation succeeds but report generation fails:
- Evaluation results are already stored in S3 (not lost)
- Status updates to `Failed` with reason "Report generation failed: ..."
- SNS notification published

### 10.4 SNS Error Notification Format

Published to topic: `prescoach-dev-evaluation-errors` (or shared error topic)

```json
{
  "submission_id": "sub-98765",
  "component_name": "SessionSupervisor",
  "error_type": "EvaluationSessionFailed",
  "error_message": "All evaluation agents failed — no results obtained. Failed dimensions: ['delivery', 'structure']. Agent failure details: delivery-evaluator-v1 (delivery): LLM timeout; structure-evaluator-v1 (structure): Vector store connection refused",
  "retry_count_exhausted": 0,
  "timestamp": "2026-06-16T14:35:00+00:00"
}
```

### 10.5 Dead Letter Queue Routing

**When:** Invalid handoff messages (fail Pydantic validation)  
**DLQ:** `prescoach-dev-preparation-handoff-dlq.fifo`

Message attributes attached:
- `ErrorReason`: Description of the validation failure

---

## 11. DLQ Threshold Monitoring

A `DLQMonitor` service periodically checks the DLQ message count:
- **Default threshold:** 10 messages
- **Check interval:** 60 seconds
- **Alert mechanism:** SNS notification when count exceeds threshold

**Alert format:**
```json
{
  "alert_type": "DLQ_THRESHOLD_EXCEEDED",
  "queue_url": "https://sqs.us-east-1.amazonaws.com/.../prescoach-dev-preparation-handoff-dlq.fifo",
  "current_message_count": 15,
  "threshold": 10,
  "timestamp": "2026-06-16T14:40:00+00:00"
}
```

---

## 12. Agent Execution Modes: Local vs AgentCore

### Current Deployment: Local Mode (ECS Fargate Spot)

As deployed today, the agents run in **local mode** — `LOCAL_MODE=true` in the ECS task environment. This means:

- Strands `Agent` objects are instantiated in-process inside the container
- When the Coaching Supervisor calls `agent(prompt)`, Strands makes direct `bedrock:InvokeModel` API calls from the ECS task
- No AgentCore registration, no managed endpoints, no AgentCore-managed memory
- Session state lives in-memory for the duration of one evaluation (not persisted between tasks)

**What you get today:**
- Full multi-agent orchestration (Agents as Tools pattern) via Strands SDK
- Claude Sonnet reasoning via direct Bedrock API calls
- Concurrent evaluation of multiple submissions
- Cost-optimized ECS Fargate Spot execution
- Everything works end-to-end without AgentCore provisioning

**What you don't get (vs AgentCore):**
- No built-in session memory persistence across task launches
- No managed auto-scaling of individual agents
- No agent versioning or deployment management via AgentCore console
- No session isolation at the AgentCore level (isolation is at the ECS task level instead)

### When to Switch to AgentCore

Consider migrating to AgentCore when:

| Trigger | Reason |
|---------|--------|
| You need session memory across evaluation restarts | AgentCore persists session context; local mode loses it when the task exits |
| You want per-agent scaling independently | AgentCore can scale each evaluation agent separately rather than the whole container |
| AgentCore exits preview and pricing is favorable | Currently in preview; pricing/GA status may change |
| You need agent versioning and A/B testing | AgentCore provides managed deployment slots for canary releases |
| You're hitting Bedrock throttling from a single process | AgentCore distributes requests across managed endpoints |
| Production workload exceeds 100+ evaluations/day | At scale, managed infrastructure reduces operational burden |

**Don't switch if:**
- Your workload is light (< 50 evaluations/day) — ECS Spot is far cheaper
- You need fine-grained control over the execution environment
- AgentCore doesn't yet support your region
- You need to run fully offline/locally for development

### How to Switch to AgentCore

**Step 1: Register agents with AgentCore**

```bash
# Register the Session Supervisor agent
aws bedrock-agentcore create-agent \
  --agent-name "prescoach-eval-session-supervisor" \
  --foundation-model-id "anthropic.claude-sonnet-4-6" \
  --instruction "You are the Session Supervisor for a presentation evaluation platform..." \
  --region us-east-1

# Register the Coaching Supervisor agent
aws bedrock-agentcore create-agent \
  --agent-name "prescoach-eval-coaching-supervisor" \
  --foundation-model-id "anthropic.claude-sonnet-4-6" \
  --instruction "You orchestrate evaluation agents to assess presentations..." \
  --region us-east-1
```

(Exact CLI/API may differ — check current AgentCore documentation)

**Step 2: Configure memory**

```bash
# Enable session memory on the Coaching Supervisor
aws bedrock-agentcore update-agent \
  --agent-id <coaching-supervisor-agent-id> \
  --memory-configuration '{"memoryType": "SESSION", "sessionTtlHours": 24}'
```

**Step 3: Update environment variable**

Change `LOCAL_MODE` from `true` to `false` in the CDK stack:

```python
# In agentic-evaluation/infra/agentic_evaluation_stack.py
environment={
    ...
    "LOCAL_MODE": "false",  # <-- Change this
    "AGENTCORE_SESSION_SUPERVISOR_ID": "<agent-id>",
    "AGENTCORE_COACHING_SUPERVISOR_ID": "<agent-id>",
    ...
}
```

**Step 4: Update the local_runner.py to use AgentCore endpoints**

The `deployment/agentcore_config.py` already has the configuration structure. When `LOCAL_MODE=false`, the runner would:
1. Create agents via AgentCore client instead of local Strands instantiation
2. Use AgentCore's `invoke-agent` API instead of direct `InvokeModel`
3. Leverage AgentCore session memory for context persistence

**Step 5: Redeploy**

```bash
aws codepipeline start-pipeline-execution \
  --name prescoach-dev-kiro-eval-workflow-deploy \
  --region us-east-1
```

**Step 6: Verify**

```bash
# Check agent is registered
aws bedrock-agentcore list-agents --region us-east-1

# Check ECS task uses new config
aws ecs describe-task-definition \
  --task-definition prescoach-dev-kiro-eval-task \
  --query 'taskDefinition.containerDefinitions[0].environment' \
  --region us-east-1
```

### Architecture Comparison

```
LOCAL MODE (current):
┌─────────────────────────────────────┐
│  ECS Fargate Spot Container         │
│                                     │
│  SessionSupervisor                  │
│    └─> CoachingSupervisor           │
│          └─> Strands Agent          │
│                └─> bedrock:InvokeModel (direct API calls)
│                                     │
│  All agents run in-process          │
└─────────────────────────────────────┘

AGENTCORE MODE (future):
┌─────────────────────────────────────┐
│  ECS Fargate Spot Container         │
│                                     │
│  SessionSupervisor                  │
│    └─> AgentCore Client             │
│          └─> agentcore:InvokeAgent  │
└───────────────┬─────────────────────┘
                │
                ▼
┌─────────────────────────────────────┐
│  Bedrock AgentCore Runtime          │
│                                     │
│  CoachingSupervisor (managed)       │
│    ├─> DeliveryEvaluator (tool)     │
│    ├─> StructureEvaluator (tool)    │
│    ├─> PacingEvaluator (tool)       │
│    └─> ... (all 7 agents)           │
│                                     │
│  + Session Memory                   │
│  + Auto-scaling                     │
│  + Agent Versioning                 │
└─────────────────────────────────────┘
```

---

## 13. Technology Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Agent Framework | Strands Agents SDK | Multi-agent orchestration with Agents-as-Tools pattern |
| Agent Execution | Local mode (in-process) | Direct `bedrock:InvokeModel` calls from ECS container |
| Agent Execution (future) | Amazon Bedrock AgentCore | Managed deployment, session memory, auto-scaling |
| Foundation Model | Claude Sonnet (via Bedrock) | Evaluation reasoning and assessment |
| Embedding Retrieval | S3 Vector Store | Presentation content for evaluation context |
| PDF Generation | ReportLab | Coaching report production |
| Queue | SQS FIFO | Ordered message delivery with DLQ |
| Status Storage | DynamoDB | Submission lifecycle tracking |
| Object Storage | S3 | Evaluation results and PDF reports |
| Notifications | SNS | Error alerts and DLQ threshold warnings |
| Configuration | SSM Parameter Store | Runtime configuration |
| Compute | ECS Fargate Spot | Containerized evaluation task execution (cost-optimized) |
| Container Registry | ECR | Docker image storage for evaluation container |
| Scheduling | EventBridge + Lambda | On-demand task launch when messages arrive |
| Logging | CloudWatch Logs | `/ecs/prescoach-dev-kiro-agentic-evaluation` task output |

---

## 14. How to Verify End-to-End Processing

After a handoff message is consumed, check these in order:

### Check 1: DynamoDB status
```bash
aws dynamodb get-item \
  --table-name prescoach-dev-kiro-submissions \
  --key '{"submission_id": {"S": "YOUR_SUBMISSION_ID"}}' \
  --query 'Item.{status:processing_status.S,report:report_path.S}' \
  --output table \
  --region us-east-1
```
Expected: `status=Completed`, `report=reports/...`

### Check 2: Evaluation results in S3
```bash
aws s3 ls s3://prescoach-dev-kiro-uploads/evaluations/YOUR_SUBMISSION_ID/
```
Expected: Directories for each evaluated dimension (e.g., `delivery/`, `structure/`, `pacing/`)

### Check 3: Coaching report PDF
```bash
aws s3 ls s3://prescoach-dev-kiro-uploads/reports/YOUR_USER_ID/YOUR_SUBMISSION_ID/
```
Expected: `coaching_report.pdf`

### Check 4: Download and inspect report
```bash
aws s3 cp s3://prescoach-dev-kiro-uploads/reports/YOUR_USER_ID/YOUR_SUBMISSION_ID/coaching_report.pdf ./report.pdf
```
Open the PDF to verify it contains Executive Summary, Per-Dimension Feedback, and Overall Coaching Assessment sections.

### Check 5: Verify no DLQ messages (healthy state)
```bash
aws sqs get-queue-attributes \
  --queue-url https://sqs.us-east-1.amazonaws.com/<ACCOUNT_ID>/prescoach-dev-preparation-handoff-dlq.fifo \
  --attribute-names ApproximateNumberOfMessages \
  --region us-east-1
```
Expected: `0` (no messages in DLQ)

---

## 15. Module Structure

```
agentic-evaluation/
├── Dockerfile                          # ECS Fargate Spot container image
├── src/
│   ├── agents/
│   │   ├── agents_manifest.json        # Agent registry configuration (7 dimensions)
│   │   ├── base_evaluator.py           # Base class + tool wrapper factory
│   │   ├── coaching_supervisor.py      # Orchestration agent (Agents as Tools)
│   │   ├── delivery_evaluator.py       # Delivery assessment agent
│   │   ├── structure_evaluator.py      # Structure assessment agent
│   │   ├── executive_presence_evaluator.py
│   │   ├── technical_communication_evaluator.py
│   │   ├── audience_engagement_evaluator.py
│   │   ├── pacing_evaluator.py
│   │   ├── persuasion_evaluator.py
│   │   ├── registry.py                 # Configuration-driven agent discovery
│   │   └── session_supervisor.py       # Top-level lifecycle orchestrator (concurrent, idle timeout)
│   ├── deployment/
│   │   ├── agentcore_config.py         # Bedrock AgentCore configuration
│   │   └── local_runner.py             # Local dev + ECS Fargate entry point
│   ├── models/
│   │   └── data_models.py             # Pydantic models (HandoffMessage, EvaluationResult, etc.)
│   └── services/
│       ├── dlq_monitor.py              # DLQ threshold alerting
│       ├── error_notifier.py           # Best-effort SNS notifications
│       ├── report_generator.py         # PDF coaching report (ReportLab)
│       ├── retry.py                    # Exponential backoff with jitter
│       ├── sqs_consumer.py             # FIFO queue consumption
│       └── status_manager.py           # DynamoDB status transitions
├── infra/
│   └── agentic_evaluation_stack.py     # CDK: ECS Fargate Spot, ECR, Lambda launcher, EventBridge
├── tests/
│   ├── properties/                     # 30 Hypothesis property-based tests
│   ├── unit/                           # 196 unit tests
│   └── integration/                    # 12 integration tests (moto)
├── pyproject.toml
├── requirements.txt
└── requirements-dev.txt
```

---

## 16. CI/CD Pipeline

Three CodePipeline pipelines automate testing and deployment:

| Pipeline | What It Does | Duration |
|----------|-------------|----------|
| `prescoach-dev-kiro-eval-workflow-test` | Runs 238 tests | ~2-4 min |
| `prescoach-dev-kiro-eval-workflow-deploy` | Builds Docker image → pushes to ECR → CDK deploy | ~5-8 min |
| `prescoach-dev-kiro-eval-workflow-full-deploy` | Test → Docker build → CDK Deploy | ~8-12 min |

The deploy pipeline now includes a `pre_build` phase that:
1. Authenticates to ECR
2. Builds the Docker image from `agentic-evaluation/Dockerfile`
3. Tags with `latest` and the git commit SHA
4. Pushes both tags to ECR

The CDK deploy phase then creates/updates the ECS task definition referencing the `latest` image tag.

Trigger: Manual / CLI (`aws codepipeline start-pipeline-execution`)

See `installations/RUN-EVAL-WORKFLOW-PIPELINE.md` for detailed run instructions.

---

## 17. Monitoring and Observability

### CloudWatch Log Group

All ECS task output is streamed to: `/ecs/prescoach-dev-kiro-agentic-evaluation`

**Key log patterns to monitor:**
- `"Starting queue consumption loop"` — task started successfully
- `"Idle timeout reached"` — task exiting due to inactivity (normal behavior)
- `"SIGTERM received"` — Spot reclamation in progress
- `"Dispatching message for submission_id=..."` — message picked up for processing
- `"Evaluation session completed"` — successful processing
- `"Evaluation session FAILED"` — processing failure

### Key Metrics

| Metric | Source | Alert Condition |
|--------|--------|----------------|
| ApproximateNumberOfMessagesVisible | SQS/CloudWatch | > 0 triggers task launch |
| DLQ message count | SQS/CloudWatch | > 10 triggers SNS alert |
| Task running count | ECS/CloudWatch | Used by launcher Lambda to prevent duplicates |
