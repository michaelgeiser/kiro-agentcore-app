// Feature: frontend-spa, Property 2: Authenticated API requests include Authorization header

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import * as fc from 'fast-check';
import { mapErrorToMessage, ERROR_MESSAGES } from '../../js/api.js';

/**
 * Property 2: Authenticated API requests include Authorization header
 *
 * For any API request made through the API client while a user session is active,
 * the request includes an `Authorization: Bearer <token>` header containing the
 * current valid access token.
 *
 * Validates: Requirements 2.6
 */
describe('Property 2: Authenticated API requests include Authorization header', () => {
  let mockFetch;
  let auth;
  let authenticatedFetch;
  let getAuthHeaders;

  beforeEach(async () => {
    // Set up fetch mock before importing the modules that use it
    mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: () => Promise.resolve('{}'),
      json: () => Promise.resolve({}),
    });
    vi.stubGlobal('fetch', mockFetch);

    // Dynamically import modules after mocking fetch
    const authModule = await import('../../js/auth.js');
    const apiModule = await import('../../js/api.js');

    auth = authModule.auth;
    authenticatedFetch = apiModule.authenticatedFetch;
    getAuthHeaders = apiModule.getAuthHeaders;
  });

  afterEach(() => {
    auth._clearState();
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  /**
   * Arbitrary that generates a valid non-empty token string.
   * Tokens are alphanumeric strings simulating JWT-like values.
   */
  const tokenArb = fc.string({ minLength: 10, maxLength: 100 }).filter(
    (s) => s.trim().length > 0 && /^[A-Za-z0-9._\-]+$/.test(s)
  );

  /**
   * Arbitrary that generates a valid URL.
   */
  const urlPathArb = fc.string({ minLength: 1, maxLength: 30 }).filter(
    (s) => /^[a-z][a-z0-9/\-]*$/.test(s)
  ).map((path) => `https://api.example.com/${path}`);

  it('any call to authenticatedFetch includes Authorization: Bearer <token> header', async () => {
    await fc.assert(
      fc.asyncProperty(tokenArb, urlPathArb, async (token, url) => {
        // Set up an active session with the generated token
        auth._setTokens({
          access_token: token,
          refresh_token: 'refresh-token-placeholder',
          expires_in: 3600,
        });

        // Reset mock tracking for this iteration
        mockFetch.mockClear();

        // Call authenticatedFetch
        await authenticatedFetch(url);

        // Verify fetch was called with the Authorization header
        expect(mockFetch).toHaveBeenCalledTimes(1);
        const [calledUrl, calledOptions] = mockFetch.mock.calls[0];
        expect(calledUrl).toBe(url);
        expect(calledOptions.headers).toBeDefined();
        expect(calledOptions.headers.Authorization).toBe(`Bearer ${token}`);
      }),
      { numRuns: 100 }
    );
  });

  it('the token in the Authorization header matches the one from getAccessToken()', async () => {
    await fc.assert(
      fc.asyncProperty(tokenArb, async (token) => {
        // Set up session with the generated token
        auth._setTokens({
          access_token: token,
          refresh_token: 'refresh-token-placeholder',
          expires_in: 3600,
        });

        // Get the token via getAccessToken
        const retrievedToken = await auth.getAccessToken();
        expect(retrievedToken).toBe(token);

        // Get auth headers and verify they contain the same token
        const headers = await getAuthHeaders();
        expect(headers.Authorization).toBe(`Bearer ${token}`);
        expect(headers.Authorization).toBe(`Bearer ${retrievedToken}`);
      }),
      { numRuns: 100 }
    );
  });

  it('authenticatedFetch attaches the correct token for varying tokens and request options', async () => {
    const httpMethodArb = fc.constantFrom('GET', 'POST', 'PUT', 'DELETE', 'PATCH');

    await fc.assert(
      fc.asyncProperty(tokenArb, urlPathArb, httpMethodArb, async (token, url, method) => {
        // Set up active session
        auth._setTokens({
          access_token: token,
          refresh_token: 'refresh-token-placeholder',
          expires_in: 3600,
        });

        // Reset mock tracking for this iteration
        mockFetch.mockClear();

        // Call authenticatedFetch with various HTTP methods
        await authenticatedFetch(url, { method });

        // Verify the Authorization header is present and correct
        expect(mockFetch).toHaveBeenCalledTimes(1);
        const [, calledOptions] = mockFetch.mock.calls[0];
        expect(calledOptions.headers.Authorization).toBe(`Bearer ${token}`);
        expect(calledOptions.method).toBe(method);
      }),
      { numRuns: 100 }
    );
  });
});


