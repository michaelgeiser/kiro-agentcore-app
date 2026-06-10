/**
 * Manages Cognito authentication with PKCE flow.
 * Tokens are held in module-scoped variables (memory only).
 *
 * Requirements: 2.1, 2.2, 2.3, 2.4, 2.5
 */

// --- Configuration (placeholder values, replace with real Cognito settings) ---
const CONFIG = {
  cognitoDomain: 'https://your-app.auth.us-east-1.amazoncognito.com',
  clientId: 'your-cognito-client-id',
  redirectUri: `${typeof window !== 'undefined' ? window.location.origin : 'http://localhost'}`,
  logoutUri: `${typeof window !== 'undefined' ? window.location.origin : 'http://localhost'}`,
  scopes: 'openid profile email',
};

// --- AuthState (in-memory only, never localStorage) ---

/** @type {string|null} */
let accessToken = null;

/** @type {string|null} */
let refreshToken = null;

/** @type {number|null} */
let expiresAt = null;

/** @type {string|null} */
let codeVerifier = null;

// --- PKCE Helpers ---

/**
 * Generate a cryptographically random code_verifier string.
 * @returns {string} A URL-safe random string (43-128 characters)
 */
function generateCodeVerifier() {
  const array = new Uint8Array(32);
  crypto.getRandomValues(array);
  return base64UrlEncode(array);
}

/**
 * Generate a code_challenge from the code_verifier using SHA-256.
 * @param {string} verifier - The code_verifier string
 * @returns {Promise<string>} The base64url-encoded SHA-256 hash
 */
async function generateCodeChallenge(verifier) {
  const encoder = new TextEncoder();
  const data = encoder.encode(verifier);
  const digest = await crypto.subtle.digest('SHA-256', data);
  return base64UrlEncode(new Uint8Array(digest));
}

/**
 * Base64url-encode a Uint8Array (no padding, URL-safe).
 * @param {Uint8Array} buffer
 * @returns {string}
 */
function base64UrlEncode(buffer) {
  let binary = '';
  for (let i = 0; i < buffer.length; i++) {
    binary += String.fromCharCode(buffer[i]);
  }
  return btoa(binary)
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '');
}

// --- Auth Module ---

export const auth = {
  /**
   * Redirect to Cognito hosted UI if no valid session.
   * Uses Authorization Code flow with PKCE.
   * Requirement: 2.1
   */
  async login() {
    const verifier = generateCodeVerifier();
    const challenge = await generateCodeChallenge(verifier);

    // Store code_verifier in memory for the callback exchange
    codeVerifier = verifier;

    const params = new URLSearchParams({
      response_type: 'code',
      client_id: CONFIG.clientId,
      redirect_uri: CONFIG.redirectUri,
      scope: CONFIG.scopes,
      code_challenge_method: 'S256',
      code_challenge: challenge,
    });

    const loginUrl = `${CONFIG.cognitoDomain}/oauth2/authorize?${params.toString()}`;
    window.location.href = loginUrl;
  },

  /**
   * Exchange authorization code for tokens using the token endpoint.
   * Requirement: 2.2, 2.3
   * @param {string} code - The authorization code from Cognito callback
   * @returns {Promise<boolean>} True if token exchange succeeded
   */
  async handleCallback(code) {
    if (!codeVerifier) {
      throw new Error('Missing code_verifier. Login flow may not have been initiated properly.');
    }

    const params = new URLSearchParams({
      grant_type: 'authorization_code',
      client_id: CONFIG.clientId,
      redirect_uri: CONFIG.redirectUri,
      code,
      code_verifier: codeVerifier,
    });

    const response = await fetch(`${CONFIG.cognitoDomain}/oauth2/token`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: params.toString(),
    });

    if (!response.ok) {
      const errorBody = await response.text();
      throw new Error(`Token exchange failed: ${response.status} ${errorBody}`);
    }

    const data = await response.json();
    setTokens(data);

    // Clear code_verifier after successful exchange
    codeVerifier = null;

    return true;
  },

  /**
   * Return current valid access token, refreshing if expired.
   * Requirement: 2.3, 2.4
   * @returns {Promise<string|null>} The valid access token, or null if unavailable
   */
  async getAccessToken() {
    if (accessToken && expiresAt && Date.now() < expiresAt) {
      return accessToken;
    }

    // Token is expired or missing — attempt refresh
    if (refreshToken) {
      const refreshed = await this.refreshAccessToken();
      if (refreshed) {
        return accessToken;
      }
    }

    return null;
  },

  /**
   * Attempt to refresh the access token using the refresh token.
   * Requirement: 2.4
   * @returns {Promise<boolean>} True if refresh succeeded
   */
  async refreshAccessToken() {
    if (!refreshToken) {
      return false;
    }

    const params = new URLSearchParams({
      grant_type: 'refresh_token',
      client_id: CONFIG.clientId,
      refresh_token: refreshToken,
    });

    try {
      const response = await fetch(`${CONFIG.cognitoDomain}/oauth2/token`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: params.toString(),
      });

      if (!response.ok) {
        // Refresh token is invalid/expired — clear state
        clearTokens();
        return false;
      }

      const data = await response.json();
      setTokens(data);
      return true;
    } catch {
      clearTokens();
      return false;
    }
  },

  /**
   * Clear tokens from memory and redirect to Cognito logout endpoint.
   * Requirement: 2.5
   */
  logout() {
    clearTokens();

    const params = new URLSearchParams({
      client_id: CONFIG.clientId,
      logout_uri: CONFIG.logoutUri,
    });

    window.location.href = `${CONFIG.cognitoDomain}/logout?${params.toString()}`;
  },

  /**
   * Check if user has a valid (non-expired) session.
   * @returns {boolean} True if a valid access token exists
   */
  isAuthenticated() {
    return accessToken !== null && expiresAt !== null && Date.now() < expiresAt;
  },

  // --- Test helpers (exposed for unit testing only) ---

  /**
   * Get the current code verifier (for testing).
   * @returns {string|null}
   */
  _getCodeVerifier() {
    return codeVerifier;
  },

  /**
   * Set the code verifier (for testing callback without full login flow).
   * @param {string|null} verifier
   */
  _setCodeVerifier(verifier) {
    codeVerifier = verifier;
  },

  /**
   * Directly set tokens (for testing).
   * @param {{ access_token: string, refresh_token?: string, expires_in: number }} tokenData
   */
  _setTokens(tokenData) {
    setTokens(tokenData);
  },

  /**
   * Clear all auth state (for testing).
   */
  _clearState() {
    clearTokens();
    codeVerifier = null;
  },

  /**
   * Get current auth state (for testing).
   * @returns {{ accessToken: string|null, refreshToken: string|null, expiresAt: number|null }}
   */
  _getState() {
    return { accessToken, refreshToken, expiresAt };
  },
};

// --- Internal Helpers ---

/**
 * Store token data from Cognito response into module-scoped variables.
 * @param {{ access_token: string, refresh_token?: string, expires_in: number }} data
 */
function setTokens(data) {
  accessToken = data.access_token;
  if (data.refresh_token) {
    refreshToken = data.refresh_token;
  }
  // expires_in is in seconds; convert to ms timestamp
  expiresAt = Date.now() + data.expires_in * 1000;
}

/**
 * Clear all token data from memory.
 */
function clearTokens() {
  accessToken = null;
  refreshToken = null;
  expiresAt = null;
}

// --- Exported helpers for use by other modules ---
export { generateCodeVerifier, generateCodeChallenge, base64UrlEncode, CONFIG };
