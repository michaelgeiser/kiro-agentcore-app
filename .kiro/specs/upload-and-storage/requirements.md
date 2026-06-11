# Requirements Document

## Introduction

The Upload and Storage service is the backend component of the Presentation Coaching Platform responsible for receiving presentation files from the Frontend SPA, storing them in S3 with a consistent naming convention, persisting submission metadata in DynamoDB, and publishing messages to an SQS queue to trigger downstream processing. The service exposes RESTful endpoints through API Gateway and authenticates requests using Cognito JWT tokens. The architecture is designed to scale cleanly from MVP through Pilot to Production without re-architecture.

## Glossary

- **Upload_Service**: The backend service that handles file upload requests, stores files, persists metadata, and publishes processing messages
- **API_Gateway**: AWS API Gateway — the managed service exposing RESTful upload endpoints to the Frontend SPA
- **S3_Bucket**: The AWS S3 bucket configured to store uploaded presentation files
- **DynamoDB_Table**: The AWS DynamoDB table used to store submission metadata (run information)
- **SQS_Queue**: The AWS SQS queue that receives messages when a file is successfully uploaded, triggering the Preparation Workflow
- **SNS_Topic**: The AWS SNS topic used to communicate error notifications and threshold alerts
- **Cognito**: AWS Cognito — the authentication service that manages user registration, sign-in, and issues JWT tokens used to authorize API requests
- **Cognito_User_Pool**: The AWS Cognito User Pool that stores user accounts, handles sign-up/sign-in flows, and issues JWTs
- **Cognito_App_Client**: The User Pool App Client configuration that enables the Frontend SPA to authenticate users via OAuth 2.0 Authorization Code Grant with PKCE
- **Cognito_Hosted_UI**: The Cognito-managed login/signup web pages served at a configured domain prefix
- **JWT_Access_Token**: A short-lived JSON Web Token issued by Cognito, included in the Authorization header of upload requests
- **PKCE**: Proof Key for Code Exchange — an OAuth 2.0 extension that secures the Authorization Code flow for public clients (SPAs) without requiring a client secret
- **Submission_Record**: A DynamoDB item containing metadata about an uploaded file including file name, description, upload date, processing status, completion date, and report link
- **File_Key**: The S3 object key generated using the platform naming convention to uniquely identify a stored file
- **Processing_Status**: The state of a submission in the analysis pipeline (Pending, Processing, Completed, Failed)
- **Preparation_Workflow**: The downstream processing pipeline triggered by the SQS message after successful upload

## Requirements

### Requirement 1: Upload Endpoint

**User Story:** As a frontend application, I want to send presentation files and metadata to a RESTful API endpoint, so that the platform can receive and process user submissions.

#### Acceptance Criteria

1. THE Upload_Service SHALL expose a POST endpoint through the API_Gateway for receiving file uploads with associated metadata
2. WHEN the API_Gateway receives an upload request, THE Upload_Service SHALL accept the uploaded file along with the following metadata fields: presentation title (required), description (optional), and original file name
3. THE Upload_Service SHALL accept audio files in MP3, WAV, M4A, and AAC formats and video files in MP4, MOV, and WebM formats
4. IF the upload request contains a file with an unsupported format, THEN THE Upload_Service SHALL return a 400 Bad Request response with a message specifying the accepted file formats
5. IF the upload request contains a file exceeding 500 MB, THEN THE Upload_Service SHALL return a 413 Payload Too Large response with a message indicating the maximum allowed file size
6. IF the upload request is missing a required metadata field (presentation title), THEN THE Upload_Service SHALL return a 400 Bad Request response identifying the missing field

### Requirement 2: Authentication and Authorization

**User Story:** As a platform operator, I want upload requests authenticated via Cognito JWT tokens, so that only authorized users can submit files.

#### Acceptance Criteria

1. THE Upload_Service SHALL provision a Cognito User Pool with email as the sign-in alias and self sign-up enabled, so that users can register and authenticate without manual provisioning
2. THE Upload_Service SHALL configure a Cognito User Pool App Client that supports the OAuth 2.0 Authorization Code Grant with PKCE (Proof Key for Code Exchange) and does not require a client secret, enabling secure authentication from the single-page application
3. THE Upload_Service SHALL configure the Cognito User Pool App Client with OAuth scopes openid, profile, and email, and set callback URLs for the production domain (`https://kiro.geiserai.com`) and local development (`http://localhost:5500`)
4. THE API_Gateway SHALL require a valid Cognito JWT_Access_Token in the Authorization header for all upload endpoint requests, using a native JWT authorizer configured with the Cognito User Pool issuer URL and App Client audience
5. IF the API_Gateway receives a request without a JWT_Access_Token, THEN THE API_Gateway SHALL return a 401 Unauthorized response
6. IF the API_Gateway receives a request with an expired or invalid JWT_Access_Token, THEN THE API_Gateway SHALL return a 401 Unauthorized response
7. WHEN the API_Gateway validates a JWT_Access_Token, THE Upload_Service SHALL extract the authenticated user identifier from the token claims (`sub`) for associating the submission with the user
8. THE Upload_Service SHALL export the Cognito User Pool ID, App Client ID, and hosted UI domain as infrastructure outputs, so that the Frontend SPA can configure its authentication module

