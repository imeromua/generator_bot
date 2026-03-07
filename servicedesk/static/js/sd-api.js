/**
 * sd-api.js — API client for the ServiceDesk SPA.
 *
 * All fetch requests go through the `request()` helper which:
 *   1. Attaches the Bearer token from sd-auth.js.
 *   2. On 401 attempts a token refresh then retries once.
 *   3. Throws an Error (message = server detail) on non-2xx.
 *
 * Usage:
 *   const data = await api.auth.me();
 *   const logs = await api.logs.list({ limit: 50 });
 */

const api = (() => {
  const BASE = '';          // same origin
  let _refreshing = null;   // pending refresh promise (de-dup)

  /* ── Core fetch wrapper ─────────────────────────────────── */

  async function request(method, path, { body, params } = {}, _retry = true) {
    let url = BASE + path;
    if (params) {
      const qs = new URLSearchParams(
        Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== '')
      ).toString();
      if (qs) url += '?' + qs;
    }

    const token = SD_AUTH.getAccessToken();
    const headers = { 'Content-Type': 'application/json' };
    if (token) headers['Authorization'] = `Bearer ${token}`;

    const resp = await fetch(url, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });

    if (resp.status === 401 && _retry) {
      // Try to refresh the access token once
      const refreshed = await _doRefresh();
      if (refreshed) return request(method, path, { body, params }, false);
      // Refresh failed → logout
      await SD_AUTH.logout(false);
      return;
    }

    if (!resp.ok) {
      let detail = `HTTP ${resp.status}`;
      try {
        const err = await resp.json();
        detail = err.detail || err.message || detail;
      } catch { /* noop */ }
      throw new Error(detail);
    }

    const ct = resp.headers.get('content-type') || '';
    if (ct.includes('application/json')) return resp.json();
    if (ct.includes('application/octet-stream') || ct.includes('blob')) return resp.blob();
    return resp.text();
  }

  async function _doRefresh() {
    if (_refreshing) return _refreshing;
    _refreshing = (async () => {
      const refreshToken = SD_AUTH.getRefreshToken();
      if (!refreshToken) return false;
      try {
        const resp = await fetch(`${BASE}/api/sd/auth/refresh`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh_token: refreshToken }),
        });
        if (!resp.ok) return false;
        const data = await resp.json();
        if (data.access_token) {
          SD_AUTH.saveAccessToken(data.access_token);
          return true;
        }
        return false;
      } catch {
        return false;
      } finally {
        _refreshing = null;
      }
    })();
    return _refreshing;
  }

  const get    = (path, opts) => request('GET',    path, opts);
  const post   = (path, opts) => request('POST',   path, opts);
  const put    = (path, opts) => request('PUT',    path, opts);
  const del    = (path, opts) => request('DELETE', path, opts);

  /* ── Auth ────────────────────────────────────────────────── */
  const auth = {
    login(login, password) {
      return post('/api/sd/auth/login', { body: { login, password } });
    },
    logout() {
      return post('/api/sd/auth/logout');
    },
    refresh(refreshToken) {
      return post('/api/sd/auth/refresh', { body: { refresh_token: refreshToken } });
    },
    me() {
      return get('/api/sd/auth/me');
    },
    changePassword(oldPassword, newPassword) {
      return post('/api/sd/auth/change-password', { body: { old_password: oldPassword, new_password: newPassword } });
    },
  };

  /* ── Logs (audit trail) ──────────────────────────────────── */
  const logs = {
    list(params) {
      return get('/api/admin/audit', { params });
    },
    create(data) {
      return post('/api/admin/audit', { body: data });
    },
  };

  /* ── Maintenance ─────────────────────────────────────────── */
  const maintenance = {
    list(params) {
      return get('/api/maintenance', { params });
    },
    create(data) {
      return post('/api/maintenance/perform', { body: data });
    },
  };

  /* ── Fuel orders ─────────────────────────────────────────── */
  const fuel = {
    list(params) {
      return get('/api/fuel/orders', { params });
    },
    create(data) {
      return post('/api/fuel/orders', { body: data });
    },
    updateStatus(data) {
      return post('/api/fuel/orders/update', { body: data });
    },
  };

  /* ── Shift schedule ──────────────────────────────────────── */
  const schedule = {
    list(params) {
      return get('/api/shifts/schedule', { params });
    },
    create(data) {
      return post('/api/shifts/schedule', { body: data });
    },
  };

  /* ── Users (admin) ───────────────────────────────────────── */
  const users = {
    list(params) {
      return get('/api/admin/users', { params });
    },
    block(userId) {
      return put(`/api/admin/users/${userId}/block`);
    },
    unblock(userId) {
      return put(`/api/admin/users/${userId}/unblock`);
    },
    setPassword(userId, password) {
      return post('/api/sd/auth/change-password', { body: { user_id: userId, password } });
    },
  };

  /* ── Status (dashboard overview) ────────────────────────── */
  const status = {
    current() {
      return get('/api/status');
    },
    schedule() {
      return get('/api/schedule');
    },
  };

  return { auth, logs, maintenance, fuel, schedule, users, status, request };
})();

if (typeof module !== 'undefined') module.exports = api;
