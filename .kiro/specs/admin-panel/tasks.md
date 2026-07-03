# Implementation Plan: Administration Panel

## Overview

This plan implements a role-gated administration panel for the Presentation Coaching Platform. The implementation is split across frontend (vanilla JS SPA) and backend (Python Lambda + CDK), following the existing project patterns. The approach builds infrastructure and shared utilities first, then backend handlers, then frontend views, wiring everything together at the end.

## Tasks

- [x] 1. Backend shared utilities and authorization
  - [x] 1.1 Create admin authorization helper module
    - Create `upload-service/src/utils/admin_auth.py`
    - Implement `verify_admin(event)` function that extracts JWT claims from `event["requestContext"]["authorizer"]["jwt"]["claims"]`
    - Check `cognito:groups` claim contains "administrators"
    - Return `(True, user_id)` if admin, `(False, None)` if not
    - Follow error handling pattern: non-admin → immediate 403 (unrecoverable)
    - _Requirements: 9.1, 9.2, 8.5, 8.6_

  - [x] 1.2 Write property test for admin authorization (Property 8)
    - **Property 8: Non-administrator requests receive 403**
    - Generate random JWT claims without "administrators" in cognito:groups
    - Verify that `verify_admin` returns `(False, None)` for all generated non-admin claims
    - Also verify that claims WITH "administrators" return `(True, user_id)`
    - Use Hypothesis library with minimum 100 iterations
    - **Validates: Requirements 8.5, 8.6, 9.1, 9.2, 9.3**

  - [x] 1.3 Create ECS deployment service module
    - Create `upload-service/src/services/ecs_service.py`
    - Implement `EcsService` class with `update_task_environment(task_family, env_updates)` method
    - Implement `force_new_deployment(cluster, service, task_definition_arn)` method
    - Handle `desired_count=0` case: skip force-deploy, return `deploymentStatus: "skipped_no_running_tasks"`
    - Use exponential backoff + jitter for recoverable ECS API errors (throttling, service unavailable)
    - Fail immediately for unrecoverable errors (access denied, resource not found)
    - _Requirements: 6.3, 6.4, 6.7_

  - [x] 1.4 Write unit tests for ECS deployment service
    - Test `update_task_environment` registers new task definition with updated env vars (mocked boto3)
    - Test `force_new_deployment` calls UpdateService with forceNewDeployment=true
    - Test `force_new_deployment` skips when desired_count=0
    - Test retry behavior on throttling exceptions
    - Test immediate failure on access denied
    - _Requirements: 6.3, 6.4, 6.7_

- [x] 2. Backend Lambda handlers
  - [x] 2.1 Implement admin environment variables handler
    - Create `upload-service/src/handlers/admin_env_vars.py`
    - Implement `handler(event, context)` function routing GET and PUT methods
    - GET: Read all env var values from SSM under `/prescoach/{env}/admin/env-vars/` prefix
    - GET: Return variables with name, value, description, and inputType fields
    - PUT: Validate request body contains `variables` map with only known variable names
    - PUT: Write each changed variable to SSM via `put_parameter`
    - PUT: Call EcsService to update task definition and trigger force-deployment
    - PUT: Return response with `updatedVars`, `deploymentStatus`, and `message` fields
    - Use `verify_admin` for defense-in-depth authorization check
    - Reject unknown variable names with 400 (unrecoverable)
    - Retry SSM throttling with exponential backoff (recoverable)
    - _Requirements: 8.1, 8.2, 8.5, 8.6, 8.7, 8.8, 6.1, 6.2, 6.3, 6.4, 6.7_

  - [x] 2.2 Write property test for PUT environment-variables response (Property 9)
    - **Property 9: PUT environment-variables response contains required fields**
    - Generate random sets of valid variable names and values
    - Mock SSM and ECS calls to succeed
    - Verify response body always contains `updatedVars` (array), `deploymentStatus` (string), `message` (string)
    - Verify `updatedVars` contains exactly the variable names that were in the request
    - Use Hypothesis library with minimum 100 iterations
    - **Validates: Requirements 8.8**

  - [x] 2.3 Write unit tests for admin environment variables handler
    - Test GET returns correct structure with all 6 variables
    - Test PUT calls SSM put_parameter for each changed variable
    - Test PUT calls ECS register_task_definition with correct env vars
    - Test PUT skips force-deploy when desired_count=0
    - Test non-admin request returns 403
    - Test invalid variable name returns 400
    - Test malformed request body returns 400
    - _Requirements: 8.1, 8.2, 8.7, 8.8, 6.7_

  - [x] 2.4 Implement admin feature flags handler
    - Create `upload-service/src/handlers/admin_feature_flags.py`
    - Implement `handler(event, context)` function routing GET and PUT methods
    - GET: Read all feature flag values from SSM under `/prescoach/{env}/feature-flags/` prefix
    - GET: Return flags with name, enabled (boolean), and description fields
    - PUT: Extract flag name from path parameters, validate it's a known flag
    - PUT: Write new boolean value to SSM as "true"/"false" string
    - PUT: Return response with name and enabled fields
    - Use `verify_admin` for defense-in-depth authorization check
    - Reject unknown flag names with 404 (unrecoverable)
    - Retry SSM throttling with exponential backoff (recoverable)
    - _Requirements: 8.3, 8.4, 8.5, 8.6_

  - [x] 2.5 Write unit tests for admin feature flags handler
    - Test GET returns all 4 flags with correct boolean values
    - Test PUT updates single parameter in SSM
    - Test non-admin request returns 403
    - Test invalid flag name returns 404
    - Test malformed request body returns 400
    - _Requirements: 8.3, 8.4, 8.5, 8.6_

