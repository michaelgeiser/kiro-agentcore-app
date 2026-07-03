# Requirements Document

## Introduction

The Administration Panel is a role-gated feature of the Presentation Coaching Platform that provides administrators with the ability to view and modify runtime environment variables and toggle feature flags without requiring redeployment. The panel is accessible only to users in the Cognito "administrators" group and is presented through a distinct visual theme (medium dark gray background) to differentiate it from the standard user experience. The panel consists of two pages: Environment Variables management and Feature Flags management, both accessible from an "Administration" hover menu in the navigation header.

Changes to environment variables are persisted to SSM Parameter Store and trigger an ECS service force-new-deployment so that new tasks pick up updated values immediately. Feature flag changes are persisted directly to SSM Parameter Store and take effect on the next Lambda cold start or Step Functions execution (no ECS redeployment needed for flags).

## Glossary

- **Administration_Menu**: A hover-triggered dropdown menu in the navigation bar, visible only to users with the Administrator role, providing links to the Environment Variables and Feature Flags pages
- **Environment_Variables_Page**: A lightbox dialog that displays all runtime environment variables with editable controls, allowing administrators to update values and persist changes
- **Feature_Flags_Page**: A page displaying all feature flags as visual toggle switches (on/off), allowing administrators to enable or disable platform features
- **Changed_Flag**: A per-variable dirty state indicator that tracks whether a value has been modified from its original value; reverts to clean if the value is changed back to its original
- **Toggle_Switch**: A mobile-style on/off slide control with visible "On"/"Off" text labels, used instead of checkboxes for feature flag state
- **Model_Dropdown**: A select control populated with current (non-legacy) Amazon and Anthropic foundation model IDs (hardcoded list), showing human-friendly display names while storing API-compatible model IDs as values
- **CRI**: Cross-Region Inference — a Bedrock routing mode that distributes requests across multiple AWS regions within a geography for higher throughput
- **SSM_Parameter_Store**: AWS Systems Manager Parameter Store — the backend service storing both environment variable values and feature flags as string parameters under defined prefixes
- **ECS_Force_Deployment**: An ECS UpdateService call with `forceNewDeployment=true` that causes the service to launch new tasks with updated configuration, replacing existing tasks gracefully

## Requirements

### Requirement 1: Administration Menu — Access and Visibility

**User Story:** As an administrator, I want a clearly visible menu entry in the navigation bar, so that I can quickly access administration functions without navigating away from the main application.

#### Acceptance Criteria

1. WHEN a user is authenticated AND belongs to the Cognito "administrators" group, THE SPA SHALL display an "Administration" text label in the navigation bar styled in red with bold font weight
2. WHEN a non-administrator user is authenticated, THE SPA SHALL NOT display the "Administration" label or any administration menu elements
3. WHEN a user hovers over the "Administration" label, THE SPA SHALL display a dropdown menu with two options: "Environment Variables" and "Feature Flags"
4. WHEN the user moves the mouse away from the "Administration" label and the dropdown, THE SPA SHALL hide the dropdown menu after a short delay (300ms) to allow mouse movement to the menu items
5. THE dropdown menu SHALL be styled consistently with the administration theme (medium dark gray background, appropriate contrast for text)

### Requirement 2: Administration Visual Theme

**User Story:** As an administrator, I want administration pages to be visually distinct from the standard user interface, so that I clearly know I am in an administrative context.

#### Acceptance Criteria

1. ALL administration pages and dialogs SHALL use a medium dark gray background color instead of the standard black background
2. THE administration theme SHALL adjust text colors, border colors, and accent colors as needed to maintain WCAG 4.5:1 minimum contrast ratio against the gray background
3. THE administration theme SHALL maintain the same font families, spacing units, and general layout patterns as the standard user interface
4. THE administration pages SHALL include a visual indicator (e.g., header bar or breadcrumb) identifying the current page as an administration context

### Requirement 3: Environment Variables Page — Display

**User Story:** As an administrator, I want to see all current environment variables and their values with descriptions, so that I can understand the current runtime configuration.

#### Acceptance Criteria

