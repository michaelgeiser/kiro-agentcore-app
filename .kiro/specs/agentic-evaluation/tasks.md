# Implementation Plan: Agentic Evaluation and Report Generation

## Overview

This plan implements the intelligence layer of the Presentation Coaching Platform — the Agentic Evaluation work unit. It uses Amazon Bedrock AgentCore with the Strands Agents SDK "Agents as Tools" pattern to orchestrate multiple evaluation agents. The implementation follows the established project structure (mirroring the preparation-workflow module) and builds incrementally: data models first, then infrastructure services, then agents, then report generation, and finally wiring everything together.

## Tasks

- [ ] 1. Set up project structure and core data models
  - [ ] 1.1 Create the agentic-evaluation module directory structure and dependencies
    - Create `agentic-evaluation/` directory with `src/`, `tests/`, `tests/properties/`, `tests/unit/`, `tests/integration/` subdirectories
    - Create `pyproject.toml` with project metadata and pytest/hypothesis configuration
    - Create `requirements.txt` with runtime dependencies (strands-agents, boto3, pydantic, reportlab)
    - Create `requirements-dev.txt` with dev dependencies (pytest, hypothesis, moto, pytest-asyncio)
    - Create `src/__init__.py`, `tests/__init__.py`, `tests/conftest.py`
    - _Requirements: 7.1, 7.5_

  - [ ] 1.2 Implement core data models (Pydantic)
    - Create `src/models/__init__.py` and `src/models/data_models.py`
    - Implement `HandoffMessage`, `ProcessingStatus` enum, `Finding`, `EvaluationResult`, `EvaluationInput`, `AgentDescriptor`, `ErrorNotification`, `SessionResult`, `RetryConfig` models
    - Include all field validations (min_length, ge constraints, score ranges 0.0-10.0)
    - Implement S3 path construction helpers: `get_evaluation_result_path(submission_id, dimension_name)` and `get_report_path(user_id, submission_id)`
    - _Requirements: 1.2, 3.5, 5.1, 5.2, 6.5, 9.3_

  - [ ]* 1.3 Write property tests for data model serialization and validation
    - **Property 1: Handoff message parsing round-trip**
    - **Property 2: Invalid messages produce DLQ routing (validation rejection)**
    - **Property 5: S3 path construction correctness**
    - **Property 6: Evaluation result serialization round-trip**
    - **Validates: Requirements 1.2, 1.4, 5.1, 5.2, 6.5**

  - [ ]* 1.4 Write unit tests for data models
    - Test HandoffMessage with valid and invalid inputs
    - Test ProcessingStatus enum values
    - Test Finding and EvaluationResult construction with edge cases
    - Test S3 path helpers with various submission_id and dimension combinations
    - _Requirements: 1.2, 5.1, 6.5_

- [ ] 2. Implement infrastructure services
  - [ ] 2.1 Implement the SQS Consumer
    - Create `src/services/__init__.py` and `src/services/sqs_consumer.py`
    - Implement `SQSConsumer` class with `receive_message()`, `acknowledge()`, and `send_to_dlq()` methods
    - Use boto3 SQS client with long-polling (WaitTimeSeconds=20)
    - Handle FIFO queue specifics (MessageGroupId, SequenceNumber)
    - _Requirements: 1.1, 8.1, 8.2, 8.3, 8.4, 8.5_

  - [ ] 2.2 Implement the Status Manager
    - Create `src/services/status_manager.py`
    - Implement `StatusManager` class with `update_status()` method
    - Support optional `report_path` and `failure_reason` fields
    - Use boto3 DynamoDB client with proper error handling
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5_

  - [ ] 2.3 Implement the Error Notifier
    - Create `src/services/error_notifier.py`
    - Implement `ErrorNotifier` class with `notify()` method
    - Construct `ErrorNotification` with all required fields (submission_id, component_name, error_type, error_message, retry_count_exhausted, timestamp)
    - Implement best-effort publishing: catch and log SNS failures without propagating
    - _Requirements: 11.1, 11.2, 11.3_

  - [ ] 2.4 Implement retry logic with exponential backoff and jitter
    - Create `src/services/retry.py`
    - Implement `retry_with_backoff()` as an async utility function/decorator
    - Use `RetryConfig` for max_attempts, base_delay_seconds, backoff_multiplier, max_delay_seconds, jitter
    - Compute delay as `min(base * 2^(attempt-1), max_delay)` with random jitter
    - _Requirements: 5.4, 6.6_

  - [ ]* 2.5 Write property tests for retry backoff and error notifications
    - **Property 8: Exponential backoff with jitter**
    - **Property 11: Error notification structure compliance**
    - **Validates: Requirements 5.4, 9.3, 11.2**

  - [ ]* 2.6 Write unit tests for infrastructure services
    - Test SQS Consumer: receive, acknowledge, DLQ routing
    - Test Status Manager: all status transitions, failure_reason inclusion
    - Test Error Notifier: best-effort isolation, correct notification format
    - Test retry logic: first attempt success, retries exhausted, backoff timing
    - _Requirements: 8.1, 8.3, 10.1, 10.5, 11.3_