- [x] 3. Checkpoint - Backend handlers complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. CDK infrastructure changes
  - [x] 4.1 Add admin Lambda functions and API routes to CDK stack
    - Modify `upload-service/cdk/upload_service/upload_service_stack.py`
    - Add `admin-env-vars` Lambda function with appropriate environment variables (SSM prefix, ECS cluster/service name, task family)
    - Add `admin-feature-flags` Lambda function with appropriate environment variables (SSM prefix)
    - Add 4 API Gateway routes: GET/PUT `/admin/environment-variables`, GET `/admin/feature-flags`, PUT `/admin/feature-flags/{flag-name}`
    - Attach existing JWT authorizer to all admin routes
    - Add IAM policies: SSM read/write for `/prescoach/{env}/admin/env-vars/*` and `/prescoach/{env}/feature-flags/*`
    - Add IAM policies: ECS DescribeTaskDefinition, RegisterTaskDefinition, UpdateService, DescribeServices (scoped to evaluation cluster/service)
    - Update CORS configuration to include PUT method
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 9.5_

  - [x] 4.2 Write CDK assertion tests for admin infrastructure
    - Test admin Lambda functions created with correct environment variables
    - Test API Gateway routes created for all 4 admin endpoints
    - Test IAM policies grant least-privilege access to SSM prefixes
    - Test IAM policies grant ECS permissions scoped to correct cluster/service
    - Test CORS configuration includes PUT method
    - _Requirements: 8.5, 9.5_

- [x] 5. Frontend admin API client and utilities
  - [x] 5.1 Create admin API client module
    - Create `webapp/js/admin-api.js`
    - Implement `getEnvironmentVariables()` — GET `/admin/environment-variables` with JWT auth header
    - Implement `updateEnvironmentVariables(changedVars)` — PUT `/admin/environment-variables` with JWT auth header
    - Implement `getFeatureFlags()` — GET `/admin/feature-flags` with JWT auth header
    - Implement `updateFeatureFlag(flagName, enabled)` — PUT `/admin/feature-flags/{flagName}` with JWT auth header
    - Follow existing `api.js` patterns for fetch, error handling, and token management
    - _Requirements: 8.1, 8.2, 8.3, 8.4_

  - [x] 5.2 Add admin role check to auth module
    - Extend `webapp/js/auth.js` with `isAdmin()` function
    - Parse JWT token to check `cognito:groups` claim contains "administrators"
    - Return boolean indicating admin status
    - _Requirements: 1.1, 1.2, 9.1, 9.4_

