# Requirements Document

## Introduction

The Agentic Evaluation and Report Generation feature is the core intelligence layer of the Presentation Coaching Platform. It receives processed presentation data (vector embeddings and metadata) from the Preparation Workflow via a FIFO SQS queue and orchestrates a set of independent evaluation agents to assess presentations through multiple lenses — delivery, structure, executive presence, technical communication, audience engagement, pacing, persuasion, and other dimensions. A Session Supervisor coordinates the overall evaluation, while a Coaching Supervisor dynamically selects and orchestrates evaluators based on the presentation context. The architecture is built on Amazon Bedrock AgentCore, leveraging its reasoning, tool orchestration, memory, identity, and API capabilities. Individual evaluation results are temporarily stored in S3 until all agents complete, at which point a Report Generator produces a comprehensive PDF coaching report. The design prioritizes modularity so that evaluators can be added, removed, refined, or replaced without impacting the rest of the system, and supports a path from MVP/PoC through Pilot to Production without re-architecture.

## Glossary

- **Session_Supervisor**: The top-level orchestrator agent responsible for coordinating the overall evaluation session lifecycle, from receiving the handoff message through final report generation
- **Coaching_Supervisor**: The supervisory agent that reasons about the presentation context, determines which evaluation agents are appropriate, reviews findings, and decides whether additional analysis is warranted
- **Evaluation_Agent**: An independent agent that assesses a presentation through a specific lens (e.g., delivery, structure, pacing, persuasion); each agent is logically independent and can evolve at its own pace
- **Report_Generator**: The component responsible for aggregating evaluation results from all completed agents and producing a comprehensive PDF coaching report
- **SQS_Handoff_Queue**: The FIFO SQS queue used by the Preparation Workflow to pass processed results (submission metadata, vector store location, chunk count) to the Agentic Evaluation work unit
- **DLQ_Handoff_Consumer**: The dead-letter queue for messages from the SQS_Handoff_Queue that fail consumption by the Agentic Evaluation work unit
- **SNS_Topic**: The AWS SNS topic used to communicate error notifications, processing failures, and threshold alerts to the operations team
- **DynamoDB_Table**: The AWS DynamoDB table storing submission metadata including processing status
- **S3_Evaluation_Bucket**: The S3 storage location used for temporary storage of individual evaluation agent results until all agents have completed their work
- **Vector_Store**: The storage system containing vector embeddings of the presentation audio created by the Preparation Workflow
- **Bedrock_AgentCore**: Amazon Bedrock AgentCore — the agent framework providing reasoning, tool orchestration, memory, identity, and API capabilities used to implement the agentic architecture
- **Evaluation_Dimension**: A specific aspect of a presentation being assessed (e.g., delivery, structure, executive presence, technical communication, audience engagement, pacing, persuasion)
- **Processing_Status**: The state of a submission in the pipeline (Pending, Processing, Evaluating, Report_Generating, Completed, Failed)
- **Coaching_Report**: The final PDF document containing aggregated evaluation feedback from all completed evaluation agents

## Requirements

### Requirement 1: Handoff Message Consumption

**User Story:** As the platform pipeline, I want the Agentic Evaluation work unit to consume messages from the handoff queue, so that processed presentations are automatically picked up for evaluation.

#### Acceptance Criteria

1. WHEN a message arrives on the SQS_Handoff_Queue, THE Session_Supervisor SHALL be triggered to begin the evaluation session for the submission referenced in the message
2. THE Session_Supervisor SHALL extract the submission_id, user_id, s3_file_key, vector_store_location, chunk_count, and presentation_title from the handoff message body
3. WHEN the Session_Supervisor begins processing a handoff message, THE Session_Supervisor SHALL update the Processing_Status of the corresponding submission in the DynamoDB_Table to Evaluating
4. IF the Session_Supervisor fails to parse or validate the handoff message, THEN THE Session_Supervisor SHALL send the message to the DLQ_Handoff_Consumer and publish an error notification to the SNS_Topic

### Requirement 2: Coaching Supervisor Agent Orchestration

**User Story:** As a platform architect, I want a Coaching Supervisor that dynamically selects evaluators based on presentation context, so that each presentation receives the most relevant and adaptive evaluation.

#### Acceptance Criteria

1. WHEN the Session_Supervisor initiates an evaluation session, THE Coaching_Supervisor SHALL analyze the presentation context (title, metadata, and vector embeddings) to determine which Evaluation_Agents are appropriate
2. THE Coaching_Supervisor SHALL leverage Bedrock_AgentCore reasoning capabilities to select Evaluation_Agents based on presentation characteristics
3. WHEN the Coaching_Supervisor receives results from an Evaluation_Agent, THE Coaching_Supervisor SHALL review the findings and determine whether additional Evaluation_Agents should be invoked
4. THE Coaching_Supervisor SHALL support iterative invocation of Evaluation_Agents based on findings from earlier evaluations
5. WHEN all selected Evaluation_Agents have completed and no further analysis is warranted, THE Coaching_Supervisor SHALL signal the Session_Supervisor that evaluation is complete

