# Implementation Plan: Preparation Workflow

## Overview

This plan implements the Preparation Workflow as an AWS Step Functions Standard Workflow that orchestrates file validation, audio extraction, embedding creation, and hand-off to downstream processing. Implementation is in Python using Pydantic data models, AWS Lambda handlers, and CDK infrastructure-as-code. Tasks are ordered to build foundational models first, then handlers, then infrastructure, with property tests and unit tests integrated throughout.

## Tasks

- [x] 1. Set up project structure and core data models
  - [x] 1.1 Create project directory structure and configuration files
    - Create `preparation-workflow/` directory with subdirectories: `src/models/`, `src/handlers/`, `src/services/`, `src/validation/`, `tests/properties/`, `tests/unit/`, `tests/integration/`, `tests/cdk/`, `infra/`
    - Add `pyproject.toml` or `requirements.txt` with dependencies: `pydantic>=2.0`, `boto3`, `hypothesis>=6.90.0`, `pytest`, `moto[all]`
    - Add `conftest.py` files for test configuration
    - _Requirements: 8.1, 8.3_

  - [x] 1.2 Implement WorkflowConfig data model
    - Create `src/models/workflow_config.py` with Pydantic `WorkflowConfig` model
    - Fields: `embedding_model_id`, `chunk_size_seconds`, `chunk_overlap_seconds`, `max_retry_attempts`, `video_processing_enabled`, `vector_store_endpoint`, `vector_store_type`, `batch_size`, `batch_processing_enabled`
    - Add type validation (int for numeric fields, bool for flags)
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

  - [x] 1.3 Implement InputMessage data model
    - Create `src/models/input_message.py` with Pydantic `InputMessage` model
    - Fields: `submission_id`, `user_id`, `s3_bucket`, `s3_file_key`, `original_file_name`, `presentation_title`
    - All fields required, string type
    - _Requirements: 1.2_

  - [x] 1.4 Write property test for InputMessage round-trip (Property 1)
    - **Property 1: Message Parsing Round-Trip**
    - **Validates: Requirements 1.2**
    - Generate arbitrary valid InputMessage instances using Hypothesis strategies
    - Verify serializing to JSON and deserializing back produces identical messages

  - [x] 1.5 Implement HandoffMessage data model
    - Create `src/models/handoff_message.py` with Pydantic `HandoffMessage` model
    - Fields: `submission_id`, `user_id`, `s3_file_key`, `vector_store_location`, `chunk_count` (int >= 1), `presentation_title`
    - _Requirements: 7.3_

  - [x] 1.6 Write property test for HandoffMessage completeness (Property 9)
    - **Property 9: Handoff Message Completeness**
    - **Validates: Requirements 7.3**
    - Generate arbitrary valid inputs and verify constructed HandoffMessage contains all fields with exact matching values

  - [x] 1.7 Implement AudioChunk, EmbeddingResult, and VectorMetadata data models
    - Create `src/models/audio_chunk.py` with Pydantic `AudioChunk` model
    - Create `src/models/embedding_result.py` with Pydantic `EmbeddingResult` model
    - Create `src/models/vector_metadata.py` with Pydantic `VectorMetadata` model
    - Include proper type annotations and field validators
    - _Requirements: 4.3, 4.4, 11.3_

  - [x] 1.8 Write property test for VectorMetadata completeness (Property 7)
    - **Property 7: Vector Metadata Completeness**
    - **Validates: Requirements 4.4, 11.3**
    - Generate arbitrary valid inputs and verify VectorMetadata contains all six fields with exact matching values

  - [x] 1.9 Implement FileValidationResult and WorkflowErrorNotification data models
    - Create `src/models/file_validation_result.py` with Pydantic `FileValidationResult` model
    - Create `src/models/error_notification.py` with Pydantic `WorkflowErrorNotification` model
    - FileValidationResult: `valid` (bool), `file_type` (optional str), `error` (optional str)
    - WorkflowErrorNotification: `submission_id`, `step_name`, `error_type`, `error_message`, `retry_count_exhausted`, `timestamp` (ISO 8601), `queue_name` (optional)
    - _Requirements: 2.1, 6.4, 9.2_

  - [x] 1.10 Write property test for WorkflowErrorNotification completeness (Property 8)
    - **Property 8: Error Notification Completeness**
    - **Validates: Requirements 6.4, 9.2**
    - Generate arbitrary failure contexts and verify WorkflowErrorNotification contains all required fields with valid ISO 8601 timestamp