1. WHEN the user selects "Environment Variables" from the Administration menu, THE SPA SHALL open a lightbox dialog overlaying the current page
2. THE lightbox SHALL retrieve and display all runtime environment variables from the backend API
3. EACH variable SHALL be displayed with its name as a label, a brief text description of what it controls, and its current value in an editable input control
4. THE lightbox SHALL include a "Save Changes" button and a "Cancel" button
5. WHEN the user clicks "Cancel", THE lightbox SHALL close without persisting any changes
6. THE lightbox SHALL be scrollable if the number of variables exceeds the viewport height
7. THE following environment variables SHALL be displayed and editable:
   - `SESSION_SUPERVISOR_MODEL_ID` — "Foundation model used by the Session Supervisor agent"
   - `COACHING_SUPERVISOR_MODEL_ID` — "Foundation model used by the Coaching Supervisor agent"
   - `EVALUATION_MODEL_ID` — "Foundation model used by the individual evaluation agents"
   - `IDLE_TIMEOUT_MINUTES` — "Minutes of inactivity before the ECS evaluation task exits"
   - `MAX_CONCURRENT_EVALUATIONS` — "Maximum number of submissions processed simultaneously"
   - `COGNITO_USER_POOL_NAME` — "Name of the Cognito User Pool for user lookups"

### Requirement 4: Environment Variables — Model Selection Dropdowns

**User Story:** As an administrator, I want to select AI models from a predefined list of valid options, so that I cannot accidentally enter an invalid model identifier.

#### Acceptance Criteria

1. THE environment variables `SESSION_SUPERVISOR_MODEL_ID`, `COACHING_SUPERVISOR_MODEL_ID`, and `EVALUATION_MODEL_ID` SHALL each be rendered as a dropdown select control instead of a free-text input
2. THE dropdown SHALL be populated with a hardcoded list of current (non-legacy) Amazon and Anthropic large language models compatible with the Bedrock Converse API
3. THE model list SHALL include ONLY Amazon (Nova) and Anthropic (Claude) models; no other providers shall be included in this iteration
4. EACH dropdown option SHALL display a human-friendly name (e.g., "Amazon Nova Pro CRI") while storing the Bedrock model API identifier as its value (e.g., "us.amazon.nova-pro-v1:0")
5. FOR models available with Cross-Region Inference, THE dropdown SHALL include both a CRI variant (prefixed with "us.") and a Single Region variant (no prefix), clearly labeled
6. THE dropdown SHALL pre-select the option matching the currently set value
7. IF the currently set value does not match any valid dropdown option, THE dropdown SHALL display an "unselected" placeholder option indicating the value is invalid/legacy
8. THE "Save Changes" button SHALL be disabled if any model dropdown is in the "unselected" state
9. THE `MAX_CONCURRENT_EVALUATIONS` variable SHALL be rendered as a dropdown with options: 1, 2, 3, 5, 10

### Requirement 5: Environment Variables — Change Tracking

**User Story:** As an administrator, I want to know which values I have modified before saving, so that I can review my changes and avoid accidental updates.

#### Acceptance Criteria

1. THE lightbox SHALL maintain a Changed_Flag for each environment variable, initially set to false (unchanged)
2. WHEN an administrator modifies a variable's value to differ from its original loaded value, THE Changed_Flag for that variable SHALL be set to true
3. WHEN an administrator changes a variable's value back to its original loaded value, THE Changed_Flag for that variable SHALL be reset to false
4. THE UI SHALL provide a visual indication (e.g., highlight, icon, or border color change) for variables whose Changed_Flag is true
5. THE "Save Changes" button SHALL only persist variables whose Changed_Flag is true; unchanged variables SHALL NOT be written

### Requirement 6: Environment Variables — Persistence and Deployment

**User Story:** As an administrator, I want to save my changes and have the running application pick up the new values immediately, so that I can adjust configuration without manual redeployment.

#### Acceptance Criteria

1. WHEN the administrator clicks "Save Changes", THE SPA SHALL send only the changed variables to the backend API endpoint
2. THE backend API SHALL update the corresponding SSM parameters with the new values
3. THE backend API SHALL update the ECS task definition environment variables with the new values
4. THE backend API SHALL trigger an ECS service force-new-deployment (`UpdateService` with `forceNewDeployment=true`) so that new tasks launch with the updated configuration
5. AFTER successful persistence and deployment trigger, THE lightbox SHALL display a success message indicating "Configuration saved. ECS service redeployment triggered — new tasks will use updated values within minutes." and then close
6. IF the persistence or deployment trigger fails, THE lightbox SHALL display an error message with details and remain open so the administrator can retry
7. THE backend SHALL handle the case where no ECS tasks are currently running (desired_count=0) gracefully — update SSM and task definition without attempting force-deployment of a zero-task service

### Requirement 7: Feature Flags Page — Display and Toggle

**User Story:** As an administrator, I want to see all feature flags and quickly toggle them on or off, so that I can control platform behavior without code changes.