### Requirement 3: Evaluation Agent Independence and Modularity

**User Story:** As a platform architect, I want each evaluation agent to be logically independent and modular, so that capabilities can be added, removed, refined, or replaced without impacting the rest of the system.

#### Acceptance Criteria

1. THE platform SHALL implement each Evaluation_Dimension as a separate Evaluation_Agent with its own tools, prompts, and evaluation logic
2. THE platform SHALL support the following Evaluation_Dimensions at minimum: delivery, structure, executive presence, technical communication, audience engagement, pacing, and persuasion
3. WHEN a new Evaluation_Agent is added to the platform, THE platform SHALL require no modifications to existing Evaluation_Agents or the Coaching_Supervisor orchestration logic
4. WHEN an Evaluation_Agent is removed or replaced, THE platform SHALL continue to function with the remaining agents without degradation
5. THE Evaluation_Agent interface SHALL define a standard contract for input (vector_store_location, submission metadata) and output (structured evaluation results)

### Requirement 4: Evaluation Agent Execution

**User Story:** As a platform operator, I want evaluation agents to execute independently against the vector embeddings, so that presentations are assessed through multiple lenses concurrently.

#### Acceptance Criteria

1. WHEN the Coaching_Supervisor invokes an Evaluation_Agent, THE Evaluation_Agent SHALL retrieve relevant vector embeddings from the Vector_Store using the provided vector_store_location and submission_id
2. THE Evaluation_Agent SHALL use Bedrock_AgentCore reasoning and tool orchestration capabilities to assess the presentation for its assigned Evaluation_Dimension
3. WHEN an Evaluation_Agent completes its assessment, THE Evaluation_Agent SHALL produce a structured evaluation result containing the dimension name, findings, scores, and specific feedback
4. IF an Evaluation_Agent fails during execution, THEN THE Coaching_Supervisor SHALL log the failure, publish an error notification to the SNS_Topic, and continue with remaining agents

### Requirement 5: Temporary Evaluation Result Storage

**User Story:** As a platform operator, I want individual evaluation results stored temporarily in S3 until all agents complete, so that results are durable during the evaluation session and available for report generation.

#### Acceptance Criteria

1. WHEN an Evaluation_Agent completes its assessment, THE Session_Supervisor SHALL store the evaluation result in the S3_Evaluation_Bucket using the path: `evaluations/{submission_id}/{dimension_name}.json`
2. THE Session_Supervisor SHALL store each evaluation result as a structured JSON document containing the dimension name, agent identifier, timestamp, findings, scores, and detailed feedback
3. WHEN all Evaluation_Agents for a session have completed, THE Session_Supervisor SHALL verify that all expected evaluation result files are present in the S3_Evaluation_Bucket before proceeding to report generation
4. IF the S3 write operation for an evaluation result fails, THEN THE Session_Supervisor SHALL retry the write with exponential backoff and jitter up to a configurable maximum number of attempts
5. IF the S3 write fails after all retry attempts, THEN THE Session_Supervisor SHALL publish an error notification to the SNS_Topic and continue processing remaining agents

### Requirement 6: Report Generation

**User Story:** As a presenter, I want a comprehensive PDF coaching report generated from all evaluation results, so that I receive detailed, actionable feedback similar to what an experienced presentation coach would provide.

#### Acceptance Criteria

1. WHEN all Evaluation_Agents for a session have completed and results are stored in S3, THE Report_Generator SHALL aggregate all evaluation results from the S3_Evaluation_Bucket for the given submission_id
2. THE Report_Generator SHALL produce a PDF document containing feedback for each evaluated dimension with specific, actionable coaching guidance
3. THE Report_Generator SHALL produce feedback comparable in quality and depth to what an experienced Toastmasters evaluator, executive presentation coach, or AWS re:Invent speaker mentor would provide
4. THE Report_Generator SHALL include in the Coaching_Report: an executive summary, per-dimension detailed feedback, specific strengths identified, areas for improvement with concrete suggestions, and an overall coaching assessment
5. WHEN the Report_Generator completes the PDF, THE Report_Generator SHALL store the Coaching_Report in S3 using the path: `reports/{user_id}/{submission_id}/coaching_report.pdf`
6. IF the Report_Generator fails to produce the PDF, THEN THE Session_Supervisor SHALL retry report generation up to a configurable maximum number of attempts before marking the submission as Failed

### Requirement 7: Bedrock AgentCore Integration

**User Story:** As a platform architect, I want the agentic evaluation to leverage Amazon Bedrock AgentCore components efficiently, so that the platform benefits from managed agent infrastructure and supports a path from MVP to production without re-architecture.

#### Acceptance Criteria