- [x] 2. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. Implement validation and configuration handlers
  - [x] 3.1 Implement load_config Lambda handler
    - Create `src/handlers/load_config.py`
    - Fetch all SSM parameters from `/prescoach/{env}/preparation-workflow/` namespace
    - Parse parameters into `WorkflowConfig` model
    - Handle missing parameters with descriptive errors
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

  - [x] 3.2 Implement parse_message Lambda handler
    - Create `src/handlers/parse_message.py`
    - Deserialize SQS message body JSON into `InputMessage` model
    - Return validation error result for invalid/incomplete messages
    - _Requirements: 1.2, 1.4_

  - [x] 3.3 Write property test for invalid message rejection (Property 2)
    - **Property 2: Invalid Message Rejection**
    - **Validates: Requirements 1.4**
    - Generate JSON objects with one or more required fields missing
    - Verify parse_message returns an error result for each invalid input

  - [x] 3.4 Implement validate_format function
    - Create `src/validation/format_validator.py`
    - Validate file extensions case-insensitively against accepted formats
    - Audio extensions: `.mp3`, `.wav`, `.m4a`, `.aac`
    - Video extensions: `.mp4`, `.mov`, `.webm`
    - Return `FileValidationResult` with `file_type` as "audio" or "video"
    - _Requirements: 2.1_

  - [x] 3.5 Write property test for file format validation (Property 3)
    - **Property 3: File Format Validation Biconditional**
    - **Validates: Requirements 2.1**
    - Generate arbitrary filename strings and verify validate_format returns valid=True iff extension is accepted, with correct file_type classification

  - [x] 3.6 Implement video processing decision logic
    - Create `src/handlers/validate_format.py` Lambda handler
    - Combine FileValidationResult with Feature_Flag_Video_Processing to decide next step
    - Audio → proceed to embedding; Video + flag enabled → extract audio; Video + flag disabled → fail
    - _Requirements: 2.3, 2.4_

  - [x] 3.7 Write property test for video processing decision (Property 4)
    - **Property 4: Video Processing Decision**
    - **Validates: Requirements 2.3, 2.4**
    - Generate arbitrary file classification and flag state combinations
    - Verify correct decision for each scenario

  - [x] 3.8 Write unit tests for load_config and parse_message handlers
    - Test SSM parameter parsing with complete and partial parameter sets
    - Test type coercion for numeric and boolean parameters
    - Test parse_message with valid JSON, malformed JSON, missing fields
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 1.2, 1.4_

- [x] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Implement audio extraction and chunking services
  - [x] 5.1 Implement extract_audio service
    - Create `src/services/audio_extraction.py`
    - Submit MediaConvert job to extract audio from video
    - Construct output S3 key using pattern `processed/{user_id}/{submission_id}/audio.{format}`
    - Poll for job completion (or use Step Functions wait pattern)
    - Return extracted audio S3 key on success
    - _Requirements: 3.1, 3.2, 3.3_

  - [x] 5.2 Write property test for audio output path construction (Property 5)
    - **Property 5: Audio Output Path Construction**
    - **Validates: Requirements 3.2**
    - Generate arbitrary user_id and submission_id strings
    - Verify constructed S3 key matches the expected pattern with exact values

  - [x] 5.3 Implement chunk_audio service
    - Create `src/services/chunking.py`
    - Divide audio into chunks based on configured chunk_size and chunk_overlap parameters
    - Generate AudioChunk models with correct timestamps
    - Upload chunks to S3 and return list of AudioChunk objects
    - _Requirements: 4.2, 4.3_

  - [x] 5.4 Write property test for audio chunking correctness (Property 6)
    - **Property 6: Audio Chunking Correctness**
    - **Validates: Requirements 4.3**
    - Generate arbitrary audio durations, chunk sizes, and overlaps
    - Verify: first chunk starts at 0, last chunk covers end, consecutive chunks overlap correctly, no gaps

  - [x] 5.5 Write unit tests for audio extraction and chunking
    - Test extract_audio with mocked MediaConvert responses (success, failure)
    - Test chunk_audio with edge cases: audio shorter than chunk size, exact multiple, zero overlap
    - _Requirements: 3.1, 3.2, 3.3, 4.2, 4.3_

- [x] 6. Implement embedding and vector store services
  - [x] 6.1 Implement create_embedding service
    - Create `src/services/embedding.py`
    - Invoke Amazon Bedrock with audio chunk for embedding creation
    - Return `EmbeddingResult` with embedding vector and metadata
    - Support both individual and batch invocation based on `batch_processing_enabled` config
    - _Requirements: 4.1, 4.2, 10.1_

  - [x] 6.2 Implement batch_processor service
    - Create `src/services/batch_processor.py`
    - Group audio chunks into batches based on `batch_size` config
    - Process batches and collect results maintaining chunk order
    - _Requirements: 10.1, 10.2, 10.3, 10.4_

  - [x] 6.3 Write property test for batch grouping correctness (Property 10)
    - **Property 10: Batch Grouping Correctness**
    - **Validates: Requirements 10.1, 10.2**
    - Generate arbitrary chunk lists and batch sizes
    - Verify: correct number of batches, each batch at most batch_size, all chunks appear exactly once, order preserved

  - [x] 6.4 Implement store_vectors service
    - Create `src/services/vector_store.py`
    - Write embedding vectors with `VectorMetadata` to configured Vector Store
    - Support configurable vector store type (read from config)
    - _Requirements: 11.1, 11.2, 11.3, 11.4_

  - [x] 6.5 Write unit tests for embedding and vector store services
    - Test create_embedding with mocked Bedrock responses
    - Test store_vectors with mocked vector store client
    - Test batch_processor with single chunk, batch_size=1, batch_size > chunk_count
    - _Requirements: 4.1, 10.1, 10.2, 11.1, 11.3_

