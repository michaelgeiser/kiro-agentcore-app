/**
 * Centralized HTTP client for API Gateway communication.
 * Automatically attaches Authorization header and handles errors.
 *
 * Requirements: 2.6, 2.7, 8.1, 8.2, 8.3, 8.4, 10.2, 10.3, 10.6
 */

import { auth } from './auth.js';
import { CONFIG } from './config.js';

// --- Configuration ---

/** Base URL for the API Gateway. Sourced from deployment config. */
export const API_BASE_URL = CONFIG.apiBaseUrl;

// --- Error Messages (user-friendly, no raw technical details) ---

const ERROR_MESSAGES = {
  400: 'The request was invalid. Please check your input and try again.',
  401: 'Your session has expired. Please log in again.',
  403: 'You do not have permission to perform this action.',
  404: 'The requested resource was not found.',
  409: 'A conflict occurred. Please refresh and try again.',
  413: 'The file is too large to upload.',
  422: 'The provided data is invalid. Please check your input.',
  429: 'Too many requests. Please wait a moment and try again.',
  500: 'An unexpected server error occurred. Please try again later.',
  502: 'The service is temporarily unavailable. Please try again later.',
  503: 'The service is temporarily unavailable. Please try again later.',
  504: 'The request timed out. Please try again later.',
  network: 'Network unavailable. Please check your connection and try again.',
  unknown: 'An unexpected error occurred. Please try again.',
};

// --- Error Handling ---

/**
 * Map an HTTP error status to a user-friendly message.
 * Exported for independent testing by property tests.
 *
 * @param {number} status - HTTP status code (4xx or 5xx)
 * @param {string} [responseBody] - Raw response body (ignored for user-facing message)
 * @returns {string} User-friendly error message
 */
export function mapErrorToMessage(status, responseBody) {
  if (ERROR_MESSAGES[status]) {
    return ERROR_MESSAGES[status];
  }
  if (status >= 400 && status < 500) {
    return 'The request could not be completed. Please try again.';
  }
  if (status >= 500) {
    return 'An unexpected server error occurred. Please try again later.';
  }
  return ERROR_MESSAGES.unknown;
}

/**
 * Create an ApiError with a user-friendly message.
 * @param {number} status - HTTP status code
 * @param {string} [responseBody] - Raw response body
 * @returns {Error} Error with user-friendly message
 */
function createApiError(status, responseBody) {
  const message = mapErrorToMessage(status, responseBody);
  const error = new Error(message);
  error.status = status;
  error.isApiError = true;
  return error;
}

/**
 * Create a network error with a user-friendly message.
 * @returns {Error} Error indicating network unavailability
 */
function createNetworkError() {
  const error = new Error(ERROR_MESSAGES.network);
  error.isNetworkError = true;
  return error;
}

// --- Internal Helpers ---

/**
 * Get authorization headers with the current access token.
 * @returns {Promise<Object>} Headers object with Authorization bearer token
 */
async function getAuthHeaders() {
  const token = await auth.getAccessToken();
  if (!token) {
    // No token available — redirect to login
    auth.login();
    throw new Error(ERROR_MESSAGES[401]);
  }
  return { Authorization: `Bearer ${token}` };
}

/**
 * Perform an authenticated fetch request with 401 retry logic.
 * Requirement: 2.6 (Authorization header), 2.7 (401 retry)
 *
 * @param {string} url - Full request URL
 * @param {Object} options - Fetch options (method, headers, body)
 * @returns {Promise<Response>} The fetch response
 */