1. THE Session_Supervisor SHALL be implemented using Bedrock_AgentCore agent framework with memory, identity, and API components
2. THE Coaching_Supervisor SHALL be implemented using Bedrock_AgentCore reasoning and tool orchestration capabilities
3. THE Evaluation_Agents SHALL be implemented as Bedrock_AgentCore tools that can be invoked by the Coaching_Supervisor
4. THE platform SHALL use Bedrock_AgentCore memory to maintain session context during the evaluation lifecycle
5. THE platform architecture SHALL support local execution for development and testing without requiring re-architecture for cloud deployment

### Requirement 8: SQS FIFO Queue Hand-off Processing

**User Story:** As a platform architect, I want the hand-off between the Preparation Workflow and Agentic Evaluation to use a FIFO SQS queue, so that processing order is preserved and the two work units remain loosely coupled.

#### Acceptance Criteria

1. THE Session_Supervisor SHALL consume messages from the SQS_Handoff_Queue configured as a FIFO queue
2. THE Session_Supervisor SHALL process messages in the order received from the FIFO queue
3. THE Session_Supervisor SHALL acknowledge (delete) messages from the SQS_Handoff_Queue only after the evaluation session has been successfully initiated
4. IF the Session_Supervisor fails to initiate an evaluation session, THEN THE Session_Supervisor SHALL allow the message to return to the SQS_Handoff_Queue for reprocessing according to the queue retry policy
5. WHEN a message exceeds the maximum receive count on the SQS_Handoff_Queue, THE message SHALL be routed to the DLQ_Handoff_Consumer

### Requirement 9: Dead-Letter Queue and Failure Handling

**User Story:** As a platform operator, I want failed evaluation messages routed to a dead-letter queue and submissions marked as failed, so that no submission is silently lost and failures are visible for remediation.

#### Acceptance Criteria

1. WHEN a handoff message fails processing after all retry attempts, THE Session_Supervisor SHALL route the message to the DLQ_Handoff_Consumer
2. WHEN a message is placed on the DLQ_Handoff_Consumer, THE Session_Supervisor SHALL update the Processing_Status of the corresponding submission in the DynamoDB_Table to Failed
3. WHEN a message is placed on the DLQ_Handoff_Consumer, THE Session_Supervisor SHALL publish an error notification to the SNS_Topic containing the submission_id, failure reason, queue name, and timestamp in ISO 8601 format
4. IF an evaluation session fails midway (after some agents have completed), THEN THE Session_Supervisor SHALL update the Processing_Status to Failed in the DynamoDB_Table and publish an error notification to the SNS_Topic with details of which agents completed and which failed

### Requirement 10: Session Lifecycle and Status Management

**User Story:** As a platform operator, I want clear status tracking throughout the evaluation session, so that the state of each submission is always visible and auditable.

#### Acceptance Criteria

1. WHEN the Session_Supervisor begins an evaluation session, THE Session_Supervisor SHALL update the Processing_Status in the DynamoDB_Table to Evaluating
2. WHEN the Session_Supervisor transitions to report generation, THE Session_Supervisor SHALL update the Processing_Status in the DynamoDB_Table to Report_Generating
3. WHEN the Coaching_Report is successfully generated and stored, THE Session_Supervisor SHALL update the Processing_Status in the DynamoDB_Table to Completed
4. WHEN the Session_Supervisor updates the Processing_Status to Completed, THE Session_Supervisor SHALL store the S3 path of the Coaching_Report in the DynamoDB_Table submission record
5. IF any unrecoverable failure occurs during the evaluation session, THEN THE Session_Supervisor SHALL update the Processing_Status to Failed in the DynamoDB_Table with a failure reason

### Requirement 11: Error Notification and Observability

**User Story:** As a platform operator, I want errors and failures published to SNS throughout the evaluation process, so that the operations team can respond to problems and maintain platform health.

#### Acceptance Criteria

1. WHEN any component in the evaluation session fails after exhausting retries, THE Session_Supervisor SHALL publish an error notification to the SNS_Topic
2. THE SNS error notification SHALL contain the submission_id, component name that failed (agent name or service), error type, error message, retry count exhausted, and timestamp in ISO 8601 format
3. THE Session_Supervisor SHALL publish the SNS error notification on a best-effort basis without causing the evaluation session to fail if the SNS publish itself fails
4. WHEN the DLQ_Handoff_Consumer message count exceeds a configurable threshold, THE SNS_Topic SHALL receive a threshold alert notification

### Requirement 12: Extensibility and Future-Proofing

**User Story:** As a platform architect, I want the evaluation architecture to support adding new evaluators, tools, and analysis capabilities over time, so that the platform can grow without significant redesign.

#### Acceptance Criteria

1. THE platform SHALL define a standard Evaluation_Agent registration mechanism that allows new agents to be added through configuration rather than code changes to the orchestration layer
2. THE Coaching_Supervisor SHALL discover available Evaluation_Agents at runtime rather than relying on a hardcoded list
3. THE platform architecture SHALL support the addition of new Evaluation_Dimensions without modifying existing agent implementations
4. THE platform architecture SHALL support a progression from MVP/PoC to Pilot to Production without requiring re-architecture of the agent orchestration layer