// Feature: frontend-spa, Property 11: Error responses produce user-friendly messages

/**
 * **Validates: Requirements 8.3**
 *
 * Property 11: For any HTTP error response (4xx or 5xx), the error handler produces
 * a user-friendly message string that does not contain raw stack traces,
 * exception class names, or internal server details.
 */
describe('Property 11: Error responses produce user-friendly messages', () => {
  // Technical patterns that should never appear in user-facing messages
  const technicalPatterns = [
    /Exception/i,
    /Error:/,
    /\bat\s+\S+\s*\(/,            // stack frame: "at Object.method (file:line)"
    /NullPointer/i,
    /\bundefined\b/i,
    /\{"error"/,                    // raw JSON like {"error":...}
    /at\s+Object\.\w+\s*\(/,      // "at Object.method ("
    /at\s+\w+\.\w+\s*\(/,         // "at Class.method ("
    /\.js:\d+:\d+/,               // file.js:10:5 stack trace patterns
  ];

  // Generator for HTTP error status codes (400-599)
  const errorStatusArb = fc.integer({ min: 400, max: 599 });

  // Generator for arbitrary response bodies including technical content
  const technicalBodies = [
    'java.lang.NullPointerException: Cannot invoke method on null',
    'Error: ENOENT: no such file or directory',
    'at Object.readFileSync (fs.js:584:3)\n    at Module._compile (internal/modules/cjs/loader.js:1063:30)',
    '{"error": "InternalServerError", "message": "Something went wrong", "stack": "at handler (/app/index.js:42:11)"}',
    'TypeError: Cannot read properties of undefined (reading \'id\')',
    'UnhandledPromiseRejection: Error at processTicksAndRejections (node:internal/process/task_queues:95:5)',
    'com.amazonaws.services.lambda.runtime.LambdaRuntimeInternal$LambdaRuntimeException',
    'Traceback (most recent call last):\n  File "app.py", line 42, in handler\n    raise ValueError("Invalid input")',
    '<html><body><h1>500 Internal Server Error</h1><pre>at Object.handler (/var/task/index.js:15:9)</pre></body></html>',
    'FATAL ERROR: CALL_AND_RETRY_LAST Allocation failed - JavaScript heap out of memory',
  ];

  const responseBodyArb = fc.oneof(
    fc.string(),                                    // random strings
    fc.constant(''),                                // empty body
    fc.constantFrom(...technicalBodies),            // known technical content
    fc.string().map(s => `{"error": "${s}"}`),      // JSON-like error bodies
    fc.string().map(s => `Exception in ${s}`),      // exception messages
    fc.string().map(s => `at ${s} (file.js:42:10)`), // stack frames
  );

  it('should return a non-empty string for any error status code', () => {
    fc.assert(
      fc.property(errorStatusArb, responseBodyArb, (status, body) => {
        const message = mapErrorToMessage(status, body);

        // Must be a non-empty string
        expect(typeof message).toBe('string');
        expect(message.length).toBeGreaterThan(0);
      }),
      { numRuns: 100 }
    );
  });

  it('should not contain common technical terms in the message', () => {
    fc.assert(
      fc.property(errorStatusArb, responseBodyArb, (status, body) => {
        const message = mapErrorToMessage(status, body);

        // Message should not contain any technical patterns
        for (const pattern of technicalPatterns) {
          expect(message).not.toMatch(pattern);
        }
      }),
      { numRuns: 100 }
    );
  });

  it('should not contain the raw response body content', () => {
    fc.assert(
      fc.property(errorStatusArb, responseBodyArb, (status, body) => {
        const message = mapErrorToMessage(status, body);

        // If the body has substantive content (non-empty, more than trivial),
        // the message should not contain the raw body
        if (body && body.length > 10) {
          expect(message).not.toContain(body);
        }
      }),
      { numRuns: 100 }
    );
  });

  it('should produce a user-friendly message (no raw technical details leaked)', () => {
    fc.assert(
      fc.property(errorStatusArb, responseBodyArb, (status, body) => {
        const message = mapErrorToMessage(status, body);

        // The message must be a known friendly message — either from ERROR_MESSAGES
        // or one of the generic fallback messages
        const knownMessages = [
          ...Object.values(ERROR_MESSAGES),
          'The request could not be completed. Please try again.',
          'An unexpected server error occurred. Please try again later.',
        ];

        expect(knownMessages).toContain(message);
      }),
      { numRuns: 100 }
    );
  });
});


// Feature: frontend-spa, Property 10: API requests with body include JSON content-type

/**
 * Property 10: API requests with body include JSON content-type
 *
 * For any API request made through the API client that includes a request body,
 * the request includes a `Content-Type: application/json` header.
 *
 * Validates: Requirements 8.2
 */
describe('Property 10: API requests with body include JSON content-type', () => {
  let mockFetch;
  let auth;
  let authenticatedFetch;

  beforeEach(async () => {
    // Set up fetch mock to capture request headers
    mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: () => Promise.resolve('{}'),
      json: () => Promise.resolve({}),
    });
    vi.stubGlobal('fetch', mockFetch);

    // Dynamically import modules after mocking fetch
    const authModule = await import('../../js/auth.js');
    const apiModule = await import('../../js/api.js');

    auth = authModule.auth;
    authenticatedFetch = apiModule.authenticatedFetch;

    // Set up a valid session so authenticatedFetch doesn't redirect to login
    auth._setTokens({
      access_token: 'test-access-token-12345',
      refresh_token: 'test-refresh-token',
      expires_in: 3600,
    });
  });

  afterEach(() => {
    auth._clearState();
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  /**
   * Arbitrary that generates JSON-serializable objects suitable as request bodies.
   */
  const jsonBodyArb = fc.oneof(
    fc.record({
      title: fc.string({ minLength: 1, maxLength: 200 }),
      description: fc.string({ maxLength: 500 }),
    }),
    fc.record({
      id: fc.integer({ min: 1, max: 99999 }),
      name: fc.string({ minLength: 1, maxLength: 100 }),
      active: fc.boolean(),
    }),
    fc.record({
      data: fc.array(fc.integer(), { minLength: 0, maxLength: 10 }),
    }),
    fc.dictionary(
      fc.string({ minLength: 1, maxLength: 20 }).filter((s) => /^[a-zA-Z]/.test(s)),
      fc.oneof(fc.string(), fc.integer(), fc.boolean())
    )
  );

  /**
   * Arbitrary that generates valid API endpoint paths.
   */
  const urlPathArb = fc.string({ minLength: 1, maxLength: 30 }).filter(
    (s) => /^[a-z][a-z0-9/\-]*$/.test(s)
  ).map((path) => `https://api.example.com/${path}`);

  /**
   * Arbitrary that generates HTTP methods that typically carry a body.
   */
  const methodWithBodyArb = fc.constantFrom('POST', 'PUT', 'PATCH');

  it('any request with a JSON body preserves Content-Type: application/json header', async () => {
    await fc.assert(
      fc.asyncProperty(
        jsonBodyArb,
        urlPathArb,
        methodWithBodyArb,
        async (body, url, method) => {
          mockFetch.mockClear();

          const options = {
            method,
            headers: {
              'Content-Type': 'application/json',
            },
            body: JSON.stringify(body),
          };

          await authenticatedFetch(url, options);

          // Verify fetch was called
          expect(mockFetch).toHaveBeenCalledTimes(1);

          // Verify Content-Type header is present and set to application/json
          const [, calledOptions] = mockFetch.mock.calls[0];
          expect(calledOptions.headers).toBeDefined();
          expect(calledOptions.headers['Content-Type']).toBe('application/json');
        }
      ),
      { numRuns: 100 }
    );
  });

  it('Content-Type: application/json coexists with Authorization header when body is present', async () => {
    await fc.assert(
      fc.asyncProperty(
        jsonBodyArb,
        methodWithBodyArb,
        async (body, method) => {
          mockFetch.mockClear();

          const url = 'https://api.example.com/submissions';
          const options = {
            method,
            headers: {
              'Content-Type': 'application/json',
            },
            body: JSON.stringify(body),
          };

          await authenticatedFetch(url, options);

          // Verify fetch was called
          expect(mockFetch).toHaveBeenCalledTimes(1);

          const [, calledOptions] = mockFetch.mock.calls[0];

          // Both headers should coexist without conflict
          expect(calledOptions.headers['Content-Type']).toBe('application/json');
          expect(calledOptions.headers['Authorization']).toBe('Bearer test-access-token-12345');
        }
      ),
      { numRuns: 100 }
    );
  });
});
