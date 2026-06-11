# Implementation Plan: Upload and Storage Service

## Overview

Implement the Upload and Storage backend service using Python 3.12 Lambda functions, HTTP API Gateway v2 with native JWT authorizer, S3 presigned URLs for file upload, DynamoDB for metadata persistence, SQS for downstream processing, and SNS for error notifications. Infrastructure is defined using AWS CDK (Python), including a Cognito User Pool for authentication (PKCE flow). Testing uses pytest + hypothesis (PBT) + moto (AWS mocking).

## Tasks

- [x] 1. Set up project structure, dependencies, and shared utilities
  - [x] 1.1 Create project skeleton and dependency files
    - Create `upload-service/` directory with `src/`, `tests/`, `cdk/` subdirectories
    - Create `pyproject.toml` with project metadata and tool configuration (pytest, hypothesis settings)
    - Create `requirements.txt` with: boto3, pydantic>=2.0
    - Create `requirements-dev.txt` with: pytest>=7.4.0, hypothesis>=6.90.0, moto[s3,dynamodb,sqs,sns]>=5.0.0, pytest-cov>=4.1.0
    - Create all `__init__.py` files in `src/handlers/`, `src/services/`, `src/models/`, `src/validation/`, `src/utils/`
    - _Requirements: 9.1_

  - [x] 1.2 Implement shared types and constants (`src/types.py`)
    - Define `ACCEPTED_CONTENT_TYPES` dict mapping audio/video categories to MIME type lists
    - Define `ACCEPTED_EXTENSIONS` list: `.mp3`, `.wav`, `.m4a`, `.aac`, `.mp4`, `.mov`, `.webm`
    - Define `MAX_FILE_SIZE_BYTES = 500 * 1024 * 1024`
    - Define `CORS_HEADERS` dict with `Access-Control-Allow-Origin: https://kiro.geiserai.com`, allowed methods, allowed headers, and max-age
    - _Requirements: 1.3, 1.5_

  - [x] 1.3 Implement ID generator utility (`src/utils/id_generator.py`)
    - Implement `generate_submission_id() -> str` returning a UUID v4 string
    - Implement `generate_correlation_id() -> str` returning a UUID v4 string
    - _Requirements: 4.3, 6.2_

  - [x] 1.4 Implement error response builder (`src/utils/error_response.py`)
    - Implement `build_error_response(status_code: int, code: str, message: str, correlation_id: str) -> dict[str, Any]`
    - Response must include `statusCode`, `headers` (with CORS headers for `https://kiro.geiserai.com`), and JSON `body` containing `error.code`, `error.message`, `error.correlation_id`
    - _Requirements: 6.2_

  - [x] 1.5 Implement file key generator (`src/utils/file_key_generator.py`)
    - Implement `generate_file_key(user_id: str, submission_id: str, original_file_name: str) -> str`
    - Returns `uploads/{user_id}/{submission_id}/{original_file_name}` preserving original file extension
    - _Requirements: 3.2, 3.3_

  - [x] 1.6 Write property test for error response format (Property 7)
    - **Property 7: Error response format consistency**
    - Use `hypothesis` with `st.integers(min_value=400, max_value=599)` for status codes, `st.text(min_size=1)` for code/message/correlation_id
    - Verify response body always contains exactly `error.code`, `error.message`, `error.correlation_id` with matching values
    - Verify CORS headers present with correct `Access-Control-Allow-Origin`
    - **Validates: Requirements 6.2**

  - [x] 1.7 Write property test for file key generation (Property 4)
    - **Property 4: File key generation follows naming convention**
    - Use `st.text(min_size=1, alphabet=st.characters(whitelist_categories=('L', 'N')))` for user_id and submission_id
    - Use `st.sampled_from()` for extensions combined with `st.text()` for base file names
    - Verify output matches `uploads/{user_id}/{submission_id}/{original_file_name}` exactly
    - Verify file extension is preserved
    - **Validates: Requirements 3.2, 3.3**

