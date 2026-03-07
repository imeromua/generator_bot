/**
 * sd-auth.js — JWT token management for the ServiceDesk SPA.
 *
 * Tokens are kept in localStorage. If "remember me" is enabled,
 * the refresh token survives a browser restart.
 */

const SD_AUTH = (() => {
  const KEY_ACCESS  = 'sd_access_token';
  const KEY_REFRESH = 'sd_refresh_token';
  const KEY_USER    = 'sd_user';

  /** Persist tokens after a successful login. */
  function saveTokens(accessToken, refreshToken, remember = false) {
    localStorage.setItem(KEY_ACCESS, accessToken);
    if (refreshToken) {
      if (remember) {
        localStorage.setItem(KEY_REFRESH, refreshToken);
      } else {
        // Only keep for this browser session
        sessionStorage.setItem(KEY_REFRESH, refreshToken);
        localStorage.removeItem(KEY_REFRESH);
      }
    }
  }

  /** Overwrite only the access token (after a /refresh call). */
  function saveAccessToken(accessToken) {
    localStorage.setItem(KEY_ACCESS, accessToken);
  }

  /** Save user profile from /me or login response. */
  function saveUser(user) {
    localStorage.setItem(KEY_USER, JSON.stringify(user));
  }

  /** Return current access token or null. */
  function getAccessToken() {
    return localStorage.getItem(KEY_ACCESS);
  }

  /** Return current refresh token or null (checks both storages). */
  function getRefreshToken() {
    return localStorage.getItem(KEY_REFRESH) || sessionStorage.getItem(KEY_REFRESH);
  }

  /** Return cached user profile or null. */
  function getUser() {
    try {
      const raw = localStorage.getItem(KEY_USER);
      return raw ? JSON.parse(raw) : null;
    } catch {
      return null;
    }
  }

  /** True when an access token exists. */
  function isAuthenticated() {
    return !!localStorage.getItem(KEY_ACCESS);
  }

  /**
   * Clear all auth state and optionally call the server logout endpoint.
   * Redirects to login page when done.
   */
  async function logout(callServer = true) {
    const token = getAccessToken();
    _clearStorage();
    if (callServer && token) {
      try {
        await fetch('/api/sd/auth/logout', {
          method: 'POST',
          headers: { Authorization: `Bearer ${token}` },
        });
      } catch {
        // ignore network errors during logout
      }
    }
    window.location.href = '/sd/login.html';
  }

  function _clearStorage() {
    localStorage.removeItem(KEY_ACCESS);
    localStorage.removeItem(KEY_REFRESH);
    localStorage.removeItem(KEY_USER);
    sessionStorage.removeItem(KEY_REFRESH);
  }

  return { saveTokens, saveAccessToken, saveUser, getAccessToken, getRefreshToken, getUser, isAuthenticated, logout };
})();

// Make available as both a module-style export and a global
if (typeof module !== 'undefined') module.exports = SD_AUTH;