### Requirement 3: File Storage in S3

**User Story:** As a platform operator, I want uploaded files stored in S3 with a consistent naming convention, so that files are uniquely identified and organized for downstream processing.

#### Acceptance Criteria

1. WHEN a file passes validation, THE Upload_Service SHALL store the file in the configured S3_Bucket
2. THE Upload_Service SHALL generate a File_Key using the naming convention: `uploads/{user_id}/{submission_id}/{original_filename}` where submission_id is a unique identifier generated at upload time
3. THE Upload_Service SHALL preserve the original file extension in the File_Key
4. WHEN storing a file, THE Upload_Service SHALL set the S3 object content type to match the uploaded file MIME type
5. IF the S3 upload operation fails, THEN THE Upload_Service SHALL return a 500 Internal Server Error response to the client and publish an error notification to the SNS_Topic

### Requirement 4: Metadata Persistence in DynamoDB

**User Story:** As a platform operator, I want submission metadata stored in DynamoDB, so that the platform can track uploads and their processing status throughout the pipeline.

#### Acceptance Criteria

1. WHEN a file is successfully stored in S3, THE Upload_Service SHALL create a Submission_Record in the DynamoDB_Table
2. THE Submission_Record SHALL contain the following attributes: submission_id (partition key), user_id, original_file_name, presentation_title, description, s3_file_key, upload_date (ISO 8601 format), processing_status (set to Pending), completion_date (null), and report_link (null)
3. THE Upload_Service SHALL generate a unique submission_id for each upload using a UUID v4 format
4. IF the DynamoDB write operation fails, THEN THE Upload_Service SHALL delete the previously stored S3 object to maintain consistency and return a 500 Internal Server Error response to the client
5. IF the DynamoDB write operation fails and the compensating S3 deletion also fails, THEN THE Upload_Service SHALL publish an error notification to the SNS_Topic including the orphaned S3 File_Key for manual remediation

### Requirement 5: SQS Message Publication

**User Story:** As a platform operator, I want a message published to SQS after successful upload, so that the Preparation Workflow is triggered automatically without polling.

#### Acceptance Criteria

1. WHEN a Submission_Record is successfully persisted in DynamoDB, THE Upload_Service SHALL publish a message to the SQS_Queue
2. THE SQS message body SHALL contain the submission_id, user_id, s3_file_key, original_file_name, and presentation_title
3. IF the SQS publish operation fails, THEN THE Upload_Service SHALL retry the publish operation up to 3 times with exponential backoff
4. IF the SQS publish operation fails after all retry attempts, THEN THE Upload_Service SHALL update the Submission_Record processing_status to Failed, publish an error notification to the SNS_Topic, and return a 500 Internal Server Error response to the client

### Requirement 6: Upload Response

**User Story:** As a frontend application, I want a clear success or failure response after submitting metadata, so that the user interface can proceed with the file upload using the presigned URL.

#### Acceptance Criteria

1. WHEN metadata is validated and a presigned URL is generated successfully, THE Upload_Service SHALL return a 201 Created response containing `submissionId`, `presignedUrl`, and `status` (set to "Pending") using camelCase field names
2. THE Upload_Service SHALL return all error responses in a consistent JSON format containing an error code, a human-readable message, and a correlation identifier for troubleshooting
3. WHEN the Upload_Service returns a successful response, THE Frontend SPA SHALL use the `presignedUrl` to upload the file directly to S3 with progress tracking, and use `submissionId` to track processing status

### Requirement 7: Submission Retrieval

**User Story:** As a frontend application, I want to retrieve the list of submissions for a user, so that the List View can display submission history and processing status.

#### Acceptance Criteria

1. THE Upload_Service SHALL expose a GET endpoint through the API_Gateway for retrieving submissions belonging to the authenticated user
2. WHEN the GET endpoint is called, THE Upload_Service SHALL query the DynamoDB_Table for all Submission_Records matching the authenticated user_id
3. THE Upload_Service SHALL return each Submission_Record mapped to the Frontend SPA's expected field names: `id`, `title`, `fileName`, `description`, `dateUploaded`, `status`, `dateCompleted`, and `reportUrl`
4. THE Upload_Service SHALL return submissions sorted by upload_date in descending order (most recent first)
5. IF no submissions exist for the authenticated user, THEN THE Upload_Service SHALL return a 200 OK response with an empty submissions array

### Requirement 8: Error Notification

**User Story:** As a platform operator, I want errors and threshold issues published to SNS, so that the operations team can respond to failures and prevent data loss.

#### Acceptance Criteria

1. WHEN an infrastructure-level failure occurs (S3 write failure, DynamoDB write failure, or SQS publish exhaustion), THE Upload_Service SHALL publish an error notification to the SNS_Topic
2. THE SNS error notification SHALL contain the submission_id (if available), error type, error message, timestamp (ISO 8601 format), and the service component that encountered the failure
3. THE Upload_Service SHALL publish the SNS error notification on a best-effort basis without failing the client request if the SNS publish itself fails