#### Acceptance Criteria

1. WHEN the user selects "Feature Flags" from the Administration menu, THE SPA SHALL navigate to a Feature Flags administration page
2. THE page SHALL retrieve and display all feature flags from the backend API (sourced from SSM Parameter Store)
3. EACH feature flag SHALL be displayed with its parameter name, a human-readable description, and a Toggle_Switch control showing its current state
4. THE Toggle_Switch SHALL visually resemble a mobile OS (iOS/Android) style slide toggle with clearly visible "On" and "Off" text labels — NOT a simple checkbox
5. WHEN the administrator toggles a switch, THE SPA SHALL immediately persist the new value to the backend API
6. AFTER successful persistence of a toggle change, THE SPA SHALL display a brief success confirmation (toast notification)
7. IF persistence of a toggle change fails, THE SPA SHALL revert the toggle to its previous state and display an error message
8. THE following feature flags SHALL be displayed with descriptions:
   - `video-processing-enabled` — "Allow video file uploads to be processed (audio extraction via MediaConvert)"
   - `batch-processing-enabled` — "Enable batch processing mode for embedding creation"
   - `embeddings-enabled` — "Create vector embeddings from audio chunks during preparation (when disabled, evaluation uses transcript only)"
   - `local-mode` — "Run evaluation agents in local mode (in-process Bedrock calls) vs. AgentCore managed mode"

### Requirement 8: Backend API — Administration Endpoints

**User Story:** As a developer, I want dedicated API endpoints for administration operations, so that the admin panel can read and write configuration securely.

#### Acceptance Criteria

1. THE backend SHALL expose a `GET /admin/environment-variables` endpoint that returns all configurable environment variables with their current values and text descriptions
2. THE backend SHALL expose a `PUT /admin/environment-variables` endpoint that accepts a map of variable names to new values, persists them to SSM and the ECS task definition, and triggers an ECS force-new-deployment
3. THE backend SHALL expose a `GET /admin/feature-flags` endpoint that returns all feature flags with their current boolean state and text descriptions
4. THE backend SHALL expose a `PUT /admin/feature-flags/{flag-name}` endpoint that accepts a new boolean state for a single flag and persists it to SSM Parameter Store
5. ALL administration endpoints SHALL require a valid JWT token from a user in the "administrators" Cognito group; non-admin requests SHALL receive a 403 response
6. THE API Gateway SHALL use the existing JWT authorizer; the backend Lambda SHALL additionally verify the `cognito:groups` claim contains "administrators" (defense in depth)
7. THE `GET /admin/environment-variables` endpoint SHALL read current values from SSM Parameter Store (source of truth) rather than from the ECS task definition directly
8. THE `PUT /admin/environment-variables` endpoint SHALL return a response body including: list of updated variables, ECS deployment status, and a human-readable message

### Requirement 9: Security and Authorization

**User Story:** As a platform owner, I want administration functions to be strictly limited to authorized administrators, so that regular users cannot modify system configuration.

#### Acceptance Criteria

1. THE administration menu, pages, and API endpoints SHALL only be accessible to users whose Cognito JWT token contains "administrators" in the `cognito:groups` claim
2. THE backend Lambda functions for administration endpoints SHALL independently verify the administrator group membership from the JWT token (defense in depth)
3. IF a non-administrator user attempts to access an administration API endpoint directly, THE API SHALL return a 403 Forbidden response
4. THE frontend SHALL NOT expose administration routes or menu elements to non-administrator users even via direct URL navigation
5. THE Lambda execution role for administration endpoints SHALL have least-privilege IAM permissions: SSM read/write for the specific parameter prefixes, ECS UpdateService and RegisterTaskDefinition for the specific cluster/service, and ECS DescribeTaskDefinition for reading current config

### Requirement 10: Documentation Updates

**User Story:** As a developer or operator, I want updated documentation reflecting the new administration capabilities, so that I can understand and maintain the system.

#### Acceptance Criteria

1. THE project-overview.md SHALL be updated to reference the administration panel as part of the platform's capabilities
2. A new `documentation/admin-panel.md` document SHALL be created describing: the administration feature, API endpoints, how environment variables are persisted and deployed, how feature flags work, and the security model
3. THE existing `documentation/model-configuration.md` SHALL be updated to reference the admin panel as the preferred method for changing model IDs (in addition to the existing env var documentation)
4. THE admin panel documentation SHALL include the complete list of supported model IDs with their display names for reference
5. THE documentation SHALL explain the ECS force-deployment behavior and expected timeline for changes to take effect

