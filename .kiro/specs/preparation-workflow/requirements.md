# Requirements Document

## Introduction

The Preparation Workflow is the processing pipeline of the Presentation Coaching Platform responsible for consuming messages from the SQS queue populated by the Upload and Storage service, validating uploaded files, extracting audio from video files, creating vector embeddings of audio content, and handing off processed results to the Agentic Processing work unit. The workflow is implemented as an AWS Step Function (Standard Workflow) to support long-running embedding operations, retry logic with backoff and jitter, and future extensibility. The architecture prioritizes configurability of models and processing strategies, uses feature flags to control processing scope, and maintains robust error handling with dead-letter queues and SNS notifications.

## Glossary

- **Preparation_Workflow**: The AWS Step Functions Standard Workflow that orchestrates file validation, audio extraction, embedding creation, and hand-off to downstream processing
- **Step_Function**: AWS Step Functions Standard Workflow — chosen over Express Workflow due to the longer execution lifespan required by the embedding process
- **SQS_Input_Queue**: The SQS queue populated by the Upload and Storage service containing messages about newly uploaded files awaiting processing
- **SQS_Handoff_Queue**: A separate FIFO SQS queue used to pass processed results to the Agentic Processing work unit in a loosely coupled manner
- **DLQ_Input**: The dead-letter queue associated with the SQS_Input_Queue for messages that fail initial consumption
- **DLQ_Handoff**: The dead-letter queue associated with the SQS_Handoff_Queue for messages that fail delivery to the Agentic Processing work unit
- **SNS_Topic**: The AWS SNS topic used to communicate error notifications, processing failures, and threshold alerts to the operations team
- **DynamoDB_Table**: The AWS DynamoDB table storing submission metadata including processing status
- **S3_Bucket**: The AWS S3 bucket where uploaded presentation files and processed audio files are stored
- **Audio_Extraction_Service**: An AWS-native service (AWS Elemental MediaConvert) used for cost-effective extraction of audio tracks from video files
- **Embedding_Model**: A multi-modal, multilingual embedding model (default: Amazon Nova Multimodal Embeddings) used to create vector embeddings from audio content
- **Vector_Store**: The storage system for vector embeddings — candidate options include S3-based vector storage, to be finalized based on price and performance evaluation
- **Feature_Flag_Video_Processing**: A configuration flag that controls whether video files are processed; defaults to disabled (audio-only processing)
- **Processing_Status**: The state of a submission in the pipeline (Pending, Processing, Completed, Failed)
- **Chunking_Strategy**: The approach for dividing audio content into segments for embedding, including chunk size and overlap parameters
- **Model_Configuration**: Externalized configuration (e.g., AWS Systems Manager Parameter Store or similar) that allows model selection and parameters to be changed without redeployment

## Requirements

### Requirement 1: Message Consumption from Input Queue

**User Story:** As the platform pipeline, I want the Preparation Workflow to consume messages from the upload queue, so that newly uploaded files are automatically picked up for processing.

#### Acceptance Criteria

1. WHEN a message arrives on the SQS_Input_Queue, THE Preparation_Workflow SHALL be triggered to process the uploaded file referenced in the message
2. THE Preparation_Workflow SHALL extract the submission_id, user_id, s3_file_key, original_file_name, and presentation_title from the SQS message body
3. WHEN the Preparation_Workflow begins processing a message, THE Preparation_Workflow SHALL update the Processing_Status of the corresponding Submission_Record in the DynamoDB_Table to Processing
4. IF the Preparation_Workflow fails to parse the SQS message body, THEN THE Preparation_Workflow SHALL send the message to the DLQ_Input and publish an error notification to the SNS_Topic

### Requirement 2: File Format Validation

**User Story:** As a platform operator, I want uploaded files validated for format compliance before processing, so that only supported file types enter the pipeline.

#### Acceptance Criteria

1. WHEN the Preparation_Workflow receives a file for processing, THE Preparation_Workflow SHALL validate that the file format matches the accepted audio formats (MP3, WAV, M4A, AAC) or accepted video formats (MP4, MOV, WebM)
2. IF the file format does not match any accepted format, THEN THE Preparation_Workflow SHALL update the Processing_Status to Failed in the DynamoDB_Table, send the message to the DLQ_Input, and publish an error notification to the SNS_Topic
3. WHEN the file is a video format and the Feature_Flag_Video_Processing is disabled, THE Preparation_Workflow SHALL update the Processing_Status to Failed in the DynamoDB_Table with a reason indicating video processing is not currently enabled
4. WHEN the file is a video format and the Feature_Flag_Video_Processing is enabled, THE Preparation_Workflow SHALL proceed with audio extraction from the video file