### Requirement 9: Scalability and Architecture

**User Story:** As a platform architect, I want the upload service designed for clean scaling from MVP to Production, so that growth does not require re-architecture.

#### Acceptance Criteria

1. THE Upload_Service SHALL use stateless request handling so that multiple instances can serve requests concurrently without shared in-memory state
2. THE Upload_Service SHALL use DynamoDB on-demand capacity mode to scale read and write throughput automatically with traffic
3. THE Upload_Service SHALL use S3 standard storage class for uploaded files to balance cost and durability
4. THE Upload_Service SHALL decouple file processing from file upload by using the SQS_Queue as the sole trigger for the Preparation_Workflow

### Requirement 10: Frontend SPA Integration

**User Story:** As a developer, I want the backend and frontend to use a consistent API contract and shared configuration, so that the full platform works end-to-end after deployment.

#### Acceptance Criteria

1. THE Upload_Service GET /submissions endpoint SHALL return submission records using field names that the Frontend SPA List View expects: `id`, `title`, `fileName`, `description`, `dateUploaded`, `status`, `dateCompleted`, and `reportUrl`
2. THE Upload_Service POST /submissions endpoint SHALL accept a JSON body containing `title` (required), `description` (optional), `fileName` (required), `contentType` (required), and `fileSizeBytes` (required), and SHALL return a JSON response containing `submissionId`, `presignedUrl`, and `status`
3. THE Frontend SPA upload flow SHALL use a two-step process: first POST metadata to /submissions to receive a presigned S3 URL, then PUT the file directly to S3 using the presigned URL with upload progress tracking
4. THE Frontend SPA SHALL read the Cognito User Pool domain, App Client ID, and API Gateway endpoint URL from a configuration file (`webapp/js/config.js`) that is populated from CDK stack outputs after deployment
5. THE Upload_Service CDK stack SHALL output the API Gateway endpoint URL in addition to the Cognito outputs, so the frontend configuration can be generated from a single `cdk deploy` output
6. THE Frontend SPA SHALL NOT use a separate `GET /submissions/{id}/report` endpoint; the report URL SHALL be provided as the `reportUrl` field in the submissions list response

### Requirement 11: Resource Naming Convention and Multi-Instance Deployment

**User Story:** As a platform operator, I want to deploy multiple isolated instances of the platform in a single AWS account (e.g., per-customer or per-environment), with all related resources clearly identifiable by a consistent naming convention.

#### Acceptance Criteria

1. ALL AWS resources provisioned by the CDK stack SHALL follow the naming convention `{appName}-{envName}-{instanceId}-{resourceName}` where:
   - `appName` is a short application identifier (default: `prescoach`)
   - `envName` is the deployment environment (e.g., `dev`, `test`, `prod`)
   - `instanceId` is an alphanumeric identifier for the deployment instance (e.g., a customer ID or tenant ID)
   - `resourceName` is a descriptive name indicating the resource's purpose
2. THE CDK stack SHALL accept `appName`, `envName`, and `instanceId` as deployment parameters (via CDK context), enabling multiple independent instances to coexist in a single AWS account without name collisions
3. THE CloudFormation stack name SHALL follow the pattern `{appName}-{envName}-{instanceId}` (e.g., `prescoach-prod-acme123`)
4. THE following resources SHALL use the naming convention:
   - S3 Bucket: `{appName}-{envName}-{instanceId}-uploads`
   - DynamoDB Table: `{appName}-{envName}-{instanceId}-submissions`
   - Cognito User Pool: `{appName}-{envName}-{instanceId}-users`
   - Cognito Hosted UI Domain prefix: `{appName}-{envName}-{instanceId}`
   - SQS Queue: `{appName}-{envName}-{instanceId}-processing-queue`
   - SQS Dead Letter Queue: `{appName}-{envName}-{instanceId}-processing-dlq`
   - SNS Topic: `{appName}-{envName}-{instanceId}-errors`
   - HTTP API Gateway: `{appName}-{envName}-{instanceId}-api`
   - Lambda functions: `{appName}-{envName}-{instanceId}-upload`, `{appName}-{envName}-{instanceId}-get-submissions`, `{appName}-{envName}-{instanceId}-confirm-upload`
5. THE naming convention SHALL ensure all resource names remain within AWS service limits (S3 bucket: max 63 characters, Cognito domain prefix: max 63 characters, Lambda function name: max 64 characters)
6. THE CDK stack SHALL validate that the combined `{appName}-{envName}-{instanceId}` prefix does not exceed 40 characters, leaving room for resource name suffixes within AWS limits
7. THE `instanceId` parameter SHALL accept lowercase alphanumeric characters and hyphens, with a minimum length of 2 and maximum length of 20 characters
8. ALL resources within a single deployment instance SHALL be tagged with `app`, `env`, and `instance` tags matching their naming convention values, enabling cost allocation and resource grouping
