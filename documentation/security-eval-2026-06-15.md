# Security Assessment: Upload & Storage Web Backend

**Date:** 2026-06-15  
**Scope:** Upload Service (API Gateway, Lambda, S3, DynamoDB, Cognito)  
**Environment:** prescoach-dev-kiro

---

## What's Done Well

| Area | Assessment |
|------|-----------|
| **Authentication** | Solid. Cognito with PKCE (no implicit flow), no client secret (correct for SPA), strong password policy, optional MFA, email verification required. |
| **Authorization** | JWT authorizer on all API routes. user_id extracted from token claims server-side — users can only access their own data. |
| **S3 Bucket** | `BlockPublicAccess.BLOCK_ALL`, S3-managed encryption, CORS locked to single origin. |
| **CORS** | Tight — only `https://kiro.geiserai.com` allowed, specific methods/headers. |
| **Input Validation** | File type whitelist, 500MB max size, metadata required field checks. |
| **IAM** | CDK `grant*` helpers give least-privilege by default. Lambdas only get the permissions they need. |
| **Token Storage** | In-memory only (no localStorage) — resistant to XSS token theft. |
| **Error Responses** | User-friendly messages, no stack traces or internal details leaked to client. Correlation IDs for debugging. |
| **DynamoDB** | PAY_PER_REQUEST (no provisioned capacity to exhaust), queries use KeyConditionExpression (no scans). |

---

## Vulnerabilities & Gaps

### 1. No Rate Limiting / Throttling (HIGH)

There is no rate limiting anywhere. HTTP API Gateway v2 has a default account-level limit of 10,000 requests/second but no per-user or per-route throttling configured. A single authenticated user could:

- Flood POST /submissions creating thousands of DynamoDB records and presigned URLs
- Exhaust Lambda concurrency
- Generate massive S3 storage costs

### 2. No WAF (MEDIUM-HIGH for DDoS)

HTTP API Gateway v2 supports WAF association (via the stage ARN). Without WAF:

- No bot protection
- No IP rate limiting for unauthenticated requests (preflight/OPTIONS)
- No geographic blocking
- No managed rule sets (SQL injection, XSS in headers)
- Only basic AWS Shield Standard (volumetric L3/L4 only, no L7 protection)

### 3. File Name Not Sanitized in S3 Key (MEDIUM)

`generate_file_key` uses the original filename directly:

```python
return f"uploads/{user_id}/{submission_id}/{original_file_name}"
```

A malicious filename like `../../etc/passwd` or one with special characters could cause issues in downstream processing or log injection. The presigned URL constrains the key, but the stored name flows into SQS messages and Lambda processing.

### 4. Presigned URL Scope (LOW-MEDIUM)

The presigned URL is generated before the DynamoDB record is confirmed. If DynamoDB write fails, the compensation action tries to delete the S3 object, but the presigned URL could still be valid for up to 1 hour. A client could still upload to that key.

### 5. No Content-Length Enforcement on S3 PUT (MEDIUM)

The presigned URL constrains `ContentType` but not `Content-Length`. A user could claim `fileSizeBytes: 1000` in the API request (passing validation) then upload a 10GB file via the presigned URL. Add a `Content-Length` condition to the presigned URL generation.

### 6. Self Sign-Up Enabled (LOW for this use case)

Anyone can create an account. Fine for a coaching platform, but means any attacker can get a valid JWT and start making authenticated requests. This amplifies the rate limiting gap.

---

## DDoS Assessment: Should WAF Be Added?

**Recommendation: Yes.**

| Threat | Without WAF | With WAF |
|--------|-------------|----------|
| L7 DDoS (HTTP floods) | Unprotected — only Lambda concurrency limits stop it | Rate-based rules block at edge |
| Bot traffic | No detection | Bot Control managed rules |
| Cost-based attacks | Attacker can trigger Lambda/S3/DDB costs | Blocked before reaching compute |
| Credential stuffing on Cognito | Unprotected | IP rate limiting on auth endpoints |
| Known exploit patterns | No filtering | AWS Managed Rules (Core, SQL, XSS) |

For dev/pilot scale, a basic WAF configuration costs approximately $5-10/month and provides:

- Rate-based rule: 100 requests per 5 minutes per IP
- AWS Managed Rules: Core Rule Set + Known Bad Inputs
- Geographic restriction (optional)

---

## Priority Recommendations

| Priority | Action | Effort |
|----------|--------|--------|
| 1 | **Add API Gateway throttling** — configure route-level throttle in stage settings (e.g., 10 req/sec burst, 5 req/sec steady per route) | Low |
| 2 | **Add WAF** with rate-based rule + AWS Managed Core Rule Set | Medium |
| 3 | **Sanitize filenames** before using in S3 keys (strip path traversal, limit to alphanumeric + safe chars) | Low |
| 4 | **Add Content-Length condition** to presigned URL generation | Low |
| 5 | **Add per-user submission limits** in the upload Lambda (query DDB count before allowing new submission) | Medium |

---

## Current Protection Summary

```
Layer 3/4:  AWS Shield Standard (automatic, free)
Layer 7:    NONE (no WAF, no rate limiting)
Auth:       Cognito JWT (strong)
Data:       S3 encryption at rest, HTTPS in transit
Access:     IAM least-privilege, per-user data isolation
Input:      File type + size validation (partial — no filename sanitization, no content-length enforcement)
```

---

## Notes

- This assessment covers the Upload & Storage Service only. The Preparation Workflow and Agentic Evaluation components have separate security considerations.
- WAF is not currently attached to the HTTP API Gateway v2.
- The webapp is served from a separate hosting mechanism (not assessed here).