- [x] 6. Frontend admin menu and navigation
  - [x] 6.1 Implement admin hover menu component
    - Create `webapp/js/views/admin-menu.js`
    - Implement `renderAdminMenu(navContainer)` function
    - Render "Administration" label styled in red with bold font weight
    - On hover: show dropdown with "Environment Variables" and "Feature Flags" links
    - Implement 300ms hide delay on mouse-out to allow cursor travel to menu items
    - Only call `renderAdminMenu` when `isAdmin()` returns true
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

  - [x] 6.2 Add admin CSS styles
    - Create `webapp/css/admin.css` (or extend existing CSS)
    - Define medium dark gray background color for admin context
    - Ensure text colors maintain WCAG 4.5:1 contrast ratio against gray background
    - Style hover dropdown menu with admin theme
    - Style toggle switches (iOS-style slide toggle with On/Off labels)
    - Style lightbox overlay and modal dialog
    - Style change indicators for modified variables
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [x] 6.3 Register admin routes in router
    - Update `webapp/js/router.js` to add `#feature-flags` route
    - Gate admin routes: if `isAdmin()` is false, redirect to main page
    - Block direct URL navigation to admin routes for non-admins
    - _Requirements: 9.4_

- [x] 7. Frontend environment variables lightbox
  - [x] 7.1 Implement environment variables lightbox view
    - Create `webapp/js/views/env-vars.js`
    - Implement `openEnvVarsLightbox()` function
    - On open: fetch current values from admin API, render lightbox modal
    - Render each variable with name label, description, and appropriate input control
    - For model IDs: render `<select>` dropdown populated from `MODEL_OPTIONS` array
    - For `MAX_CONCURRENT_EVALUATIONS`: render dropdown with options [1, 2, 3, 5, 10]
    - For other variables: render `<input type="text">`
    - Export `MODEL_OPTIONS` array with all Amazon Nova and Anthropic Claude models (CRI and Single Region variants)
    - Export `CONCURRENCY_OPTIONS = [1, 2, 3, 5, 10]`
    - Pre-select dropdown option matching current value; show placeholder if value is invalid/legacy
    - _Requirements: 3.1, 3.2, 3.3, 3.6, 3.7, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.9_

  - [x] 7.2 Implement change tracking and save logic
    - Track Changed_Flag per variable: set true when value differs from original, reset to false when reverted
    - Provide visual indication (e.g., border color change) for modified variables
    - Disable "Save Changes" button when any model dropdown is in unselected/placeholder state
    - On Save: construct payload with only changed variables, call `updateEnvironmentVariables`
    - On success: show success message, close lightbox
    - On failure: show error message, keep lightbox open for retry
    - On Cancel: close lightbox without persisting
    - _Requirements: 3.4, 3.5, 4.8, 5.1, 5.2, 5.3, 5.4, 5.5, 6.1, 6.5, 6.6_

  - [x] 7.3 Write property tests for environment variable rendering (Properties 1, 2, 3)
    - **Property 1: Variable rendering includes all required fields**
    - Generate random variable objects with non-empty name, description, and value
    - Verify rendered HTML contains the variable name as label, description text, and editable input control with current value
    - **Property 2: Input type determines rendered control type**
    - Generate random variables with inputType "model-dropdown" or "text"
    - Verify "model-dropdown" renders a `<select>` element; "text" renders an `<input type="text">`
    - **Property 3: Dropdown selection reflects current value validity**
    - Generate random model IDs (both valid from MODEL_OPTIONS and invalid arbitrary strings)
    - Verify valid IDs result in pre-selected option; invalid IDs show placeholder state
    - Use fast-check library with minimum 100 iterations per property
    - **Validates: Requirements 3.3, 4.1, 4.4, 4.6, 4.7**

  - [x] 7.4 Write property tests for change tracking (Properties 4, 5)
    - **Property 4: Change tracking round-trip preserves clean state**
    - Generate random original/modified value pairs
    - Verify: change to different value → Changed_Flag true; change back to original → Changed_Flag false
    - **Property 5: Save payload contains exactly the changed variables**
    - Generate random sets of variables with mixed Changed_Flag states
    - Verify payload includes all and only variables with Changed_Flag true
    - Use fast-check library with minimum 100 iterations per property
    - **Validates: Requirements 5.1, 5.2, 5.3, 5.5, 6.1**