- [x] 2. Implement validation layer
  - [x] 2.1 Implement file validator (`src/validation/file_validator.py`)
    - Define `FileValidationInput` dataclass with `file_name`, `content_type`, `file_size_bytes`
    - Define `ValidationResult` dataclass with `valid: bool`, `error: str | None`
    - Implement `validate_file(input_data: FileValidationInput) -> ValidationResult`
    - Validate content_type against `ACCEPTED_CONTENT_TYPES` (audio/video MIME types)
    - Validate file_size_bytes <= `MAX_FILE_SIZE_BYTES` (500 MB)
    - Return descriptive error messages for each constraint violation
    - _Requirements: 1.3, 1.4, 1.5_

  - [x] 2.2 Write property test for file validation (Property 1)
    - **Property 1: File validation correctness**
    - Use `st.sampled_from()` for valid/invalid MIME types, `st.integers(min_value=0, max_value=1_073_741_824)` for file sizes
    - Assert: valid=True iff content_type in accepted types AND file_size <= 500 MB
    - Assert: valid=False with descriptive error for invalid content_type or oversized files
    - **Validates: Requirements 1.3, 1.4, 1.5**

  - [x] 2.3 Implement metadata validator (`src/validation/metadata_validator.py`)
    - Define `MetadataInput` dataclass with `presentation_title`, `description`, `original_file_name`
    - Define `FieldError` dataclass with `field: str`, `message: str`
    - Define `MetadataValidationResult` dataclass with `valid: bool`, `errors: list[FieldError]`
    - Implement `validate_metadata(input_data: MetadataInput) -> MetadataValidationResult`
    - Validate `presentation_title` is non-empty, non-whitespace
    - Validate `original_file_name` is present
    - Return field-level errors identifying each missing/invalid field
    - _Requirements: 1.2, 1.6_

  - [x] 2.4 Write property test for metadata validation (Property 2)
    - **Property 2: Metadata validation correctness**
    - Use `st.text()` with whitespace-only strings, `st.none()`, and valid strings
    - Assert: valid=True iff presentation_title is non-empty/non-whitespace AND original_file_name is present
    - Assert: valid=False with errors identifying each invalid field
    - **Validates: Requirements 1.2, 1.6**

- [x] 3. Implement Pydantic data models
  - [x] 3.1 Implement submission record model (`src/models/submission.py`)
    - Define `ProcessingStatus` enum: Pending, Processing, Completed, Failed
    - Define `SubmissionRecord` Pydantic BaseModel with all DynamoDB attributes
    - Define `ErrorNotification` Pydantic BaseModel with: submission_id (Optional), error_type (ErrorType enum), error_message, timestamp, service_component, orphaned_s3_key (Optional)
    - Define `ErrorType` enum: S3_WRITE_FAILURE, DYNAMO_WRITE_FAILURE, SQS_PUBLISH_FAILURE, S3_COMPENSATION_FAILURE
    - _Requirements: 4.2, 8.2_

  - [x] 3.2 Implement SQS message model (`src/models/sqs_message.py`)
    - Define `SqsMessageBody` Pydantic BaseModel with: submission_id, user_id, s3_file_key, original_file_name, presentation_title
    - _Requirements: 5.2_

  - [x] 3.3 Write property test for submission record construction (Property 5)
    - **Property 5: Submission record construction**
    - Use `st.builds(SubmissionRecord)` with hypothesis strategies for each field
    - Assert: submission_id matches UUID v4 regex, processing_status defaults to "Pending", completion_date is None, report_link is None, upload_date is valid ISO 8601
    - **Validates: Requirements 4.2, 4.3**

  - [x] 3.4 Write property test for SQS message body construction (Property 6)
    - **Property 6: SQS message body construction**
    - Use `st.builds(SqsMessageBody)` with random valid submission data
    - Assert: all fields present and values match input data exactly
    - **Validates: Requirements 5.2**

  - [x] 3.5 Write property test for SNS error notification construction (Property 10)
    - **Property 10: SNS error notification construction**
    - Use `st.builds(ErrorNotification)` with `st.none() | st.text()` for submission_id
    - Assert: all required fields present, timestamp is valid ISO 8601, values match inputs
    - **Validates: Requirements 8.2**

