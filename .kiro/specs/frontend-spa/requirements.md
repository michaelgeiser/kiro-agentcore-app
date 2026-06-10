# Requirements Document

## Introduction

The Frontend SPA is a single-page application for the Presentation Coaching Platform. It provides a professional, cloud-native web interface hosted on AWS that allows users to upload presentation audio or video files for analysis and track the processing status of their submissions. The SPA communicates with backend services through a RESTful API and uses AWS-native authentication. The MVP focuses on audio analysis, though the UI accepts video files to support the backend prep workflow that handles conversion.

## Glossary

- **SPA**: Single-Page Application — a web application that dynamically rewrites the current page rather than loading entire new pages from the server
- **Upload_Page**: The view within the SPA where users submit new presentation files and associated metadata for processing
- **List_View**: The view within the SPA that displays all previously submitted presentation requests and their processing status
- **Submission**: A user-created request to process a presentation file, consisting of the uploaded file and its associated metadata
- **Processing_Status**: The current state of a submission's analysis pipeline (e.g., Pending, Processing, Completed, Failed)
- **Report**: The generated coaching feedback document produced after successful analysis of a presentation file
- **API_Gateway**: The AWS API Gateway service that exposes RESTful endpoints for the SPA to communicate with backend services
- **Cognito**: AWS Cognito — the authentication service used to manage user identity and issue short-lived JWT access tokens and refresh tokens
- **JWT_Access_Token**: A short-lived JSON Web Token issued by Cognito, used to authorize API requests (typically valid for 1 hour)
- **Refresh_Token**: A longer-lived token issued by Cognito used to obtain new JWT access tokens without requiring re-authentication
- **CloudFront**: AWS CloudFront — the content delivery network used to serve the SPA static assets
- **S3_Bucket**: AWS S3 storage used for hosting the SPA static files and for storing uploaded presentation files

## Requirements

### Requirement 1: SPA Hosting and Delivery

**User Story:** As a user, I want the application to load quickly and reliably from any location, so that I can access the coaching platform without delays.

#### Acceptance Criteria

1. THE SPA SHALL be hosted as static assets in an S3_Bucket and delivered through CloudFront
2. WHEN a user navigates to the application URL, THE SPA SHALL load the complete single-page application without requiring server-side rendering
3. THE SPA SHALL support client-side routing between the Upload_Page and the List_View without full page reloads
4. THE SPA SHALL render a professional layout using semantic HTML and custom CSS styling

### Requirement 2: User Authentication

**User Story:** As a user, I want to securely log in to the platform, so that my submissions and reports are private and protected.

#### Acceptance Criteria

1. WHEN a user accesses the SPA without a valid session, THE SPA SHALL redirect the user to the Cognito hosted login page
2. WHEN Cognito returns an authentication token after successful login, THE SPA SHALL store short-lived JWT access tokens and refresh tokens issued by Cognito in browser memory (not localStorage)
3. THE SPA SHALL use Cognito-issued JWT access tokens for API authorization and SHALL NOT use long-term IAM access keys
4. WHEN a Cognito access token expires, THE SPA SHALL use the refresh token to obtain a new access token without requiring the user to re-authenticate
5. WHEN a user clicks the logout button, THE SPA SHALL invalidate the session token and redirect the user to the login page
6. WHILE a user session is active, THE SPA SHALL include the Cognito JWT access token in the Authorization header of all requests sent to the API_Gateway
7. IF an API request returns a 401 Unauthorized response, THEN THE SPA SHALL attempt a token refresh and retry the request once before redirecting the user to the Cognito login page

### Requirement 3: Upload Page — File Selection

**User Story:** As a user, I want to upload a presentation audio or video file, so that the platform can analyze my presentation delivery.

#### Acceptance Criteria

1. THE Upload_Page SHALL provide a file input control that accepts audio files (MP3, WAV, M4A, AAC) and video files (MP4, MOV, WebM)
2. WHEN a user selects a file, THE Upload_Page SHALL display the selected file name and file size
3. IF a user selects a file with an unsupported format, THEN THE Upload_Page SHALL display an error message indicating the accepted file formats
4. IF a user selects a file exceeding 500 MB, THEN THE Upload_Page SHALL display an error message indicating the maximum allowed file size
5. WHEN a user selects a valid file, THE Upload_Page SHALL enable the submit button

### Requirement 4: Upload Page — Metadata Entry

**User Story:** As a user, I want to provide context about my presentation, so that the analysis can be more relevant and the submission is identifiable later.

#### Acceptance Criteria

1. THE Upload_Page SHALL provide a text input field for the user to enter a presentation title (required, maximum 200 characters)
2. THE Upload_Page SHALL provide a text area for the user to enter a description of the presentation (optional, maximum 2000 characters)
3. IF the user attempts to submit without providing a presentation title, THEN THE Upload_Page SHALL display a validation error message on the title field
4. IF the user enters a title exceeding 200 characters, THEN THE Upload_Page SHALL prevent additional character input and display the character count

