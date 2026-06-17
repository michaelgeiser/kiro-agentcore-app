# Remaining Issues: Agentic Evaluation Module

## Status: Infrastructure Complete, Application Logic Needs Fixes

The full end-to-end infrastructure is deployed and working:
- ✅ SQS FIFO queue consumption
- ✅ ECS Fargate Spot task auto-launch (EventBridge → Lambda → RunTask)
- ✅ 30-minute idle timeout + concurrent processing
- ✅ Bedrock model invocation (us.anthropic.claude-sonnet-4-6)
- ✅ DynamoDB status transitions (Evaluating → Report_Generating → Completed)
- ✅ PDF report generation and S3 upload
- ✅ SNS error notifications
- ✅ CI/CD pipeline with post-deploy alarm reset

**The pipeline runs end-to-end but produces an empty report because evaluation results aren't being captured.**

---

## Priority 1 (Critical): Coaching Supervisor Returns 0 Results

**Symptom:** `Coaching evaluation completed... Collected 0 result(s), 0 failure(s)`

**Root cause:** The Strands Agent orchestration succeeds (no exception) but the response parsing in `_extract_results_from_response()` can't find valid `EvaluationResult` JSON in the agent's output. The agent's response text doesn't match the regex pattern `\{[^{}]*"dimension"[^{}]*\}` that the parser searches for.

**Why:** The Coaching Supervisor's Strands Agent is asked to invoke evaluation tools, but since the tools themselves return partial/malformed results (due to empty content from Issue 2), the agent returns a conversational summary rather than structured JSON.

**Fix options:**
- A) **Skip agent orchestration, use direct tool invocation only:** The `_direct_invoke_tools()` fallback already works correctly when tools return proper JSON. Force it to always use direct invocation instead of the Strands Agent orchestration layer. Simpler and more reliable.
- B) **Fix the response parser** to handle the Strands Agent's response format (tool call results are embedded in the conversation history, not in the final text response).

**Files to change:**
- `agentic-evaluation/src/agents/coaching_supervisor.py` → `_invoke_agent()` method

**Recommendation:** Option A — it's simpler, more deterministic, and avoids the complexity of parsing agent conversational output.

---

## Priority 2 (Critical): Vector Store Retrieval Uses Wrong Parameter

**Symptom:** `Failed to retrieve content from vector store: Value 'uploads/e498e408.../1_Introducing AgentCore.mp3' at 'knowledgeBaseId' failed to satisfy constraint`

**Root cause:** Each evaluator's `_retrieve_content()` method calls `bedrock-agent-runtime:Retrieve` with `input.s3_key` as the `knowledgeBaseId`. The `s3_key` is the uploaded file path (e.g., `uploads/user/sub/file.mp3`), not a Bedrock Knowledge Base ID.

**The real architecture:** The preparation workflow stores embeddings as JSON files in S3 at `{submission_id}/embeddings/chunk_NNNN.json`. There is no Bedrock Knowledge Base — the "vector store" is just S3 files. The evaluators need to read these files directly from S3 rather than calling the Bedrock Knowledge Base API.

**Fix:** Replace `_retrieve_content()` in all evaluator agents to:
1. Read the embedding JSON files from S3 at `{vector_store_location}` (passed in the handoff message)
2. The embeddings contain metadata with `chunk_timestamp_start`, `chunk_timestamp_end`
3. Since the embeddings are vector representations (not text), the evaluators should use the original audio S3 path or use Bedrock to transcribe/analyze the audio directly

**Alternative fix:** Set up an actual Bedrock Knowledge Base backed by the S3 embeddings bucket — but this is a larger infrastructure task.

**Files to change:**
- `agentic-evaluation/src/agents/delivery_evaluator.py` → `_retrieve_content()`
- `agentic-evaluation/src/agents/structure_evaluator.py` → `_retrieve_content()`
- `agentic-evaluation/src/agents/executive_presence_evaluator.py` → `_retrieve_content()`
- `agentic-evaluation/src/agents/technical_communication_evaluator.py` → `_retrieve_content()`
- `agentic-evaluation/src/agents/audience_engagement_evaluator.py` → `_retrieve_content()`
- `agentic-evaluation/src/agents/pacing_evaluator.py` → `_retrieve_content()`
- `agentic-evaluation/src/agents/persuasion_evaluator.py` → `_retrieve_content()`

**Recommendation:** For MVP, have the evaluators pass the audio S3 URI directly to Bedrock (Claude can process audio via multimodal input). The embeddings are for RAG retrieval, but Claude Sonnet 4 can evaluate audio directly if passed the S3 URI in the prompt.

---

## Priority 3 (Medium): Individual Evaluator Response Parsing

**Symptom:** Even when an evaluator runs successfully with the model, the `_parse_response()` method may fail to extract JSON from the LLM's text response.

**Root cause:** The LLM may wrap JSON in markdown code blocks (```json ... ```) or include preamble text before the JSON. The current regex `\{.*\}` with `re.DOTALL` is greedy and may match incorrectly.

**Fix:** Improve `_parse_response()` to:
1. Try `json.loads(response_text)` first (if response is pure JSON)
2. Try extracting from markdown code block: `` ```json\n{...}\n``` ``
3. Try the regex approach as last resort
4. Add logging when parsing fails to show what the LLM actually returned

**Files to change:**
- All 7 evaluator files → `_parse_response()` method (or move to `base_evaluator.py` as a shared method)

---

## Priority 4 (Low): DLQ Name Mismatch in CDK Stack

**Symptom:** DLQ monitoring alarm may not work if the DLQ name doesn't match the actual queue.

**Status:** Already fixed locally (changed to `prescoach-dev-preparation-dlq-handoff.fifo`), needs to be deployed.

**Files:** `agentic-evaluation/infra/agentic_evaluation_stack.py`

---

## Priority 5 (Low): Missing 3 Evaluator Agent Tool Files in Manifest Path

**Symptom:** `No loaded tool found with name=audience_engagement_evaluator_tool` (previously seen)

**Status:** Already fixed — files created. Verify they're in the deployed Docker image.

---

## Recommended Fix Order

1. **Fix Priority 1** — Force direct tool invocation (bypass Strands Agent orchestration)
2. **Fix Priority 2** — Change `_retrieve_content()` to read from S3 or pass audio directly to Claude
3. **Fix Priority 3** — Improve JSON response parsing
4. Deploy and test end-to-end with a fresh upload

After these 3 fixes, the pipeline should produce a meaningful coaching report.

---

## Quick Validation Test

After fixes are deployed, upload a new file and check:

```powershell
# Wait ~2 minutes for processing, then check status
aws dynamodb get-item --table-name prescoach-dev-kiro-submissions --key "{\"submission_id\":{\"S\":\"YOUR_ID\"}}" --query "Item.{status:processing_status.S,report:report_path.S}" --output table --region us-east-1

# Check evaluation results were stored
aws s3 ls s3://prescoach-dev-kiro-uploads/evaluations/YOUR_SUBMISSION_ID/

# Download and inspect the report
aws s3 cp s3://prescoach-dev-kiro-uploads/reports/YOUR_USER_ID/YOUR_SUBMISSION_ID/coaching_report.pdf ./report.pdf
```