- [x] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Implement AWS service layer
  - [x] 5.1 Implement S3 service (`src/services/s3_service.py`)
    - Implement `S3Service` class with boto3 S3 client
    - Implement `generate_presigned_upload_url(file_key: str, content_type: str, expires_in_seconds: int = 3600) -> str`
    - Implement `delete_object(file_key: str) -> None` for compensating action
    - Configure bucket name from environment variable `S3_BUCKET_NAME`
    - _Requirements: 3.1, 3.4, 4.4_

  - [x] 5.2 Implement DynamoDB service (`src/services/dynamo_service.py`)
    - Implement `DynamoService` class with boto3 DynamoDB resource
    - Implement `create_submission(record: SubmissionRecord) -> None` using `put_item`
    - Implement `get_submissions_by_user(user_id: str) -> list[SubmissionRecord]` querying GSI `user-uploads-index` with ScanIndexForward=False for descending sort
    - Implement `update_status(submission_id: str, status: str, **additional_fields) -> None` using `update_item`
    - Configure table name from environment variable `DYNAMODB_TABLE_NAME`
    - _Requirements: 4.1, 4.2, 7.2, 7.4_

  - [x] 5.3 Implement SQS service (`src/services/sqs_service.py`)
    - Implement `SqsService` class with boto3 SQS client
    - Implement `publish_message(message: SqsMessageBody, max_retries: int = 3) -> None`
    - Implement exponential backoff retry: base_delay=0.1s, multiplier=2 (100ms, 200ms, 400ms)
    - Raise after exhausting all retries
    - Configure queue URL from environment variable `SQS_QUEUE_URL`
    - _Requirements: 5.1, 5.3, 5.4_

  - [x] 5.4 Implement SNS service (`src/services/sns_service.py`)
    - Implement `SnsService` class with boto3 SNS client
    - Implement `publish_error_notification(notification: ErrorNotification) -> None`
    - Catch all exceptions silently (best-effort, no re-raise)
    - Configure topic ARN from environment variable `SNS_TOPIC_ARN`
    - _Requirements: 8.1, 8.2, 8.3_

  - [x] 5.5 Write unit tests for SQS retry logic
    - Test exponential backoff timing (100ms, 200ms, 400ms)
    - Test successful publish on first attempt (no retry)
    - Test successful publish on second retry
    - Test failure after all 3 retries exhausted
    - Use `unittest.mock.patch` for boto3 client
    - _Requirements: 5.3, 5.4_

  - [x] 5.6 Write unit tests for SNS best-effort behavior
    - Test successful notification publish
    - Test that boto3 exceptions are caught and do not propagate
    - Use `unittest.mock.patch` for boto3 client
    - _Requirements: 8.3_

