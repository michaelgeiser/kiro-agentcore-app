/**
 * Unit tests for the API client module.
 * Tests error handling, auth header attachment, and core API methods.
 *
 * Requirements: 2.6, 2.7, 8.1, 8.2, 8.3, 8.4
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// Mock the auth module before importing api
vi.mock('../../js/auth.js', () => ({
  auth: {
    getAccessToken: vi.fn(),
    refreshAccessToken: vi.fn(),
    login: vi.fn(),
    _setTokens: vi.fn(),
    _clearState: vi.fn(),
  },
}));

import { mapErrorToMessage, ERROR_MESSAGES, API_BASE_URL, api, authenticatedFetch } from '../../js/api.js';
import { auth } from '../../js/auth.js';

describe('API Client', () => {
  describe('mapErrorToMessage', () => {
    it('returns user-friendly message for known 4xx status codes', () => {
      expect(mapErrorToMessage(400)).toBe(ERROR_MESSAGES[400]);
      expect(mapErrorToMessage(401)).toBe(ERROR_MESSAGES[401]);
      expect(mapErrorToMessage(403)).toBe(ERROR_MESSAGES[403]);
      expect(mapErrorToMessage(404)).toBe(ERROR_MESSAGES[404]);
      expect(mapErrorToMessage(409)).toBe(ERROR_MESSAGES[409]);
      expect(mapErrorToMessage(413)).toBe(ERROR_MESSAGES[413]);
      expect(mapErrorToMessage(422)).toBe(ERROR_MESSAGES[422]);
      expect(mapErrorToMessage(429)).toBe(ERROR_MESSAGES[429]);
    });

    it('returns user-friendly message for known 5xx status codes', () => {
      expect(mapErrorToMessage(500)).toBe(ERROR_MESSAGES[500]);
      expect(mapErrorToMessage(502)).toBe(ERROR_MESSAGES[502]);
      expect(mapErrorToMessage(503)).toBe(ERROR_MESSAGES[503]);
      expect(mapErrorToMessage(504)).toBe(ERROR_MESSAGES[504]);
    });

    it('returns generic client error message for unknown 4xx codes', () => {
      expect(mapErrorToMessage(418)).toBe('The request could not be completed. Please try again.');
      expect(mapErrorToMessage(451)).toBe('The request could not be completed. Please try again.');
    });

    it('returns generic server error message for unknown 5xx codes', () => {
      expect(mapErrorToMessage(501)).toBe('An unexpected server error occurred. Please try again later.');
      expect(mapErrorToMessage(599)).toBe('An unexpected server error occurred. Please try again later.');
    });

    it('returns unknown error for non-4xx/5xx status codes', () => {
      expect(mapErrorToMessage(200)).toBe(ERROR_MESSAGES.unknown);
      expect(mapErrorToMessage(301)).toBe(ERROR_MESSAGES.unknown);
    });

    it('does not expose raw response body in error messages', () => {
      const rawBody = '{"error":"NullPointerException at com.server.Handler:42"}';
      const msg = mapErrorToMessage(500, rawBody);
      expect(msg).not.toContain('NullPointerException');
      expect(msg).not.toContain('com.server');
      expect(msg).not.toContain('Handler');
      expect(msg).not.toContain(rawBody);
    });

    it('does not expose stack traces in error messages', () => {
      const rawBody = 'Error: ENOENT\n    at Object.fs.readFileSync\n    at Module._compile';
      const msg = mapErrorToMessage(500, rawBody);
      expect(msg).not.toContain('ENOENT');
      expect(msg).not.toContain('readFileSync');
      expect(msg).not.toContain('Module._compile');
    });
  });

  describe('ERROR_MESSAGES', () => {
    it('has a network error message', () => {
      expect(ERROR_MESSAGES.network).toBe(
        'Network unavailable. Please check your connection and try again.'
      );
    });

    it('all messages are user-friendly strings', () => {
      for (const [key, message] of Object.entries(ERROR_MESSAGES)) {
        expect(typeof message).toBe('string');
        expect(message.length).toBeGreaterThan(0);
        // Should not contain common technical terms
        expect(message).not.toMatch(/exception/i);
        expect(message).not.toMatch(/stack\s*trace/i);
        expect(message).not.toMatch(/null\s*pointer/i);
      }
    });
  });

  describe('API_BASE_URL', () => {
    it('is a non-empty string', () => {
      expect(typeof API_BASE_URL).toBe('string');
      expect(API_BASE_URL.length).toBeGreaterThan(0);
    });

    it('starts with https://', () => {
      expect(API_BASE_URL.startsWith('https://')).toBe(true);
    });
  });

  describe('uploadSubmission — progress callback (Requirement 2.7)', () => {
    beforeEach(() => {
      // auth.getAccessToken returns a valid token
      auth.getAccessToken.mockResolvedValue('test-access-token');
    });

    afterEach(() => {
      vi.restoreAllMocks();
    });

    it('invokes onProgress with percentage values during upload', async () => {
      const file = new File(['test content'], 'presentation.mp4', { type: 'video/mp4' });
      const metadata = { title: 'My Presentation' };
      const onProgress = vi.fn();

      // Mock send to simulate progress events and a successful load
      vi.spyOn(XMLHttpRequest.prototype, 'send').mockImplementation(function () {
        const xhr = this;

        // Simulate progress events on upload
        const progressEvents = [
          { lengthComputable: true, loaded: 25, total: 100 },
          { lengthComputable: true, loaded: 50, total: 100 },
          { lengthComputable: true, loaded: 75, total: 100 },
          { lengthComputable: true, loaded: 100, total: 100 },
        ];
        for (const evt of progressEvents) {
          const progressEvent = new ProgressEvent('progress', evt);
          xhr.upload.dispatchEvent(progressEvent);
        }

        // Simulate successful response
        Object.defineProperty(xhr, 'status', { value: 200, writable: true, configurable: true });
        Object.defineProperty(xhr, 'responseText', { value: '{"id":"sub-123"}', writable: true, configurable: true });
        xhr.dispatchEvent(new Event('load'));
      });

      await api.uploadSubmission(file, metadata, onProgress);

      // Verify progress was called with correct percentages
      expect(onProgress).toHaveBeenCalledTimes(4);
      expect(onProgress).toHaveBeenNthCalledWith(1, 25);
      expect(onProgress).toHaveBeenNthCalledWith(2, 50);
      expect(onProgress).toHaveBeenNthCalledWith(3, 75);
      expect(onProgress).toHaveBeenNthCalledWith(4, 100);
    });

    it('does not invoke onProgress when event is not lengthComputable', async () => {
      const file = new File(['test content'], 'audio.mp3', { type: 'audio/mpeg' });
      const metadata = { title: 'Audio Presentation' };
      const onProgress = vi.fn();

      vi.spyOn(XMLHttpRequest.prototype, 'send').mockImplementation(function () {
        const xhr = this;

        // Simulate non-computable progress event
        const progressEvent = new ProgressEvent('progress', { lengthComputable: false, loaded: 0, total: 0 });
        xhr.upload.dispatchEvent(progressEvent);

        // Simulate successful response
        Object.defineProperty(xhr, 'status', { value: 200, writable: true, configurable: true });
        Object.defineProperty(xhr, 'responseText', { value: '{"id":"sub-123"}', writable: true, configurable: true });
        xhr.dispatchEvent(new Event('load'));
      });

      await api.uploadSubmission(file, metadata, onProgress);

      expect(onProgress).not.toHaveBeenCalled();
    });
  });

  describe('authenticatedFetch — 401 retry then redirect (Requirement 2.7)', () => {
    let originalFetch;

    beforeEach(() => {
      originalFetch = global.fetch;
      auth.getAccessToken.mockResolvedValue('initial-token');
      auth.login.mockImplementation(() => {});
    });

    afterEach(() => {
      global.fetch = originalFetch;
      vi.restoreAllMocks();
    });

    it('retries with refreshed token on 401, succeeds on retry', async () => {
      let callCount = 0;
      global.fetch = vi.fn(async () => {
        callCount++;
        if (callCount === 1) {
          return { status: 401, ok: false, text: async () => '' };
        }
        return { status: 200, ok: true, text: async () => '{"data":"success"}' };
      });

      // refreshAccessToken succeeds
      auth.refreshAccessToken.mockResolvedValue(true);
      // After refresh, getAccessToken returns new token
      auth.getAccessToken
        .mockResolvedValueOnce('initial-token')
        .mockResolvedValueOnce('refreshed-token');

      const response = await authenticatedFetch(`${API_BASE_URL}/submissions`);

      expect(response.status).toBe(200);
      expect(auth.refreshAccessToken).toHaveBeenCalledTimes(1);
      expect(global.fetch).toHaveBeenCalledTimes(2);
      // Verify login was NOT called (retry succeeded)
      expect(auth.login).not.toHaveBeenCalled();
    });

    it('redirects to login when 401 persists after retry', async () => {
      global.fetch = vi.fn(async () => ({
        status: 401,
        ok: false,
        text: async () => '',
      }));

      // refreshAccessToken succeeds but API still returns 401
      auth.refreshAccessToken.mockResolvedValue(true);
      auth.getAccessToken.mockResolvedValue('any-token');

      await expect(
        authenticatedFetch(`${API_BASE_URL}/submissions`)
      ).rejects.toThrow();

      // Should have called login (redirect to login page)
      expect(auth.login).toHaveBeenCalled();
      // Fetch called twice: original + retry
      expect(global.fetch).toHaveBeenCalledTimes(2);
    });

    it('redirects to login when token refresh fails', async () => {
      global.fetch = vi.fn(async () => ({
        status: 401,
        ok: false,
        text: async () => '',
      }));

      // refreshAccessToken fails
      auth.refreshAccessToken.mockResolvedValue(false);
      auth.getAccessToken.mockResolvedValue('initial-token');

      await expect(
        authenticatedFetch(`${API_BASE_URL}/submissions`)
      ).rejects.toThrow();

      // Should redirect to login
      expect(auth.login).toHaveBeenCalled();
      // Fetch called only once (no retry since refresh failed)
      expect(global.fetch).toHaveBeenCalledTimes(1);
    });
  });

  describe('authenticatedFetch — network failure error message (Requirement 8.4)', () => {
    let originalFetch;

    beforeEach(() => {
      originalFetch = global.fetch;
      auth.getAccessToken.mockResolvedValue('valid-token');
    });

    afterEach(() => {
      global.fetch = originalFetch;
      vi.restoreAllMocks();
    });

    it('throws network error with user-friendly message when fetch throws', async () => {
      global.fetch = vi.fn(async () => {
        throw new TypeError('Failed to fetch');
      });

      let error;
      try {
        await authenticatedFetch(`${API_BASE_URL}/submissions`);
      } catch (e) {
        error = e;
      }

      expect(error).toBeDefined();
      expect(error.message).toBe(ERROR_MESSAGES.network);
      expect(error.message).toBe('Network unavailable. Please check your connection and try again.');
      expect(error.isNetworkError).toBe(true);
    });

    it('does not expose raw error details in network failure message', async () => {
      global.fetch = vi.fn(async () => {
        throw new Error('net::ERR_INTERNET_DISCONNECTED at chrome-internal://network-error');
      });

      let error;
      try {
        await authenticatedFetch(`${API_BASE_URL}/submissions`);
      } catch (e) {
        error = e;
      }

      expect(error).toBeDefined();
      expect(error.message).not.toContain('ERR_INTERNET_DISCONNECTED');
      expect(error.message).not.toContain('chrome-internal');
      expect(error.message).toBe(ERROR_MESSAGES.network);
    });
  });
});