- [ ] 3. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 4. Implement Agent Registry and Evaluation Agents
  - [ ] 4.1 Implement the Agent Registry
    - Create `src/agents/__init__.py` and `src/agents/registry.py`
    - Implement `AgentRegistry` class with `get_available_agents()` and `get_agent_by_dimension()` methods
    - Load agent descriptors from a JSON manifest file (`agents_manifest.json`)
    - Filter out disabled agents at runtime
    - _Requirements: 12.1, 12.2, 3.3, 3.4_

  - [ ] 4.2 Create the agent manifest configuration file
    - Create `src/agents/agents_manifest.json` with entries for all 7 evaluation dimensions (delivery, structure, executive_presence, technical_communication, audience_engagement, pacing, persuasion)
    - Each entry includes: agent_id, dimension, display_name, description, version, enabled, tool_module
    - _Requirements: 3.1, 3.2, 12.1_

  - [ ] 4.3 Implement the base evaluation agent tool contract
    - Create `src/agents/base_evaluator.py`
    - Define a base class or protocol for evaluation tools with the standard input/output contract
    - Implement the Strands `@tool` decorator pattern for wrapping agents as callable tools
    - Accept `EvaluationInput`, return `EvaluationResult`
    - _Requirements: 3.5, 4.2, 4.3, 7.3_

  - [ ] 4.4 Implement the 7 evaluation agent tools
    - Create `src/agents/delivery_evaluator.py`, `src/agents/structure_evaluator.py`, `src/agents/executive_presence_evaluator.py`, `src/agents/technical_communication_evaluator.py`, `src/agents/audience_engagement_evaluator.py`, `src/agents/pacing_evaluator.py`, `src/agents/persuasion_evaluator.py`
    - Each agent retrieves embeddings from Vector Store, performs assessment using its specific system prompt, and returns a structured `EvaluationResult`
    - Each agent is implemented as a Strands tool using the base contract
    - _Requirements: 3.1, 3.2, 4.1, 4.2, 4.3_

  - [ ]* 4.5 Write property tests for agent registry and evaluation output
    - **Property 3: Evaluation agent output schema compliance**
    - **Property 14: System functions with any agent subset**
    - **Validates: Requirements 3.4, 3.5, 4.3**

  - [ ]* 4.6 Write unit tests for agent registry and evaluation agents
    - Test registry loads agents from manifest correctly
    - Test disabled agents are filtered out
    - Test empty registry handling
    - Test agent tool invocation returns valid EvaluationResult structure
    - _Requirements: 3.3, 3.4, 12.2_

- [ ] 5. Implement the Coaching Supervisor Agent
  - [ ] 5.1 Implement the Coaching Supervisor
    - Create `src/agents/coaching_supervisor.py`
    - Implement `CoachingSupervisor` class with `evaluate()` method
    - Use Strands Agent with registered evaluation tools from the AgentRegistry
    - Implement reasoning logic: analyze presentation context, select appropriate evaluators, review results, decide on additional invocations
    - Support iterative invocation pattern based on findings from earlier evaluations
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

  - [ ] 5.2 Implement agent failure handling in Coaching Supervisor
    - Catch exceptions from individual evaluation agent invocations
    - Log failures with agent identifier and error details
    - Continue execution with remaining agents after a failure
    - Track which agents completed and which failed for partial failure reporting
    - _Requirements: 4.4, 9.4_

  - [ ]* 5.3 Write property tests for coaching supervisor resilience
    - **Property 4: Agent failure resilience**
    - **Validates: Requirements 4.4**

  - [ ]* 5.4 Write unit tests for coaching supervisor
    - Test successful orchestration with all agents
    - Test partial failure (some agents succeed, some fail)
    - Test iterative invocation (additional agent triggered by findings)
    - Test completion signaling
    - _Requirements: 2.1, 2.3, 2.5, 4.4_

- [ ] 6. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 7. Implement Report Generator
  - [ ] 7.1 Implement the Report Generator
    - Create `src/services/report_generator.py`
    - Implement `ReportGenerator` class with `generate()` method
    - Read all evaluation results from S3 for the given submission_id
    - Use ReportLab to produce a PDF with: executive summary, per-dimension detailed feedback, strengths, improvements, overall coaching assessment
    - Store the PDF at `reports/{user_id}/{submission_id}/coaching_report.pdf`
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

  - [ ]* 7.2 Write property tests for report generation
    - **Property 9: Report contains all required sections**
    - **Validates: Requirements 6.2, 6.4**

  - [ ]* 7.3 Write unit tests for report generator
    - Test report generation with single dimension result
    - Test report generation with all 7 dimension results
    - Test minimum content verification (executive summary, feedback, strengths, improvements present)
    - Test PDF file is valid and non-empty
    - _Requirements: 6.1, 6.2, 6.4, 6.5_

