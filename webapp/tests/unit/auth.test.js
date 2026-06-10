import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { auth, generateCodeVerifier, generateCodeChallenge, base64UrlEncode, CONFIG } from '../../js/auth.js';

describe('auth module', () => {
  beforeEach(() => {
    auth._clearState();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('PKCE helpers', () => {
    it('generateCodeVerifier produces a URL-safe base64 string', () => {
      const verifier = generateCodeVerifier();
      expect(verifier).toBeTruthy();
      expect(verifier.length).toBeGreaterThanOrEqual(32);
      // Should not contain +, /, or = (base64url encoding)
      expect(verifier).not.toMatch(/[+/=]/);
    });

    it('generateCodeVerifier produces different values on each call', () => {
      const v1 = generateCodeVerifier();
      const v2 = generateCodeVerifier();
      expect(v1).not.toBe(v2);
    });

    it('generateCodeChallenge returns a base64url string derived from SHA-256', async () => {
      const verifier = 'test-verifier-string';
      const challenge = await generateCodeChallenge(verifier);
      expect(challenge).toBeTruthy();
      expect(challenge.length).toBeGreaterThan(0);
      // Should be base64url (no +, /, =)
      expect(challenge).not.toMatch(/[+/=]/);
    });

    it('generateCodeChallenge produces same output for same input', async () => {
      const verifier = 'deterministic-test';
      const c1 = await generateCodeChallenge(verifier);
      const c2 = await generateCodeChallenge(verifier);
      expect(c1).toBe(c2);
    });

    it('base64UrlEncode encodes correctly without padding', () => {
      const input = new Uint8Array([72, 101, 108, 108, 111]); // "Hello"
      const result = base64UrlEncode(input);
      expect(result).not.toMatch(/[+/=]/);
      expect(result).toBeTruthy();
    });
  });

  describe('login()', () => {
    it('redirects to Cognito hosted UI with PKCE parameters', async () => {
      // Mock window.location.href assignment
      const hrefSetter = vi.fn();
      Object.defineProperty(window, 'location', {
        value: { href: '', origin: 'http://localhost' },
        writable: true,
        configurable: true,
      });
      Object.defineProperty(window.location, 'href', {
        set: hrefSetter,
        get: () => '',
        configurable: true,
      });

      await auth.login();

      expect(hrefSetter).toHaveBeenCalledTimes(1);
      const url = hrefSetter.mock.calls[0][0];
      expect(url).toContain(`${CONFIG.cognitoDomain}/oauth2/authorize`);
      expect(url).toContain('response_type=code');
      expect(url).toContain(`client_id=${CONFIG.clientId}`);
      expect(url).toContain('code_challenge_method=S256');
      expect(url).toContain('code_challenge=');
    });

    it('stores code_verifier in memory after login', async () => {
      Object.defineProperty(window, 'location', {
        value: { href: '', origin: 'http://localhost' },
        writable: true,
        configurable: true,
      });

      await auth.login();

      expect(auth._getCodeVerifier()).toBeTruthy();
      expect(auth._getCodeVerifier().length).toBeGreaterThan(0);
    });
  });

  describe('handleCallback(code)', () => {
    it('exchanges authorization code for tokens', async () => {
      auth._setCodeVerifier('test-verifier');

      const mockResponse = {
        access_token: 'mock-access-token',
        refresh_token: 'mock-refresh-token',
        expires_in: 3600,
        token_type: 'Bearer',
      };

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockResponse),
      });

      const result = await auth.handleCallback('test-auth-code');

      expect(result).toBe(true);
      expect(global.fetch).toHaveBeenCalledTimes(1);

      const [url, options] = global.fetch.mock.calls[0];
      expect(url).toBe(`${CONFIG.cognitoDomain}/oauth2/token`);
      expect(options.method).toBe('POST');
      expect(options.headers['Content-Type']).toBe('application/x-www-form-urlencoded');
      expect(options.body).toContain('grant_type=authorization_code');
      expect(options.body).toContain('code=test-auth-code');
      expect(options.body).toContain('code_verifier=test-verifier');
    });

    it('stores tokens in memory after successful exchange', async () => {
      auth._setCodeVerifier('test-verifier');

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({
          access_token: 'my-access-token',
          refresh_token: 'my-refresh-token',
          expires_in: 3600,
        }),
      });

      await auth.handleCallback('code123');

      const state = auth._getState();
      expect(state.accessToken).toBe('my-access-token');
      expect(state.refreshToken).toBe('my-refresh-token');
      expect(state.expiresAt).toBeGreaterThan(Date.now());
    });

    it('clears code_verifier after successful exchange', async () => {
      auth._setCodeVerifier('test-verifier');

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({
          access_token: 'token',
          refresh_token: 'refresh',
          expires_in: 3600,
        }),
      });

      await auth.handleCallback('code');

      expect(auth._getCodeVerifier()).toBeNull();
    });

    it('throws error when code_verifier is missing', async () => {
      auth._setCodeVerifier(null);

      await expect(auth.handleCallback('code')).rejects.toThrow('Missing code_verifier');
    });

    it('throws error on failed token exchange', async () => {
      auth._setCodeVerifier('verifier');

      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 400,
        text: () => Promise.resolve('invalid_grant'),
      });

      await expect(auth.handleCallback('bad-code')).rejects.toThrow('Token exchange failed');
    });
  });

  describe('getAccessToken()', () => {
    it('returns access token when valid and not expired', async () => {
      auth._setTokens({
        access_token: 'valid-token',
        refresh_token: 'refresh',
        expires_in: 3600,
      });

      const token = await auth.getAccessToken();
      expect(token).toBe('valid-token');
    });

    it('attempts refresh when token is expired', async () => {
      auth._setTokens({
        access_token: 'expired-token',
        refresh_token: 'my-refresh',
        expires_in: -1, // Already expired
      });

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({
          access_token: 'new-token',
          expires_in: 3600,
        }),
      });

      const token = await auth.getAccessToken();
      expect(token).toBe('new-token');
      expect(global.fetch).toHaveBeenCalledTimes(1);
    });

    it('returns null when no refresh token available and token expired', async () => {
      auth._setTokens({
        access_token: 'expired',
        expires_in: -1,
      });

      const token = await auth.getAccessToken();
      expect(token).toBeNull();
    });
  });

  describe('refreshAccessToken()', () => {
    it('refreshes token using refresh_token grant', async () => {
      auth._setTokens({
        access_token: 'old',
        refresh_token: 'my-refresh-token',
        expires_in: -1,
      });

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({
          access_token: 'refreshed-token',
          expires_in: 3600,
        }),
      });

      const result = await auth.refreshAccessToken();
      expect(result).toBe(true);

      const state = auth._getState();
      expect(state.accessToken).toBe('refreshed-token');

      const [url, options] = global.fetch.mock.calls[0];
      expect(url).toBe(`${CONFIG.cognitoDomain}/oauth2/token`);
      expect(options.body).toContain('grant_type=refresh_token');
      expect(options.body).toContain('refresh_token=my-refresh-token');
    });

    it('returns false and clears tokens on refresh failure', async () => {
      auth._setTokens({
        access_token: 'old',
        refresh_token: 'bad-refresh',
        expires_in: -1,
      });

      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 400,
      });

      const result = await auth.refreshAccessToken();
      expect(result).toBe(false);

      const state = auth._getState();
      expect(state.accessToken).toBeNull();
      expect(state.refreshToken).toBeNull();
    });

    it('returns false when no refresh token exists', async () => {
      const result = await auth.refreshAccessToken();
      expect(result).toBe(false);
    });

    it('clears tokens on network error during refresh', async () => {
      auth._setTokens({
        access_token: 'old',
        refresh_token: 'refresh',
        expires_in: -1,
      });

      global.fetch = vi.fn().mockRejectedValue(new Error('Network error'));

      const result = await auth.refreshAccessToken();
      expect(result).toBe(false);

      const state = auth._getState();
      expect(state.accessToken).toBeNull();
    });
  });

  describe('logout()', () => {
    it('clears all tokens from memory', () => {
      auth._setTokens({
        access_token: 'token',
        refresh_token: 'refresh',
        expires_in: 3600,
      });

      Object.defineProperty(window, 'location', {
        value: { href: '' },
        writable: true,
        configurable: true,
      });

      auth.logout();

      const state = auth._getState();
      expect(state.accessToken).toBeNull();
      expect(state.refreshToken).toBeNull();
      expect(state.expiresAt).toBeNull();
    });

    it('redirects to Cognito logout endpoint', () => {
      auth._setTokens({
        access_token: 'token',
        refresh_token: 'refresh',
        expires_in: 3600,
      });

      const hrefSetter = vi.fn();
      Object.defineProperty(window, 'location', {
        value: { href: '' },
        writable: true,
        configurable: true,
      });
      Object.defineProperty(window.location, 'href', {
        set: hrefSetter,
        get: () => '',
        configurable: true,
      });

      auth.logout();

      expect(hrefSetter).toHaveBeenCalledTimes(1);
      const url = hrefSetter.mock.calls[0][0];
      expect(url).toContain(`${CONFIG.cognitoDomain}/logout`);
      expect(url).toContain(`client_id=${CONFIG.clientId}`);
      expect(url).toContain('logout_uri=');
    });
  });

  describe('isAuthenticated()', () => {
    it('returns false when no tokens present', () => {
      expect(auth.isAuthenticated()).toBe(false);
    });

    it('returns true when access token is valid and not expired', () => {
      auth._setTokens({
        access_token: 'valid-token',
        refresh_token: 'refresh',
        expires_in: 3600,
      });
      expect(auth.isAuthenticated()).toBe(true);
    });

    it('returns false when access token is expired', () => {
      auth._setTokens({
        access_token: 'expired-token',
        refresh_token: 'refresh',
        expires_in: -1,
      });
      expect(auth.isAuthenticated()).toBe(false);
    });

    it('returns false after logout', () => {
      auth._setTokens({
        access_token: 'token',
        refresh_token: 'refresh',
        expires_in: 3600,
      });

      Object.defineProperty(window, 'location', {
        value: { href: '' },
        writable: true,
        configurable: true,
      });

      auth.logout();
      expect(auth.isAuthenticated()).toBe(false);
    });
  });

  describe('token storage', () => {
    it('never writes to localStorage', async () => {
      const setItemSpy = vi.spyOn(Storage.prototype, 'setItem');

      auth._setTokens({
        access_token: 'token',
        refresh_token: 'refresh',
        expires_in: 3600,
      });

      expect(setItemSpy).not.toHaveBeenCalled();
    });

    it('never writes to sessionStorage', async () => {
      const setItemSpy = vi.spyOn(Storage.prototype, 'setItem');

      auth._setTokens({
        access_token: 'token',
        refresh_token: 'refresh',
        expires_in: 3600,
      });

      expect(setItemSpy).not.toHaveBeenCalled();
    });
  });
});