- [x] 6. Implement Lambda handlers
  - [x] 6.1 Implement upload handler (`src/handlers/upload.py`)
    - Extract `user_id` from `event["requestContext"]["authorizer"]["jwt"]["claims"]["sub"]` (HTTP API v2 payload format 2.0)
    - Parse JSON body for metadata (title, description, fileName, contentType, fileSizeBytes) — use camelCase field names matching the frontend contract
    - Generate correlation_id at handler entry
    - Validate metadata using `validate_metadata` (map `title` → `presentation_title`, `fileName` → `original_file_name`)
    - Validate file using `validate_file` (map `contentType` → `content_type`, `fileSizeBytes` → `file_size_bytes`)
    - Generate submission_id and file_key
    - Generate presigned S3 PUT URL via `S3Service`
    - Create DynamoDB SubmissionRecord (status: Pending) via `DynamoService`
    - On DynamoDB failure: publish SNS error notification, return 500
    - On success: return 201 with `submissionId`, `presignedUrl`, `status` (camelCase) and CORS headers
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 2.4, 3.1, 3.2, 3.4, 4.1, 4.2, 4.4, 4.5, 6.1, 6.2, 10.2_

  - [x] 6.2 Write property test for user ID extraction (Property 3)
    - **Property 3: User ID extraction from JWT claims**
    - Use `st.fixed_dictionaries()` to generate HTTP API v2 event structures with varying claim values
    - Assert: extracted user_id matches `event["requestContext"]["authorizer"]["jwt"]["claims"]["sub"]` exactly
    - Assert: user_id is always a non-empty string
    - **Validates: Requirements 2.4**

  - [x] 6.3 Implement confirm upload handler (`src/handlers/confirm_upload.py`)
    - Parse S3 event notification to extract bucket and object key
    - Look up submission record by s3_file_key in DynamoDB
    - Build `SqsMessageBody` from submission data
    - Publish message to SQS via `SqsService` (with 3x retry)
    - On SQS failure after retries: update status to Failed, publish SNS error notification
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 8.1_

  - [x] 6.4 Implement get submissions handler (`src/handlers/get_submissions.py`)
    - Extract `user_id` from `event["requestContext"]["authorizer"]["jwt"]["claims"]["sub"]`
    - Query DynamoDB via `DynamoService.get_submissions_by_user(user_id)`
    - Map records to frontend-compatible response format using camelCase field names: `id` (from submission_id), `title` (from presentation_title), `fileName` (from original_file_name), `description`, `dateUploaded` (from upload_date), `status` (from processing_status), `dateCompleted` (from completion_date), `reportUrl` (from report_link)
    - Return 200 with `{ submissions: [...] }` array (empty array if no results) and CORS headers
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 10.1_

  - [x] 6.5 Write property test for submission response mapping (Property 8)
    - **Property 8: Submission response mapping includes all fields**
    - Use `st.builds(SubmissionRecord)` with random data
    - Assert: mapped response includes exactly all 8 required fields with correct values
    - **Validates: Requirements 7.3**

  - [x] 6.6 Write property test for submissions sort order (Property 9)
    - **Property 9: Submissions sorted by upload_date descending**
    - Use `st.lists(st.builds(SubmissionRecord), min_size=2)` with random ISO dates
    - Assert: response items sorted in strictly descending upload_date order
    - **Validates: Requirements 7.4**