- [ ] 8. Implement Session Supervisor and wire components together
  - [ ] 8.1 Implement the Session Supervisor Agent
    - Create `src/agents/session_supervisor.py`
    - Implement `SessionSupervisor` class with `handle_message()` and `consume_queue()` methods
    - Wire together: SQSConsumer, StatusManager, CoachingSupervisor, ReportGenerator, ErrorNotifier
    - Implement the full lifecycle: parse message → update status to Evaluating → delegate to CoachingSupervisor → store results in S3 → update status to Report_Generating → generate report → update status to Completed
    - _Requirements: 1.1, 1.2, 1.3, 10.1, 10.2, 10.3, 10.4_

  - [ ] 8.2 Implement message validation and DLQ routing in Session Supervisor
    - Validate incoming message against HandoffMessage schema
    - Route invalid messages to DLQ with error notification
    - Implement message acknowledgment after successful initiation
    - _Requirements: 1.4, 8.3, 8.4, 9.1, 9.2, 9.3_

  - [ ] 8.3 Implement evaluation result storage and completeness verification
    - Store each EvaluationResult as JSON in S3 at the correct path
    - Implement completeness verification: check all expected dimensions have corresponding files
    - Use retry_with_backoff for S3 writes
    - Handle S3 write failures (notify via SNS, continue with remaining agents)
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

  - [ ] 8.4 Implement partial failure handling and failure status management
    - On midway failure: store completed results, update status to Failed, publish detailed SNS notification
    - Include which agents completed and which failed in notification
    - Always include non-empty failure_reason when setting Failed status
    - Do NOT generate report from incomplete data
    - _Requirements: 9.4, 10.5, 4.4_

  - [ ]* 8.5 Write property tests for completeness verification and failure handling
    - **Property 7: Evaluation completeness verification**
    - **Property 12: Partial failure notification accuracy**
    - **Property 13: Failure status always includes reason**
    - **Validates: Requirements 5.3, 9.4, 10.5**

  - [ ]* 8.6 Write unit tests for Session Supervisor
    - Test full happy path lifecycle (Evaluating → Report_Generating → Completed)
    - Test invalid message → DLQ routing
    - Test partial failure → Failed status with details
    - Test message acknowledgment timing
    - Test report path stored in DynamoDB on completion
    - _Requirements: 1.1, 1.3, 1.4, 10.1, 10.2, 10.3, 10.4, 10.5_

- [ ] 9. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 10. Implement FIFO ordering and integration tests
  - [ ] 10.1 Implement FIFO ordering guarantee in queue consumption
    - Ensure `consume_queue()` processes messages sequentially in received order
    - Implement proper SQS FIFO message handling (visibility timeout, sequential processing)
    - _Requirements: 8.1, 8.2_

  - [ ]* 10.2 Write property test for FIFO ordering
    - **Property 10: FIFO ordering preserved**
    - **Validates: Requirements 8.2**

  - [ ]* 10.3 Write integration tests for the full evaluation session
    - Test full happy path with mocked AWS services (SQS, DynamoDB, S3, SNS) using moto
    - Test agent failure mid-session scenario
    - Test S3 write failure with retries
    - Test DLQ routing on invalid message
    - Test report generation and storage end-to-end
    - _Requirements: 1.1, 5.4, 6.1, 9.1, 10.1, 10.2, 10.3_

- [ ] 11. Implement AgentCore deployment configuration
  - [ ] 11.1 Create Bedrock AgentCore Runtime deployment configuration
    - Create deployment configuration for Session Supervisor and Coaching Supervisor agents
    - Configure AgentCore memory for session context persistence
    - Implement local execution support (Strands local mode) for development/testing
    - _Requirements: 7.1, 7.2, 7.4, 7.5_

  - [ ] 11.2 Wire the DLQ threshold alert notification
    - Implement CloudWatch alarm or polling mechanism for DLQ message count
    - Publish threshold alert to SNS when count exceeds configurable limit
    - _Requirements: 11.4_

- [ ] 12. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- Integration tests use moto to mock AWS services (SQS, DynamoDB, S3, SNS)
- The implementation follows the same directory structure pattern as the existing preparation-workflow module
- All agents use the Strands Agents SDK "Agents as Tools" pattern for hierarchical orchestration

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2"] },
    { "id": 2, "tasks": ["1.3", "1.4", "2.1", "2.2", "2.3", "2.4"] },
    { "id": 3, "tasks": ["2.5", "2.6", "4.1", "4.2"] },
    { "id": 4, "tasks": ["4.3"] },
    { "id": 5, "tasks": ["4.4", "4.5", "4.6"] },
    { "id": 6, "tasks": ["5.1"] },
    { "id": 7, "tasks": ["5.2", "5.3", "5.4", "7.1"] },
    { "id": 8, "tasks": ["7.2", "7.3"] },
    { "id": 9, "tasks": ["8.1"] },
    { "id": 10, "tasks": ["8.2", "8.3", "8.4"] },
    { "id": 11, "tasks": ["8.5", "8.6", "10.1"] },
    { "id": 12, "tasks": ["10.2", "10.3", "11.1", "11.2"] }
  ]
}
```
