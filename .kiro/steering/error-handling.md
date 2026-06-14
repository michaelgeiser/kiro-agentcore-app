---
inclusion: always
---

# Error Handling Standards

## Core Principle

Distinguish between **unrecoverable** and **recoverable** errors. Never retry an unrecoverable error — it wastes time, money, and obscures the root cause.

## Unrecoverable Errors (Fail Immediately)

These errors indicate a configuration, code, or input problem. Retrying will never succeed.

- **Invalid parameters** — wrong model ID, malformed input, missing required fields
- **Validation errors** — unsupported file format, schema violations, type mismatches
- **Access denied / permission errors** — IAM misconfiguration, missing policies
- **Resource not found** — wrong table name, wrong queue URL, wrong bucket name, wrong ARN
- **Authentication failures** — expired or invalid credentials configuration
- **Quota exceeded (hard limit)** — account-level limits that won't reset within retry window

### How to Handle
- Return an error immediately with a clear, actionable message
- Log the full error context (input, expected vs actual)
- In Step Functions: do NOT include these error types in Retry configurations
- Route to failure handling for notification and status update

## Recoverable Errors (Retry with Exponential Backoff + Jitter)

These errors are transient — the same request may succeed if retried after a delay.

- **Throttling / rate limits** — TooManyRequestsException, ThrottlingException, 429
- **Service unavailable** — ServiceUnavailableException, 500, 503
- **Network timeouts** — connection timeouts, read timeouts
- **Temporary capacity issues** — ProvisionedThroughputExceededException
- **Concurrent modification conflicts** — ConditionalCheckFailedException (in some cases)

### How to Handle
- Retry with exponential backoff: initial wait × 2^attempt
- Add jitter (randomized delay) to avoid thundering herd
- Set a maximum retry count (typically 3-5)
- Log each retry attempt with the attempt number
- After max retries exhausted, treat as a failure and route to error handling

## Step Functions Retry Configuration

In AWS Step Functions ASL, separate error types in Retry blocks:

```json
"Retry": [
  {
    "ErrorEquals": ["ThrottlingException", "ServiceUnavailableException", "States.Timeout"],
    "IntervalSeconds": 5,
    "BackoffRate": 2.0,
    "MaxAttempts": 3,
    "JitterStrategy": "FULL"
  }
]
```

Do NOT use broad patterns like `States.TaskFailed` or `States.ALL` in Retry blocks — these will retry unrecoverable errors. Instead, use Catch with `States.ALL` to route unrecoverable errors to failure handling.

## Lambda Error Handling Pattern

```python
try:
    result = some_aws_call()
except ClientError as e:
    error_code = e.response["Error"]["Code"]
    if error_code in ("ThrottlingException", "TooManyRequestsException", "ServiceUnavailableException"):
        # Recoverable — raise to let Step Functions retry
        raise
    else:
        # Unrecoverable — return error result, don't raise
        return {"error": error_code, "message": str(e)}
```

## S3 Vector Store Bucket

The vector store endpoint SSM parameter should contain just the bucket name (no `s3://` prefix). The code strips the prefix if present, but prefer storing the clean bucket name.

## Queue URLs

Lambda functions that publish to SQS should get queue URLs from environment variables, not hardcoded values. This ensures the correct queue is used across environments.