- [x] 7. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Implement CDK infrastructure
  - [x] 8.1 Implement Cognito User Pool and App Client (`cdk/upload_service/cognito_construct.py`)
    - Accept `resource_prefix` parameter (constructed from `{appName}-{envName}-{instanceId}`)
    - Define Cognito User Pool named `{resource_prefix}-users` with:
      - Self sign-up enabled
      - Email as sign-in alias and required attribute
      - Password policy: minimum 8 characters, require uppercase, lowercase, numbers, symbols
      - Auto-verified attributes: email
      - Account recovery via email
      - MFA optional (TOTP)
    - Define User Pool Domain (Cognito hosted UI) with prefix `{resource_prefix}`
    - Define User Pool App Client with:
      - OAuth 2.0 Authorization Code Grant with PKCE (no client secret)
      - Scopes: openid, profile, email
      - Callback URL: `https://kiro.geiserai.com` and `http://localhost:5500` (for local dev)
      - Logout URL: `https://kiro.geiserai.com` and `http://localhost:5500`
      - Token validity: access token 1 hour, refresh token 30 days, ID token 1 hour
    - Export User Pool ID, User Pool Client ID, and Cognito Domain as CDK outputs (CfnOutput)
    - _Requirements: 2.1, 2.2, 2.3, 11.1, 11.4_

  - [x] 8.2 Implement CDK stack (`cdk/upload_service/upload_service_stack.py`)
    - Read CDK context parameters: `appName` (default: `prescoach`), `envName` (required), `instanceId` (required)
    - Validate combined prefix `{appName}-{envName}-{instanceId}` does not exceed 40 characters
    - Validate `instanceId` is lowercase alphanumeric + hyphens, 2-20 characters
    - Construct `resource_prefix = f"{app_name}-{env_name}-{instance_id}"`
    - Apply tags (`app`, `env`, `instance`) to all resources via `cdk.Tags.of(self)`
    - Import and instantiate the Cognito construct from 8.1 with `resource_prefix`
    - Define S3 bucket named `{resource_prefix}-uploads` with standard storage class, versioning disabled for MVP
    - Define DynamoDB table named `{resource_prefix}-submissions` with PAY_PER_REQUEST billing, partition key `submission_id` (String), GSI `user-uploads-index` (partition: `user_id`, sort: `upload_date`)
    - Define SQS queue named `{resource_prefix}-processing-queue` with dead-letter queue named `{resource_prefix}-processing-dlq`
    - Define SNS topic named `{resource_prefix}-errors`
    - Define HTTP API Gateway v2 named `{resource_prefix}-api` with native JWT authorizer referencing the Cognito User Pool (issuer URL: `https://cognito-idp.{region}.amazonaws.com/{user_pool_id}`, audience: app client ID)
    - Configure CORS: allow origin `https://kiro.geiserai.com`, methods GET/POST, headers Content-Type/Authorization, max-age 1 day
    - Define Upload Lambda named `{resource_prefix}-upload` (Python 3.12 runtime, handler: `src/handlers/upload.handler`)
    - Define Get Submissions Lambda named `{resource_prefix}-get-submissions` (Python 3.12 runtime, handler: `src/handlers/get_submissions.handler`)
    - Define Confirm Upload Lambda named `{resource_prefix}-confirm-upload` (Python 3.12 runtime, triggered by S3 PutObject event on `uploads/` prefix)
    - Grant appropriate IAM permissions: Upload Lambda → S3 (putObject, getObject, deleteObject), DynamoDB (putItem), SNS (publish); Get Lambda → DynamoDB (query); Confirm Lambda → SQS (sendMessage), DynamoDB (query, updateItem), SNS (publish)
    - Set environment variables on each Lambda: S3_BUCKET_NAME, DYNAMODB_TABLE_NAME, SQS_QUEUE_URL, SNS_TOPIC_ARN
    - Add route POST /submissions → Upload Lambda, GET /submissions → Get Submissions Lambda
    - Output ApiEndpoint as CfnOutput
    - _Requirements: 1.1, 2.1, 2.2, 2.3, 3.1, 4.1, 5.1, 7.1, 8.1, 9.1, 9.2, 9.3, 9.4, 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.8_

  - [x] 8.3 Create CDK app entry point (`cdk/app.py`)
    - Instantiate CDK App
    - Read `appName`, `envName`, `instanceId` from CDK context
    - Construct stack name as `{appName}-{envName}-{instanceId}`
    - Instantiate UploadServiceStack with the context parameters
    - Configure environment (account/region) from context or defaults
    - _Requirements: 9.1, 11.2, 11.3_

  - [x] 8.4 Write CDK assertion tests (`tests/integration/test_cdk_assertions.py`)
    - Assert Cognito User Pool exists with self sign-up enabled
    - Assert Cognito User Pool App Client has no client secret (PKCE flow)
    - Assert Cognito User Pool App Client has Authorization Code Grant flow configured
    - Assert Cognito User Pool Domain is configured
    - Assert DynamoDB table has PAY_PER_REQUEST billing mode
    - Assert DynamoDB table has GSI with correct key schema
    - Assert S3 bucket uses STANDARD storage class
    - Assert HTTP API has JWT authorizer configured with Cognito issuer
    - Assert HTTP API has CORS configured for `https://kiro.geiserai.com`
    - Assert Lambda functions use Python 3.12 runtime
    - Assert S3 event notification configured on Confirm Upload Lambda
    - Assert all resource names follow `{appName}-{envName}-{instanceId}-{resourceName}` convention
    - Assert all resources are tagged with `app`, `env`, and `instance` tags
    - Assert prefix validation rejects combined prefix > 40 characters
    - Assert prefix validation rejects invalid instanceId characters
    - _Requirements: 2.1, 2.2, 2.3, 9.2, 9.3, 11.5, 11.6, 11.8_

