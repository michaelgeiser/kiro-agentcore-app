# Implementation Plan: Frontend SPA

## Overview

This plan implements a vanilla JavaScript single-page application for the Presentation Coaching Platform. The SPA uses ES modules, hash-based routing, Cognito PKCE authentication, and is designed for S3/CloudFront static hosting. Implementation proceeds from foundational project structure and theming, through core modules (router, auth, API client), to the two views (Upload Page, List View), and finally integration wiring. Testing uses Vitest with fast-check for property-based tests.

## Tasks

- [x] 1. Set up project structure, tooling, and theme foundation
  - [x] 1.1 Create directory structure and index.html shell
    - Create the `webapp/` directory structure as defined in design (css/, js/, js/views/, js/utils/, assets/icons/, tests/properties/, tests/unit/, tests/integration/)
    - Create `webapp/index.html` with semantic HTML structure (header, nav, main#app-outlet, footer)
    - Include script tag for `js/app.js` with `type="module"`
    - Include link tags for theme.css, layout.css, components.css
    - _Requirements: 1.2, 1.4, 10.3_

  - [x] 1.2 Create CSS theme file with brand tokens
    - Create `webapp/css/theme.css` with CSS custom properties for: primary color, secondary color, background color, text color, error color, success color, heading font family, body font family, base spacing unit, border radii
    - _Requirements: 9.1, 9.2, 9.3, 9.4_

  - [x] 1.3 Create responsive layout CSS
    - Create `webapp/css/layout.css` with mobile-first responsive grid layout
    - Define CSS breakpoints for small (320px–767px), medium (768px–1023px), large (1024px–1920px)
    - Implement responsive navigation with hamburger collapse below 768px
    - Include visible focus indicators for keyboard navigation
    - Use CSS custom properties from theme.css for all values
    - _Requirements: 10.1, 10.2, 10.4, 10.6, 10.7_

  - [x] 1.4 Create component styles CSS
    - Create `webapp/css/components.css` with styles for buttons, forms, cards, inputs, progress indicators, error/success messages, loading indicators
    - Use CSS custom properties from theme.css
    - Ensure minimum 4.5:1 color contrast ratio for text
    - _Requirements: 9.2, 10.6_

  - [x] 1.5 Set up Vitest and fast-check testing configuration
    - Create `webapp/package.json` with vitest and fast-check as dev dependencies
    - Create `webapp/vitest.config.js` with jsdom environment
    - Verify test runner works with a trivial test
    - _Requirements: (testing infrastructure)_

- [x] 2. Implement hash-based router
  - [x] 2.1 Implement Router class in `webapp/js/router.js`
    - Implement `Router` class with constructor accepting routes map and outlet element
    - Implement `start()` method to listen to `hashchange` events and render initial route
    - Implement `navigate(path)` method for programmatic navigation
    - Handle unknown routes by defaulting to upload view
    - _Requirements: 1.3_

  - [x] 2.2 Write property test for router (Property 1)
    - **Property 1: Client-side routing renders correct view**
    - For any registered route hash, navigating to that hash renders the corresponding view function's output into the outlet element
    - **Validates: Requirements 1.3**

  - [x] 2.3 Write unit tests for router
    - Test route registration and initial render
    - Test hashchange event triggers correct view
    - Test programmatic navigation
    - Test unknown route fallback behavior
    - _Requirements: 1.3_

- [x] 3. Implement authentication module
  - [x] 3.1 Implement auth module in `webapp/js/auth.js`
    - Implement PKCE flow: generate code_verifier and code_challenge
    - Implement `login()` to redirect to Cognito hosted UI with PKCE parameters
    - Implement `handleCallback(code)` to exchange authorization code for tokens
    - Implement `getAccessToken()` to return valid token, refreshing if expired
    - Implement `logout()` to clear tokens and redirect to Cognito logout endpoint
    - Implement `isAuthenticated()` to check token validity
    - Store tokens in module-scoped variables (memory only, never localStorage)
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

  - [x] 3.2 Write unit tests for auth module
    - Test login redirect URL construction with PKCE
    - Test token exchange flow
    - Test token refresh on expiry
    - Test logout clears memory state
    - Test isAuthenticated checks expiry time
    - _Requirements: 2.1, 2.2, 2.4, 2.5_

- [x] 4. Checkpoint - Ensure core infrastructure tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Implement API client
  - [x] 5.1 Implement API client in `webapp/js/api.js`
    - Implement `uploadSubmission(file, metadata, onProgress)` using fetch with progress tracking
    - Implement `getSubmissions()` to retrieve submission list
    - Implement `getReportUrl(submissionId)` to get report URL
    - Attach `Authorization: Bearer <token>` header to all requests via auth module
    - Set `Content-Type: application/json` for requests with JSON bodies
    - Implement error handling: map 4xx/5xx to user-friendly messages, handle network failures separately
    - Implement 401 retry logic: refresh token and retry once before redirect to login
    - _Requirements: 2.6, 2.7, 8.1, 8.2, 8.3, 8.4_

  - [x] 5.2 Write property test for Authorization header (Property 2)
    - **Property 2: Authenticated API requests include Authorization header**
    - For any API request while a session is active, the request includes `Authorization: Bearer <token>` header
    - **Validates: Requirements 2.6**

  - [x] 5.3 Write property test for JSON content-type (Property 10)
    - **Property 10: API requests with body include JSON content-type**
    - For any API request with a body, the request includes `Content-Type: application/json` header
    - **Validates: Requirements 8.2**

  - [x] 5.4 Write property test for error handling (Property 11)
    - **Property 11: Error responses produce user-friendly messages**
    - For any HTTP error response (4xx or 5xx), the error handler produces a user-friendly message without raw technical details
    - **Validates: Requirements 8.3**

  - [x] 5.5 Write unit tests for API client
    - Test upload progress callback invocation
    - Test 401 retry then redirect flow
    - Test network failure error message
    - _Requirements: 2.7, 8.3, 8.4_

- [x] 6. Implement validation utilities
  - [x] 6.1 Implement validation functions in `webapp/js/utils/validation.js`
    - Implement `validateFile(file)` checking MIME type against accepted list and size ≤ 500 MB
    - Implement `validateTitle(title)` checking non-empty, non-whitespace, ≤ 200 characters
    - Implement `validateDescription(description)` checking ≤ 2000 characters (empty allowed)
    - Define VALIDATION constants (MAX_FILE_SIZE_BYTES, MAX_TITLE_LENGTH, MAX_DESCRIPTION_LENGTH, accepted MIME types)
    - _Requirements: 3.3, 3.4, 4.1, 4.2, 4.3_

  - [x] 6.2 Write property test for file validation (Property 3)
    - **Property 3: File validation correctness**
    - For any file, validateFile returns valid:true iff MIME type is accepted AND size ≤ 500 MB
    - **Validates: Requirements 3.3, 3.4**

  - [x] 6.3 Write property test for title validation (Property 5)
    - **Property 5: Title validation**
    - For any non-empty string 1–200 chars, validateTitle returns valid:true; for empty/whitespace-only or >200 chars, returns valid:false
    - **Validates: Requirements 4.1, 4.3**

  - [x] 6.4 Write property test for description validation (Property 6)
    - **Property 6: Description validation**
    - For any string 0–2000 chars, validateDescription returns valid:true; for >2000 chars, returns valid:false
    - **Validates: Requirements 4.2**

- [x] 7. Implement DOM utilities
  - [x] 7.1 Implement DOM helper utilities in `webapp/js/utils/dom.js`
    - Implement helper functions for creating elements, setting attributes, appending children
    - Implement a file size formatter (bytes to human-readable KB/MB/GB)
    - Implement toast/notification display utility for global error messages
    - _Requirements: 3.2, 8.3_

- [x] 8. Checkpoint - Ensure all utility and module tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Implement Upload Page view
  - [x] 9.1 Implement Upload Page view in `webapp/js/views/upload.js`
    - Render file input control with accept attribute for audio/video MIME types
    - Display selected file name and size on selection
    - Show validation errors inline for file type, file size, and title
    - Render title input (required, maxlength 200) with character count display
    - Render description textarea (optional, maxlength 2000) with character count display
    - Implement submit button: enabled only when file valid + title valid
    - On submit: call API client uploadSubmission, show progress indicator, disable submit
    - On success: display success message and navigate to List View
    - On error: display user-friendly error, re-enable submit for retry
    - Include ARIA labels on all interactive elements
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 4.1, 4.2, 4.3, 4.4, 5.1, 5.2, 5.3, 5.4, 5.5, 10.5_

  - [x] 9.2 Write property test for file selection display (Property 4)
    - **Property 4: File selection displays file information**
    - For any file with any name and size, selecting it displays file name and human-readable size
    - **Validates: Requirements 3.2**

  - [x] 9.3 Write unit tests for Upload Page
    - Test file input accepts correct MIME types
    - Test submit button disabled states
    - Test progress indicator display during upload
    - Test success navigation to list view
    - Test error display and retry capability
    - Test character count display for title and description
    - _Requirements: 3.1, 3.5, 5.2, 5.3, 5.4, 5.5, 4.4_

- [x] 10. Implement List View
  - [x] 10.1 Implement List View in `webapp/js/views/list.js`
    - On mount: call API client getSubmissions, show loading indicator
    - Render each submission with: title, file name, description, date uploaded, processing status, date completed (when present)
    - Sort submissions by dateUploaded descending (most recent first)
    - Display report link for submissions with status "Completed" (opens in new tab)
    - Do not display report link for Pending/Processing/Failed statuses
    - Display empty state with message and link to Upload Page when no submissions
    - Display error state with retry button on API failure
    - Include ARIA labels on interactive elements
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 7.1, 7.2, 7.3, 10.5_

  - [x] 10.2 Write property test for submission rendering (Property 7)
    - **Property 7: Submission rendering includes all required fields**
    - For any valid Submission object, rendered HTML contains title, file name, description, date uploaded, status, and date completed (when present)
    - **Validates: Requirements 6.2**

  - [x] 10.3 Write property test for submission sorting (Property 8)
    - **Property 8: Submissions sorted by date descending**
    - For any array of submissions, the List View renders them in descending dateUploaded order
    - **Validates: Requirements 6.3**

  - [x] 10.4 Write property test for report link visibility (Property 9)
    - **Property 9: Report link displayed iff status is Completed**
    - For any submission, report link is shown only when status is "Completed"
    - **Validates: Requirements 7.1, 7.3**

  - [x] 10.5 Write unit tests for List View
    - Test loading indicator display
    - Test empty state message and upload link
    - Test report link opens in new tab
    - Test error state with retry
    - _Requirements: 6.4, 6.5, 7.2_

- [x] 11. Integrate app entry point and wire components
  - [x] 11.1 Implement app entry point in `webapp/js/app.js`
    - Import router, auth, and view modules
    - On load: check authentication state, handle Cognito callback if authorization code present
    - If not authenticated: trigger login redirect
    - If authenticated: initialize router with routes (upload and list views), start router
    - Set up global unhandled promise rejection handler for error toast display
    - Wire logout button in navigation to auth.logout()
    - Wire hamburger menu toggle for mobile navigation
    - _Requirements: 1.3, 2.1, 2.5, 10.7_

  - [x] 11.2 Write integration tests for upload flow
    - Test full flow: file selection → metadata entry → submit → API call → success navigation
    - _Requirements: 3.1, 4.1, 5.1, 5.4_

  - [x] 11.3 Write integration tests for list view flow
    - Test full flow: API call → render submissions → report link click
    - _Requirements: 6.1, 7.1, 7.2_

- [x] 12. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The app uses no build step — ES modules served directly for MVP
- Testing uses Vitest with jsdom environment and fast-check for property generation

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.5"] },
    { "id": 1, "tasks": ["1.3", "1.4"] },
    { "id": 2, "tasks": ["2.1", "3.1", "6.1", "7.1"] },
    { "id": 3, "tasks": ["2.2", "2.3", "3.2", "6.2", "6.3", "6.4"] },
    { "id": 4, "tasks": ["5.1"] },
    { "id": 5, "tasks": ["5.2", "5.3", "5.4", "5.5"] },
    { "id": 6, "tasks": ["9.1", "10.1"] },
    { "id": 7, "tasks": ["9.2", "9.3", "10.2", "10.3", "10.4", "10.5"] },
    { "id": 8, "tasks": ["11.1"] },
    { "id": 9, "tasks": ["11.2", "11.3"] }
  ]
}
```