- [x] 8. Frontend feature flags page
  - [x] 8.1 Implement feature flags page view
    - Create `webapp/js/views/feature-flags.js`
    - Implement `render(outlet)` function for the `#feature-flags` route
    - On render: fetch all flags from admin API, display with admin theme
    - Render each flag with parameter name, description, and iOS-style toggle switch
    - Toggle switch shows visible "On"/"Off" text labels (not a simple checkbox)
    - Set toggle initial state from API response `enabled` boolean
    - On toggle: immediately call `updateFeatureFlag(flagName, newState)`
    - On success: show brief toast notification confirming the change
    - On failure: revert toggle to previous state, show error message
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8_

  - [x] 8.2 Write property tests for feature flag rendering and toggle behavior (Properties 6, 7)
    - **Property 6: Feature flag rendering includes all required fields**
    - Generate random feature flag objects with non-empty name, description, and boolean state
    - Verify rendered output contains the flag's parameter name, description, and toggle reflecting boolean state
    - **Property 7: Failed toggle reverts to original state**
    - Generate random flag states and toggle directions
    - Mock API to fail
    - Verify toggle reverts to the original state prior to the toggle attempt
    - Use fast-check library with minimum 100 iterations per property
    - **Validates: Requirements 7.3, 7.7**

- [x] 9. Checkpoint - Frontend views complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. Integration wiring and end-to-end validation
  - [x] 10.1 Wire admin menu into main application
    - Update `webapp/js/app.js` to import and call `renderAdminMenu` when `isAdmin()` is true
    - Ensure admin menu renders in the navigation bar after authentication
    - Connect "Environment Variables" link to `openEnvVarsLightbox()`
    - Connect "Feature Flags" link to navigate to `#feature-flags` route
    - Include admin CSS in `webapp/index.html`
    - _Requirements: 1.1, 1.2, 1.3_

  - [x] 10.2 Write integration tests for backend API flows
    - Test full flow: GET env vars → modify → PUT → verify SSM updated (mocked AWS clients)
    - Test full flow: GET flags → toggle one → verify SSM updated (mocked AWS clients)
    - Test ECS deployment flow: PUT env vars → verify task definition registered → verify update_service called
    - Test end-to-end admin auth: non-admin token → verify 403 from each endpoint
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 6.2, 6.3, 6.4_

- [x] 11. Documentation updates
  - [x] 11.1 Create admin panel documentation
    - Create `documentation/admin-panel.md` describing the administration feature
    - Document API endpoints (request/response schemas)
    - Document how environment variables are persisted and deployed
    - Document how feature flags work and take effect
    - Document the security model (Cognito groups, JWT verification, defense in depth)
    - Include the complete list of supported model IDs with display names
    - Document ECS force-deployment behavior and expected timeline
    - _Requirements: 10.2, 10.4, 10.5_

  - [x] 11.2 Update existing documentation
    - Update `documentation/project-overview.md` to reference the administration panel
    - Update `documentation/model-configuration.md` to reference the admin panel as preferred method for changing model IDs
    - _Requirements: 10.1, 10.3_

- [x] 12. Final checkpoint - All tasks complete
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- Backend uses Python (Hypothesis for property tests, pytest for unit tests)
- Frontend uses JavaScript (fast-check for property tests, Vitest for unit tests)
- Follow the error-handling steering: unrecoverable errors (invalid params, non-admin) fail immediately; recoverable errors (SSM throttling, ECS unavailable) retry with exponential backoff + jitter

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "5.1", "5.2", "6.2"] },
    { "id": 1, "tasks": ["1.2", "1.3", "6.1", "6.3"] },
    { "id": 2, "tasks": ["1.4", "2.1", "2.4"] },
    { "id": 3, "tasks": ["2.2", "2.3", "2.5", "4.1"] },
    { "id": 4, "tasks": ["4.2", "7.1"] },
    { "id": 5, "tasks": ["7.2", "8.1"] },
    { "id": 6, "tasks": ["7.3", "7.4", "8.2"] },
    { "id": 7, "tasks": ["10.1"] },
    { "id": 8, "tasks": ["10.2", "11.1", "11.2"] }
  ]
}
```