- [x] 7. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Implement handoff and error handling
  - [x] 8.1 Implement publish_handoff handler
    - Create `src/handlers/publish_handoff.py`
    - Construct `HandoffMessage` from processing results
    - Publish message to FIFO SQS Handoff Queue with message group ID
    - _Requirements: 7.1, 7.2, 7.3_

  - [x] 8.2 Implement handle_failure handler
    - Create `src/handlers/handle_failure.py`
    - Update DynamoDB Processing_Status to Failed
    - Construct `WorkflowErrorNotification` and publish to SNS (best-effort)
    - Route original message to appropriate DLQ (Input or Handoff)
    - Catch and log SNS publish failures without propagating
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 9.1, 9.2, 9.3_

  - [x] 8.3 Write unit tests for handoff and error handling
    - Test publish_handoff with mocked SQS (success, failure)
    - Test handle_failure routes to correct DLQ based on failure context
    - Test SNS publish failure is caught and does not fail the handler
    - _Requirements: 7.1, 7.4, 7.5, 6.1, 6.4, 9.3_

- [x] 9. Implement CDK infrastructure
  - [x] 9.1 Create CDK stack for Preparation Workflow infrastructure
    - Create `infra/preparation_workflow_stack.py`
    - Define Step Functions Standard Workflow state machine
    - Define Lambda functions with appropriate IAM roles (least privilege)
    - Configure SQS Input Queue with DLQ (maxReceiveCount: 3)
    - Configure FIFO SQS Handoff Queue with DLQ
    - Define SNS Topic for error notifications
    - Set up SSM Parameter Store paths under `/prescoach/{env}/preparation-workflow/`
    - Configure EventBridge Pipe from SQS to Step Functions
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 6.1, 6.3, 7.2, 9.4_

  - [x] 9.2 Define Step Function state machine definition (ASL)
    - Create state machine definition with all states: LoadConfig, ParseMessage, UpdateStatusProcessing, ValidateFileFormat, CheckVideoFlag, ExtractAudio, ChunkAudio, CreateEmbeddings (Map state), StoreVectors, PublishHandoff, UpdateStatusCompleted, HandleFailure
    - Configure retry policies with exponential backoff and jitter on all task states
    - Configure Choice state for video processing decision
    - Configure Map state for parallel/batch embedding processing
    - Wire error catchers to HandleFailure state
    - _Requirements: 8.1, 8.2, 8.3, 8.4_

  - [x] 9.3 Write CDK snapshot tests
    - Verify Standard Workflow type
    - Verify retry configuration on all task states
    - Verify DLQ associations on SQS queues
    - Verify IAM permissions follow least privilege
    - Verify SSM parameter paths
    - _Requirements: 8.1, 8.2, 6.1, 6.3_

- [x] 10. Integration tests
  - [x] 10.1 Write integration tests for end-to-end workflows
    - Test successful audio processing flow (SQS → parse → validate → embed → store → handoff)
    - Test successful video processing flow with mocked MediaConvert
    - Test invalid format rejection updates DynamoDB and publishes SNS
    - Test video disabled rejection updates DynamoDB with reason
    - Test embedding failure after retries routes to DLQ and updates status
    - Test handoff publish failure routes to DLQ_Handoff
    - Use `moto` to mock AWS services: SQS, DynamoDB, S3, SSM, SNS, MediaConvert
    - _Requirements: 1.1, 1.3, 2.1, 2.2, 2.3, 2.4, 3.1, 4.1, 6.1, 6.2, 7.1, 7.5, 8.5_

- [x] 11. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- Integration tests use `moto` for AWS service mocking
- The implementation language is Python with Pydantic v2 for data models
- Hypothesis library (already used by upload-service) is used for property-based tests

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.3", "1.5", "1.7", "1.9"] },
    { "id": 2, "tasks": ["1.4", "1.6", "1.8", "1.10"] },
    { "id": 3, "tasks": ["3.1", "3.2", "3.4"] },
    { "id": 4, "tasks": ["3.3", "3.5", "3.6"] },
    { "id": 5, "tasks": ["3.7", "3.8"] },
    { "id": 6, "tasks": ["5.1", "5.3"] },
    { "id": 7, "tasks": ["5.2", "5.4", "5.5"] },
    { "id": 8, "tasks": ["6.1", "6.2", "6.4"] },
    { "id": 9, "tasks": ["6.3", "6.5"] },
    { "id": 10, "tasks": ["8.1", "8.2"] },
    { "id": 11, "tasks": ["8.3"] },
    { "id": 12, "tasks": ["9.1"] },
    { "id": 13, "tasks": ["9.2"] },
    { "id": 14, "tasks": ["9.3", "10.1"] }
  ]
}
```
