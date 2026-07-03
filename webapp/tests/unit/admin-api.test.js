/**
 * Unit tests for the admin API client module.
 * Tests fetch calls, auth header attachment, and response handling for admin endpoints.
 *
 * Requirements: 8.1, 8.2, 8.3, 8.4
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// Mock the auth module before importing admin-api
vi.mock('../../js/auth.js', () => ({
  auth: {
    getAccessToken: vi.fn(),
    refreshAccessToken: vi.fn(),
    login: vi.fn(),
  },
}));

import { adminApi } from '../../js/admin-api.js';
import { API_BASE_URL, ERROR_MESSAGES } from '../../js/api.js';
import { auth } from '../../js/auth.js';

describe('Admin API Client', () => {
  let originalFetch;

  beforeEach(() => {
    originalFetch = global.fetch;
    auth.getAccessToken.mockResolvedValue('test-admin-token');
  });

  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  describe('getEnvironmentVariables', () => {
    it('calls GET /admin/environment-variables with auth header', async () => {
      const mockVariables = [
        { name: 'SESSION_SUPERVISOR_MODEL_ID', value: 'us.anthropic.claude-sonnet-4-6', description: 'Foundation model used by the Session Supervisor agent', inputType: 'model-dropdown' },
        { name: 'IDLE_TIMEOUT_MINUTES', value: '30', description: 'Minutes of inactivity before the ECS evaluation task exits', inputType: 'text' },
      ];

      global.fetch = vi.fn(async () => ({
        status: 200,
        ok: true,
        text: async () => JSON.stringify({ variables: mockVariables }),
      }));

      const result = await adminApi.getEnvironmentVariables();

      expect(result).toEqual(mockVariables);
      expect(global.fetch).toHaveBeenCalledTimes(1);
      const [fetchUrl, fetchOptions] = global.fetch.mock.calls[0];
      expect(fetchUrl).toBe(`${API_BASE_URL}/admin/environment-variables`);
      expect(fetchOptions.method).toBe('GET');
      expect(fetchOptions.headers.Authorization).toBe('Bearer test-admin-token');
      expect(fetchOptions.headers.Accept).toBe('application/json');
    });

    it('throws error on 403 non-admin response', async () => {
      global.fetch = vi.fn(async () => ({
        status: 403,
        ok: false,
        text: async () => JSON.stringify({ message: 'Forbidden' }),
      }));

      await expect(adminApi.getEnvironmentVariables()).rejects.toThrow(ERROR_MESSAGES[403]);
    });

    it('throws network error when fetch fails', async () => {
      global.fetch = vi.fn(async () => {
        throw new TypeError('Failed to fetch');
      });

      await expect(adminApi.getEnvironmentVariables()).rejects.toThrow(ERROR_MESSAGES.network);
    });
  });

  describe('updateEnvironmentVariables', () => {
    it('calls PUT /admin/environment-variables with changed vars payload', async () => {
      const changedVars = {
        SESSION_SUPERVISOR_MODEL_ID: 'us.amazon.nova-pro-v1:0',
        IDLE_TIMEOUT_MINUTES: '45',
      };

      const mockResponse = {
        updatedVars: ['SESSION_SUPERVISOR_MODEL_ID', 'IDLE_TIMEOUT_MINUTES'],
        deploymentStatus: 'triggered',
        message: 'Configuration saved. ECS service redeployment triggered.',
      };

      global.fetch = vi.fn(async () => ({
        status: 200,
        ok: true,
        text: async () => JSON.stringify(mockResponse),
      }));

      const result = await adminApi.updateEnvironmentVariables(changedVars);

      expect(result).toEqual(mockResponse);
      expect(global.fetch).toHaveBeenCalledTimes(1);
      const [fetchUrl, fetchOptions] = global.fetch.mock.calls[0];
      expect(fetchUrl).toBe(`${API_BASE_URL}/admin/environment-variables`);
      expect(fetchOptions.method).toBe('PUT');
      expect(fetchOptions.headers.Authorization).toBe('Bearer test-admin-token');
      expect(fetchOptions.headers['Content-Type']).toBe('application/json');
      expect(JSON.parse(fetchOptions.body)).toEqual({ variables: changedVars });
    });

    it('throws error on 400 invalid variable name', async () => {
      global.fetch = vi.fn(async () => ({
        status: 400,
        ok: false,
        text: async () => JSON.stringify({ message: 'Invalid variable name' }),
      }));

      await expect(
        adminApi.updateEnvironmentVariables({ UNKNOWN_VAR: 'value' })
      ).rejects.toThrow(ERROR_MESSAGES[400]);
    });
  });

  describe('getFeatureFlags', () => {
    it('calls GET /admin/feature-flags with auth header', async () => {
      const mockFlags = [
        { name: 'video-processing-enabled', enabled: true, description: 'Allow video file uploads' },
        { name: 'embeddings-enabled', enabled: false, description: 'Create vector embeddings' },
      ];

      global.fetch = vi.fn(async () => ({
        status: 200,
        ok: true,
        text: async () => JSON.stringify({ flags: mockFlags }),
      }));

      const result = await adminApi.getFeatureFlags();

      expect(result).toEqual(mockFlags);
      expect(global.fetch).toHaveBeenCalledTimes(1);
      const [fetchUrl, fetchOptions] = global.fetch.mock.calls[0];
      expect(fetchUrl).toBe(`${API_BASE_URL}/admin/feature-flags`);
      expect(fetchOptions.method).toBe('GET');
      expect(fetchOptions.headers.Authorization).toBe('Bearer test-admin-token');
      expect(fetchOptions.headers.Accept).toBe('application/json');
    });
  });

  describe('updateFeatureFlag', () => {
    it('calls PUT /admin/feature-flags/{flagName} with enabled payload', async () => {
      const mockResponse = { name: 'embeddings-enabled', enabled: false };

      global.fetch = vi.fn(async () => ({
        status: 200,
        ok: true,
        text: async () => JSON.stringify(mockResponse),
      }));

      const result = await adminApi.updateFeatureFlag('embeddings-enabled', false);

      expect(result).toEqual(mockResponse);
      expect(global.fetch).toHaveBeenCalledTimes(1);
      const [fetchUrl, fetchOptions] = global.fetch.mock.calls[0];
      expect(fetchUrl).toBe(`${API_BASE_URL}/admin/feature-flags/embeddings-enabled`);
      expect(fetchOptions.method).toBe('PUT');
      expect(fetchOptions.headers.Authorization).toBe('Bearer test-admin-token');
      expect(fetchOptions.headers['Content-Type']).toBe('application/json');
      expect(JSON.parse(fetchOptions.body)).toEqual({ enabled: false });
    });

    it('encodes flag name in URL', async () => {
      global.fetch = vi.fn(async () => ({
        status: 200,
        ok: true,
        text: async () => JSON.stringify({ name: 'flag-with-special', enabled: true }),
      }));

      await adminApi.updateFeatureFlag('flag-with-special', true);

      const [fetchUrl] = global.fetch.mock.calls[0];
      expect(fetchUrl).toBe(`${API_BASE_URL}/admin/feature-flags/flag-with-special`);
    });

    it('throws error on 404 invalid flag name', async () => {
      global.fetch = vi.fn(async () => ({
        status: 404,
        ok: false,
        text: async () => JSON.stringify({ message: 'Flag not found' }),
      }));

      await expect(
        adminApi.updateFeatureFlag('nonexistent-flag', true)
      ).rejects.toThrow(ERROR_MESSAGES[404]);
    });
  });
});
