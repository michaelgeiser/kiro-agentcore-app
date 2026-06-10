/**
 * Centralized HTTP client for API Gateway communication.
 * Automatically attaches Authorization header and handles errors.
 *
 * Requirements: 2.6, 2.7, 8.1, 8.2, 8.3, 8.4
 */

import { auth } from './auth.js';

// --- Configuration ---

/** Base URL for the API Gateway. Configure per environment. */
export const API_BASE_URL = 'https://api.example.com';

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
   * Upload a file with metadata.
   * Uses XMLHttpRequest for upload progress tracking (fetch doesn't support it natively).
   *
   * @param {File} file - The presentation file
   * @param {Object} metadata - { title: string, description?: string }
   * @param {Function} onProgress - Callback with upload percentage (0-100)
   * @returns {Promise<Object>} API response
   */
  async uploadSubmission(file, metadata, onProgress) {
    const token = await auth.getAccessToken();
    if (!token) {
      auth.login();
      throw new Error(ERROR_MESSAGES[401]);
    }

    const url = `${API_BASE_URL}/submissions`;

    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();

      // Track upload progress
      xhr.upload.addEventListener('progress', (event) => {
        if (event.lengthComputable && typeof onProgress === 'function') {
          const percentage = Math.round((event.loaded / event.total) * 100);
          onProgress(percentage);
        }
      });

      xhr.addEventListener('load', async () => {
        if (xhr.status === 401) {
          // Attempt token refresh and retry once
          const refreshed = await auth.refreshAccessToken();
          if (refreshed) {
            // Retry the upload with new token
            try {
              const result = await retryUpload(file, metadata, onProgress);
              resolve(result);
            } catch (err) {
              reject(err);
            }
          } else {
            auth.login();
            reject(createApiError(401));
          }
          return;
        }

        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            const data = xhr.responseText ? JSON.parse(xhr.responseText) : null;
            resolve(data);
          } catch {
            resolve(null);
          }
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

      // Build FormData with file and metadata
      const formData = new FormData();
      formData.append('file', file);
      formData.append('metadata', JSON.stringify(metadata));

      xhr.open('POST', url);
      xhr.setRequestHeader('Authorization', `Bearer ${token}`);
      // Note: Don't set Content-Type for FormData — browser sets it with boundary
      xhr.send(formData);
    });
  },

  /**
   * Retrieve list of user submissions.
   * Requirement: 8.1 (RESTful endpoints), 8.2 (JSON content type)
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
    return processResponse(response);
  },

  /**
   * Get report URL for a completed submission.
   * Requirement: 8.1 (RESTful endpoints)
   *
   * @param {string} submissionId - The submission ID
   * @returns {Promise<string>} Report URL
   */
  async getReportUrl(submissionId) {
    const url = `${API_BASE_URL}/submissions/${encodeURIComponent(submissionId)}/report`;
    const response = await authenticatedFetch(url, {
      method: 'GET',
      headers: {
        Accept: 'application/json',
      },
    });
    const data = await processResponse(response);
    return data?.url || data?.reportUrl || '';
  },
};

// --- Internal: Retry upload after token refresh ---

/**
 * Retry upload with a fresh token (called after 401 + successful refresh).
 * @param {File} file
 * @param {Object} metadata
 * @param {Function} onProgress
 * @returns {Promise<Object>}
 */
async function retryUpload(file, metadata, onProgress) {
  const token = await auth.getAccessToken();
  if (!token) {
    auth.login();
    throw new Error(ERROR_MESSAGES[401]);
  }

  const url = `${API_BASE_URL}/submissions`;

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();

    xhr.upload.addEventListener('progress', (event) => {
      if (event.lengthComputable && typeof onProgress === 'function') {
        const percentage = Math.round((event.loaded / event.total) * 100);
        onProgress(percentage);
      }
    });

    xhr.addEventListener('load', () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          const data = xhr.responseText ? JSON.parse(xhr.responseText) : null;
          resolve(data);
        } catch {
          resolve(null);
        }
      } else if (xhr.status === 401) {
        auth.login();
        reject(createApiError(401));
      } else {
        reject(createApiError(xhr.status, xhr.responseText));
      }
    });

    xhr.addEventListener('error', () => {
      reject(createNetworkError());
    });

    const formData = new FormData();
    formData.append('file', file);
    formData.append('metadata', JSON.stringify(metadata));

    xhr.open('POST', url);
    xhr.setRequestHeader('Authorization', `Bearer ${token}`);
    xhr.send(formData);
  });
}

// --- Exported helpers for testing ---

export {
  authenticatedFetch,
  processResponse,
  createApiError,
  createNetworkError,
  getAuthHeaders,
  ERROR_MESSAGES,
};