- [x] 9. Implement unit tests for handler logic
  - [x] 9.1 Write unit tests for upload handler (`tests/unit/test_upload_handler.py`)
    - Test happy path: valid metadata → presigned URL + DynamoDB record → 201 response with CORS headers
    - Test invalid file type → 400 response with `INVALID_FILE_TYPE` code
    - Test file too large → 413 response with `FILE_TOO_LARGE` code
    - Test missing title → 400 response with `MISSING_REQUIRED_FIELD` code
    - Test DynamoDB failure → SNS notification → 500 response
    - Test presigned URL generation failure → SNS notification → 500 response
    - Use moto for DynamoDB/S3 mocking, `unittest.mock.patch` for service layer
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 3.5, 4.4, 4.5, 6.1, 6.2_

  - [x] 9.2 Write unit tests for confirm upload handler (`tests/unit/test_confirm_upload_handler.py`)
    - Test happy path: S3 event → SQS message published
    - Test SQS failure after 3 retries → status updated to Failed + SNS notification
    - Use moto for SQS/DynamoDB/SNS mocking
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

  - [x] 9.3 Write unit tests for get submissions handler (`tests/unit/test_get_submissions_handler.py`)
    - Test happy path: returns submissions sorted by upload_date descending with CORS headers
    - Test no submissions: returns 200 with empty array
    - Test DynamoDB query failure → 500 response
    - Use moto for DynamoDB mocking
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_

- [x] 10. Implement integration tests
  - [x] 10.1 Write integration test for upload flow (`tests/integration/test_upload_flow.py`)
    - Test end-to-end: POST /submissions with valid input → DynamoDB record created → presigned URL returned
    - Test compensation: simulate DynamoDB failure → verify S3 object deleted
    - Use moto for all AWS service mocking
    - _Requirements: 1.1, 3.1, 4.1, 4.4, 6.1_

- [x] 11. Frontend SPA integration updates
  - [x] 11.1 Create frontend config module (`webapp/js/config.js`)
    - Create `webapp/js/config.js` exporting CONFIG object with `cognitoDomain`, `clientId`, `apiBaseUrl` placeholders
    - Add inline comments documenting which CDK output populates each value
    - _Requirements: 10.4_

  - [x] 11.2 Update frontend auth module to use config (`webapp/js/auth.js`)
    - Import CONFIG from `./config.js`
    - Replace hardcoded placeholder values (`your-app.auth...`, `your-cognito-client-id`) with `CONFIG.cognitoDomain` and `CONFIG.clientId`
    - Ensure `redirectUri` and `logoutUri` continue to use `window.location.origin`
    - _Requirements: 10.4_

  - [x] 11.3 Update frontend API client to use config and presigned URL flow (`webapp/js/api.js`)
    - Import CONFIG from `./config.js` and use `CONFIG.apiBaseUrl` instead of hardcoded `API_BASE_URL`
    - Refactor `uploadSubmission(file, metadata, onProgress)` to use two-step presigned URL flow:
      1. POST JSON metadata (`{ title, description, fileName, contentType, fileSizeBytes }`) to `/submissions`
      2. Parse response to get `submissionId` and `presignedUrl`
      3. PUT file to `presignedUrl` using XMLHttpRequest with progress tracking
    - Remove FormData upload approach (incompatible with presigned URL backend)
    - Remove `getReportUrl(submissionId)` method (report URL is in the submissions list response field `reportUrl`)
    - _Requirements: 10.2, 10.3, 10.6_

  - [x] 11.4 Update frontend List View field mapping (`webapp/js/views/list.js`)
    - Verify `renderSubmissionCard` reads fields using the names returned by the backend: `id`, `title`, `fileName`, `description`, `dateUploaded`, `status`, `dateCompleted`, `reportUrl`
    - The List View already uses these exact field names — verify no changes needed
    - Remove any call to `api.getReportUrl()` if present; use `submission.reportUrl` directly
    - _Requirements: 10.1, 10.6_

  - [x] 11.5 Update frontend Upload Page for presigned URL response (`webapp/js/views/upload.js`)
    - After `api.uploadSubmission()` resolves, it now returns `{ submissionId, presignedUrl, status }` — the file upload to S3 is handled internally by the API client
    - Verify success message and navigation still work correctly
    - _Requirements: 10.3_

  - [x] 11.6 Update frontend tests for presigned URL flow
    - Update `webapp/tests/unit/api.test.js` — test the two-step flow: metadata POST → presigned URL → S3 PUT
    - Update `webapp/tests/unit/upload.test.js` — adjust for new response format
    - Update `webapp/tests/integration/upload-flow.test.js` — test the complete two-step presigned URL flow
    - Ensure all 190+ tests pass after refactoring
    - _Requirements: 10.2, 10.3_

  - [x] 11.7 Add CDK output generation script (`scripts/generate-frontend-config.sh`)
    - Create a shell script that reads CDK outputs (`aws cloudformation describe-stacks`) and generates `webapp/js/config.js` with actual values
    - Script should accept stack name as parameter, default to `UploadServiceStack`
    - Output the populated config.js file ready for deployment
    - _Requirements: 10.4, 10.5_

