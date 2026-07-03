/**
 * Admin API client for administration panel endpoints.
 * Follows the same patterns as api.js for fetch, error handling, and token management.
 *
 * Requirements: 8.1, 8.2, 8.3, 8.4
 */

import { authenticatedFetch, processResponse, API_BASE_URL } from './api.js';

// --- Admin API Client ---

export const adminApi = {
  /**
   * Retrieve all configurable environment variables with current values.
   * Requirement: 8.1 (GET /admin/environment-variables)
   *
   * @returns {Promise<Array<{name: string, value: string, description: string, inputType: string}>>}
   */
  async getEnvironmentVariables() {
    const url = `${API_BASE_URL}/admin/environment-variables`;
    const response = await authenticatedFetch(url, {
      method: 'GET',
      headers: {
        Accept: 'application/json',
      },
    });
    const data = await processResponse(response);
    return data.variables;
  },

  /**
   * Update changed environment variables, persist to SSM, and trigger ECS redeployment.
   * Requirement: 8.2 (PUT /admin/environment-variables)
   *
   * @param {Object<string, string>} changedVars - Map of variable names to new values
   * @returns {Promise<{updatedVars: string[], deploymentStatus: string, message: string}>}
   */
  async updateEnvironmentVariables(changedVars) {
    const url = `${API_BASE_URL}/admin/environment-variables`;
    const response = await authenticatedFetch(url, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
      },
      body: JSON.stringify({ variables: changedVars }),
    });
    return processResponse(response);
  },

  /**
   * Retrieve all feature flags with current boolean state.
   * Requirement: 8.3 (GET /admin/feature-flags)
   *
   * @returns {Promise<Array<{name: string, enabled: boolean, description: string}>>}
   */
  async getFeatureFlags() {
    const url = `${API_BASE_URL}/admin/feature-flags`;
    const response = await authenticatedFetch(url, {
      method: 'GET',
      headers: {
        Accept: 'application/json',
      },
    });
    const data = await processResponse(response);
    return data.flags;
  },

  /**
   * Update a single feature flag's enabled state.
   * Requirement: 8.4 (PUT /admin/feature-flags/{flag-name})
   *
   * @param {string} flagName - The feature flag name (e.g., "video-processing-enabled")
   * @param {boolean} enabled - The new enabled state
   * @returns {Promise<{name: string, enabled: boolean}>}
   */
  async updateFeatureFlag(flagName, enabled) {
    const url = `${API_BASE_URL}/admin/feature-flags/${encodeURIComponent(flagName)}`;
    const response = await authenticatedFetch(url, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
      },
      body: JSON.stringify({ enabled }),
    });
    return processResponse(response);
  },
};