async function authenticatedFetch(url, options = {}) {
  const authHeaders = await getAuthHeaders();

  const headers = {
    ...authHeaders,
    ...options.headers,
  };

  let response;
  try {
    response = await fetch(url, { ...options, headers });
  } catch (err) {
    throw createNetworkError();
  }

  // 401 retry logic: refresh token and retry once before redirect
  if (response.status === 401) {
    const refreshed = await auth.refreshAccessToken();
    if (refreshed) {
      // Retry with new token
      const newAuthHeaders = await getAuthHeaders();
      const retryHeaders = {
        ...newAuthHeaders,
        ...options.headers,
      };

      try {
        response = await fetch(url, { ...options, headers: retryHeaders });
      } catch (err) {
        throw createNetworkError();
      }

      // If still 401 after retry, redirect to login
      if (response.status === 401) {
        auth.login();
        throw createApiError(401);
      }
    } else {
      // Refresh failed — redirect to login
      auth.login();
      throw createApiError(401);
    }
  }

  return response;
}

/**
 * Process the response and throw user-friendly errors for 4xx/5xx.
 * @param {Response} response - Fetch response
 * @returns {Promise<Object>} Parsed JSON response body
 */
async function processResponse(response) {
  if (response.ok) {
    // Handle empty responses (204 No Content)
    const text = await response.text();
    if (!text) return null;
    return JSON.parse(text);
  }

  // Error response — read body for logging but don't expose to user
  const responseBody = await response.text().catch(() => '');
  throw createApiError(response.status, responseBody);
}

// --- API Client ---

export const api = {
  /**
   * Upload a file with metadata using the two-step presigned URL flow.
   * Requirement: 10.2 (POST metadata, receive presigned URL), 10.3 (PUT file to S3)
   *
   * Step 1: POST JSON metadata to /submissions to get a presigned S3 URL
   * Step 2: PUT file directly to S3 using the presigned URL (with progress tracking)
   *
   * @param {File} file - The presentation file
   * @param {Object} metadata - { title: string, description?: string }
   * @param {Function} onProgress - Callback with upload percentage (0-100)
   * @returns {Promise<Object>} API response containing { submissionId, presignedUrl, status }
   */
  async uploadSubmission(file, metadata, onProgress) {
    // Step 1: POST metadata to /submissions to get presigned URL
    const url = `${API_BASE_URL}/submissions`;
    const body = {
      title: metadata.title,
      description: metadata.description || '',
      fileName: file.name,
      contentType: file.type,
      fileSizeBytes: file.size,
    };

    const response = await authenticatedFetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
      },
      body: JSON.stringify(body),
    });

    const data = await processResponse(response);

    // Step 2: PUT file to presigned URL using XMLHttpRequest for progress tracking
    const { presignedUrl } = data;

    await new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();

      // Track upload progress
      xhr.upload.addEventListener('progress', (event) => {
        if (event.lengthComputable && typeof onProgress === 'function') {
          const percentage = Math.round((event.loaded / event.total) * 100);
          onProgress(percentage);
        }
      });

      xhr.addEventListener('load', () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve();
        } else {
          reject(createApiError(xhr.status, xhr.responseText));
        }
      });

      xhr.addEventListener('error', () => {
        reject(createNetworkError());
      });

      xhr.addEventListener('abort', () => {
        reject(new Error('Upload was cancelled.'));
      });

      xhr.open('PUT', presignedUrl);
      xhr.setRequestHeader('Content-Type', file.type);
      xhr.send(file);
    });

    // Return the metadata response from step 1
    return data;
  },

  /**
   * Retrieve list of user submissions.
   * Requirement: 8.1 (RESTful endpoints), 8.2 (JSON content type), 10.6 (reportUrl in list)
   *
   * @returns {Promise<Array>} Array of submission objects
   */
  async getSubmissions() {
    const url = `${API_BASE_URL}/submissions`;
    const response = await authenticatedFetch(url, {
      method: 'GET',
      headers: {
        Accept: 'application/json',
      },
    });
    const data = await processResponse(response);
    return data.submissions;
  },
};

// --- Exported helpers for testing ---

export {
  authenticatedFetch,
  processResponse,
  createApiError,
  createNetworkError,
  getAuthHeaders,
  ERROR_MESSAGES,
};