- [x] 12. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Property tests use hypothesis with `@settings(max_examples=100)` for sufficient coverage
- All hypothesis property tests include tag comment: `# Feature: upload-and-storage, Property N: <title>`
- Unit tests use moto for AWS service mocking (no real AWS calls)
- CORS headers (`Access-Control-Allow-Origin: https://kiro.geiserai.com`) must be included in all Lambda responses
- The presigned URL approach ensures file uploads bypass WAF body inspection limits
- SQS retry uses exponential backoff: 100ms → 200ms → 400ms (3 attempts)
- Checkpoints ensure incremental validation throughout implementation
- Task group 11 (Frontend SPA integration) modifies files in the `webapp/` directory from the frontend-spa spec — these tasks align the frontend with the backend's presigned URL flow, API field naming, and CDK-output-based configuration
- The GET /submissions response uses camelCase field names (`id`, `title`, `fileName`, etc.) to match the Frontend SPA's JavaScript conventions; the backend maps from snake_case DynamoDB attributes

## Post-Completion: Deployment Session

After all tasks in this spec are complete, begin a collaborative session to build multi-environment IaC and deployment code. Goals:
- Support dev/test/prod environments (or user-defined names) in same or different AWS accounts
- Parameterize environment-specific values (domain, callbacks, CORS, account/region)
- Deploy frontend SPA (S3/CloudFront) and backend as a coordinated unit
- Produce self-contained example code that others can clone → configure → deploy
- See `.kiro/steering/deployment-session.md` for full scope

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.3"] },
    { "id": 2, "tasks": ["1.4", "1.5"] },
    { "id": 3, "tasks": ["1.6", "1.7", "2.1", "2.3", "3.1", "3.2"] },
    { "id": 4, "tasks": ["2.2", "2.4", "3.3", "3.4", "3.5"] },
    { "id": 5, "tasks": ["5.1", "5.2", "5.3", "5.4"] },
    { "id": 6, "tasks": ["5.5", "5.6", "6.1", "6.4"] },
    { "id": 7, "tasks": ["6.2", "6.3", "6.5", "6.6"] },
    { "id": 8, "tasks": ["8.1"] },
    { "id": 9, "tasks": ["8.2"] },
    { "id": 10, "tasks": ["8.3", "8.4"] },
    { "id": 11, "tasks": ["9.1", "9.2", "9.3"] },
    { "id": 12, "tasks": ["10.1"] },
    { "id": 13, "tasks": ["11.1"] },
    { "id": 14, "tasks": ["11.2", "11.3", "11.4", "11.5"] },
    { "id": 15, "tasks": ["11.6", "11.7"] }
  ]
}
```