### Requirement 5: Upload Page — File Submission

**User Story:** As a user, I want to submit my file and metadata to the platform, so that processing can begin.

#### Acceptance Criteria

1. WHEN the user clicks the submit button with a valid file and valid metadata, THE Upload_Page SHALL send the file and metadata to the API_Gateway upload endpoint
2. WHILE a file upload is in progress, THE Upload_Page SHALL display a progress indicator showing upload completion percentage
3. WHILE a file upload is in progress, THE Upload_Page SHALL disable the submit button to prevent duplicate submissions
4. WHEN the API_Gateway returns a successful upload response, THE Upload_Page SHALL display a success message and navigate the user to the List_View
5. IF the API_Gateway returns an error response during upload, THEN THE Upload_Page SHALL display an error message describing the failure and allow the user to retry

### Requirement 6: List View — Submission Display

**User Story:** As a user, I want to see all my submitted presentations, so that I can track their analysis progress and access completed reports.

#### Acceptance Criteria

1. WHEN the user navigates to the List_View, THE SPA SHALL retrieve the list of Submissions from the API_Gateway
2. THE List_View SHALL display each Submission with the following fields: presentation title, uploaded file name, description, date uploaded, Processing_Status, and date of processing completion
3. THE List_View SHALL sort Submissions by date uploaded in descending order (most recent first)
4. WHILE the List_View is loading Submission data, THE SPA SHALL display a loading indicator
5. IF the API_Gateway returns an empty list of Submissions, THEN THE List_View SHALL display a message indicating no submissions exist and provide a link to the Upload_Page

### Requirement 7: List View — Report Access

**User Story:** As a user, I want to access my completed coaching report, so that I can review the feedback on my presentation.

#### Acceptance Criteria

1. WHEN a Submission has a Processing_Status of Completed, THE List_View SHALL display a link to the generated Report
2. WHEN the user clicks the Report link, THE SPA SHALL open the Report in a new browser tab
3. WHILE a Submission has a Processing_Status of Pending or Processing, THE List_View SHALL display the status label without a Report link

### Requirement 8: API Integration

**User Story:** As a developer, I want the SPA to communicate with backend services through a well-defined API, so that frontend and backend can evolve independently.

#### Acceptance Criteria

1. THE SPA SHALL communicate with backend services exclusively through RESTful endpoints exposed by the API_Gateway
2. THE SPA SHALL send all API requests with JSON content type for request bodies and accept JSON responses
3. WHEN the API_Gateway returns a 4xx or 5xx error response, THE SPA SHALL display a user-friendly error message rather than raw technical details
4. IF a network connectivity failure occurs during an API request, THEN THE SPA SHALL display a message indicating the network is unavailable and suggest the user retry

### Requirement 9: Branding and Theming

**User Story:** As a platform owner, I want all visual styling controlled through a centralized CSS theme, so that I can update branding (colors, fonts, spacing) in one place.

#### Acceptance Criteria

1. THE SPA SHALL define all brand colors, font families, font sizes, spacing values, and border radii as CSS custom properties (variables) in a single theme stylesheet
2. THE SPA SHALL apply the CSS custom properties consistently across all views so that changing a variable value updates the entire application appearance
3. THE SPA SHALL define at minimum the following brand tokens as CSS custom properties: primary color, secondary color, background color, text color, error color, success color, heading font family, body font family, and base spacing unit
4. WHEN a developer modifies a CSS custom property value in the theme stylesheet, THE SPA SHALL reflect the change across all components without requiring edits to individual component styles

### Requirement 10: Responsive and Accessible Layout

**User Story:** As a user, I want the application to look professional and work across devices, so that I can use it on my phone, tablet, or desktop.

#### Acceptance Criteria

1. THE SPA SHALL render correctly on viewport widths from 320 pixels to 1920 pixels using a responsive layout that adapts to mobile, tablet, and desktop screen sizes
2. THE SPA SHALL use a mobile-first responsive design approach with CSS breakpoints for small (320px–767px), medium (768px–1023px), and large (1024px–1920px) viewports
3. THE SPA SHALL use semantic HTML elements (header, nav, main, section, footer) for document structure
4. THE SPA SHALL provide visible focus indicators for all interactive elements when navigated via keyboard
5. THE SPA SHALL include appropriate ARIA labels on interactive elements that lack visible text labels
6. THE SPA SHALL maintain a minimum color contrast ratio of 4.5:1 for all text content against its background
7. WHILE the viewport width is below 768 pixels, THE SPA SHALL collapse navigation into a hamburger menu or equivalent compact navigation pattern