### Requirement 3: Audio Extraction from Video Files

**User Story:** As a platform operator, I want audio tracks extracted from video files using a cost-effective AWS-native service, so that the platform can process video submissions without unnecessary expense.

#### Acceptance Criteria

1. WHEN the Preparation_Workflow processes a video file with Feature_Flag_Video_Processing enabled, THE Audio_Extraction_Service SHALL extract the audio track from the video file
2. WHEN audio extraction completes, THE Preparation_Workflow SHALL store the extracted audio file in the S3_Bucket using the naming convention: `processed/{user_id}/{submission_id}/audio.{format}`
3. IF the Audio_Extraction_Service fails to extract audio from the video file, THEN THE Preparation_Workflow SHALL retry the extraction with exponential backoff and jitter up to a configurable maximum number of attempts
4. IF audio extraction fails after all retry attempts, THEN THE Preparation_Workflow SHALL update the Processing_Status to Failed in the DynamoDB_Table, send the original message to the DLQ_Input, and publish an error notification to the SNS_Topic

### Requirement 4: Audio Vector Embedding Creation

**User Story:** As a platform operator, I want vector embeddings created directly from audio content (not transcriptions), so that audio features like pacing, tone, and delivery style are preserved for coaching evaluations.

#### Acceptance Criteria

1. WHEN an audio file is ready for embedding (either an uploaded audio file or an extracted audio track), THE Preparation_Workflow SHALL create vector embeddings using the configured Embedding_Model
2. THE Preparation_Workflow SHALL process audio content directly without transcription to preserve audio features including pacing, tone, volume variation, and delivery characteristics
3. THE Preparation_Workflow SHALL divide the audio content into chunks according to the configured Chunking_Strategy including chunk size and overlap parameters
4. THE Preparation_Workflow SHALL store the resulting vector embeddings in the configured Vector_Store with metadata linking each embedding to its source submission_id, chunk index, and chunk timestamp range
5. IF the embedding creation process fails for a chunk, THEN THE Preparation_Workflow SHALL retry the embedding operation with exponential backoff and jitter up to a configurable maximum number of attempts
6. IF embedding creation fails after all retry attempts, THEN THE Preparation_Workflow SHALL update the Processing_Status to Failed in the DynamoDB_Table, send the original message to the DLQ_Input, and publish an error notification to the SNS_Topic

### Requirement 5: Model and Processing Configuration

**User Story:** As a platform operator, I want all models and processing parameters to be configurable without redeployment, so that the team can adjust or swap models based on performance, cost, or capability without a release cycle.

#### Acceptance Criteria

1. THE Preparation_Workflow SHALL read the Embedding_Model identifier from the Model_Configuration at runtime rather than from hardcoded values
2. THE Preparation_Workflow SHALL read chunking parameters (chunk size, overlap size) from the Model_Configuration at runtime
3. THE Preparation_Workflow SHALL read the maximum retry attempt count from the Model_Configuration at runtime
4. THE Preparation_Workflow SHALL read the Feature_Flag_Video_Processing value from the Model_Configuration at runtime
5. WHEN the Model_Configuration is updated, THE Preparation_Workflow SHALL use the updated values for subsequent executions without requiring redeployment of the workflow

### Requirement 6: Dead-Letter Queue Processing

**User Story:** As a platform operator, I want failed processing messages routed to dead-letter queues and the corresponding submissions marked as failed, so that no submission is silently lost and failures are visible for remediation.

#### Acceptance Criteria

1. WHEN a message from the SQS_Input_Queue fails processing after all retry attempts, THE Preparation_Workflow SHALL route the message to the DLQ_Input
2. WHEN a message is placed on the DLQ_Input, THE Preparation_Workflow SHALL update the Processing_Status of the corresponding Submission_Record in the DynamoDB_Table to Failed
3. WHEN a message fails delivery to the SQS_Handoff_Queue after all retry attempts, THE Preparation_Workflow SHALL route the message to the DLQ_Handoff
4. WHEN a message is placed on either DLQ_Input or DLQ_Handoff, THE Preparation_Workflow SHALL publish an error notification to the SNS_Topic containing the submission_id, failure reason, queue name, and timestamp

### Requirement 7: Hand-off to Agentic Processing

**User Story:** As the platform pipeline, I want processed results handed off to the Agentic Processing work unit through a loosely coupled mechanism, so that the two work units can evolve and scale independently.

#### Acceptance Criteria

1. WHEN the Preparation_Workflow successfully completes embedding creation for a submission, THE Preparation_Workflow SHALL publish a message to the SQS_Handoff_Queue
2. THE SQS_Handoff_Queue SHALL be configured as a FIFO queue to preserve processing order
3. THE handoff message body SHALL contain the submission_id, user_id, s3_file_key, vector_store_location, chunk_count, and presentation_title
4. IF the SQS_Handoff_Queue publish operation fails, THEN THE Preparation_Workflow SHALL retry the publish with exponential backoff and jitter up to a configurable maximum number of attempts
5. IF the handoff publish fails after all retry attempts, THEN THE Preparation_Workflow SHALL update the Processing_Status to Failed in the DynamoDB_Table, route the message to the DLQ_Handoff, and publish an error notification to the SNS_Topic

### Requirement 8: Step Function Workflow Orchestration

**User Story:** As a platform architect, I want the processing pipeline implemented as a Standard Step Function, so that long-running embedding operations are supported, retries are handled natively, and the workflow is extensible for future processing steps.

#### Acceptance Criteria

1. THE Preparation_Workflow SHALL be implemented as an AWS Step Functions Standard Workflow to support execution durations required by the embedding process
2. THE Preparation_Workflow SHALL implement retry logic with exponential backoff and jitter for all AWS service interactions (Audio_Extraction_Service, Embedding_Model, S3 operations, SQS publish operations)
3. THE Step_Function SHALL define discrete states for: message parsing, file validation, audio extraction (conditional), embedding creation, result storage, and handoff publishing
4. THE Step_Function SHALL support the addition of new processing states without modifying existing state logic
5. WHEN the Step_Function execution completes successfully, THE Preparation_Workflow SHALL update the Processing_Status to Completed in the DynamoDB_Table

### Requirement 9: Error Notification and Observability

**User Story:** As a platform operator, I want errors, failures, and threshold issues published to SNS, so that the operations team can respond to problems and maintain pipeline health.

#### Acceptance Criteria

1. WHEN any step in the Preparation_Workflow fails after exhausting retries, THE Preparation_Workflow SHALL publish an error notification to the SNS_Topic
2. THE SNS error notification SHALL contain the submission_id, step name that failed, error type, error message, retry count exhausted, and timestamp in ISO 8601 format
3. THE Preparation_Workflow SHALL publish the SNS error notification on a best-effort basis without causing the workflow execution to fail if the SNS publish itself fails
4. WHEN the DLQ_Input or DLQ_Handoff message count exceeds a configurable threshold, THE SNS_Topic SHALL receive a threshold alert notification

### Requirement 10: Batch Processing Consideration

**User Story:** As a platform architect, I want the workflow to support batch processing of embeddings where appropriate, so that cost efficiency is maximized for non-real-time evaluations.

#### Acceptance Criteria

1. THE Preparation_Workflow SHALL support both individual and batch invocation of the Embedding_Model based on the Model_Configuration
2. WHERE batch processing is configured, THE Preparation_Workflow SHALL group audio chunks for batch embedding submission to reduce per-invocation overhead
3. WHERE batch processing is configured, THE Preparation_Workflow SHALL wait for all chunks in a batch to complete before proceeding to the handoff step
4. THE Preparation_Workflow SHALL read the batch size parameter from the Model_Configuration at runtime

### Requirement 11: Vector Store Integration

**User Story:** As a platform operator, I want vector embeddings stored in a configurable vector store, so that the team can evaluate and select the optimal storage solution for price and performance.

#### Acceptance Criteria

1. THE Preparation_Workflow SHALL write vector embeddings to the configured Vector_Store
2. THE Preparation_Workflow SHALL read the Vector_Store endpoint and configuration from the Model_Configuration at runtime
3. THE Preparation_Workflow SHALL store each embedding with associated metadata: submission_id, user_id, chunk_index, chunk_timestamp_start, chunk_timestamp_end, and embedding_model_version
4. IF the Vector_Store write operation fails, THEN THE Preparation_Workflow SHALL retry the write with exponential backoff and jitter up to a configurable maximum number of attempts
5. IF the Vector_Store write fails after all retry attempts, THEN THE Preparation_Workflow SHALL update the Processing_Status to Failed in the DynamoDB_Table and publish an error notification to the SNS_Topic
