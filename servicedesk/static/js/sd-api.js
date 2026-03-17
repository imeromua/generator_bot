/**
 * sd-api.js — API client for the ServiceDesk SPA.
 *
 * All fetch requests go through the `request()` helper which:
 *   1. Attaches the Bearer token from sd-auth.js.
 *   2. On 401 attempts a token refresh then retries once.
 *   3. Throws an Error (message = server detail) on non-2xx.
 *
 * Namespaces:
 *   auth, logs, events, maintenance, fuel, schedule, shifts,
 *   users, status, actions, powerSchedule, admin, analytics,
 *   reports, notifications
 *
 * Usage:
 *   const data = await api.auth.me();
 *   const logs = await api.logs.list({ limit: 50 });
 *   const kpi  = await api.analytics.kpi({ days: 30 });
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

  /* ── Events (webapp events log) ─────────────────────────── */
  const events = {
    list(params) {
      return get('/api/events', { params });
    },
  };

  /* ── Maintenance (extended) ─────────────────────────────── */
  const maintenance = {
    list(params) {
      return get('/api/maintenance', { params });
    },
    perform(data) {
      return post('/api/maintenance/perform', { body: data });
    },
    setHours(data) {
      return post('/api/maintenance/set-hours', { body: data });
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

  /* ── Shifts (extended) ───────────────────────────────────── */
  const shifts = {
    list(params) {
      return get('/api/shifts/schedule', { params });
    },
    create(data) {
      return post('/api/shifts/schedule', { body: data });
    },
    auto(month, save) {
      return post('/api/shifts/auto', { body: { month, save } });
    },
    analytics(params) {
      return get('/api/shifts/analytics', { params });
    },
  };

  /* ── Users (extended) ────────────────────────────────────── */
  const users = {
    list(params) {
      return get('/api/admin/users', { params });
    },
    updateRole(userId, role) {
      return put(`/api/admin/users/${userId}/role`, { body: { role } });
    },
    block(userId, reason) {
      return put(`/api/admin/users/${userId}/block`, { body: { reason } });
    },
    unblock(userId) {
      return put(`/api/admin/users/${userId}/unblock`);
    },
    deleteUser(userId) {
      return del(`/api/admin/users/${userId}`);
    },
  };

  /* ── Status (extended) ───────────────────────────────────── */
  const status = {
    current() {
      return get('/api/status');
    },
    schedule(date) {
      return get('/api/schedule', { params: { date } });
    },
    week() {
      return get('/api/schedule/week');
    },
    generators() {
      return get('/api/generators');
    },
  };

  /* ── Actions (shift start/stop, refuel, generator switch) ── */
  const actions = {
    startShift(shift) {
      return post('/api/action/start', { body: { shift } });
    },
    stopShift(shift) {
      return post('/api/action/stop', { body: { shift } });
    },
    refuel(driver, liters, receipt_number) {
      return post('/api/action/refill', { body: { driver, liters, receipt_number } });
    },
    switchGenerator(target) {
      return post('/api/generator/switch', { body: { target } });
    },
    setFuel(fuel_liters) {
      return post('/api/fuel/set', { body: { fuel_liters } });
    },
  };

  /* ── Power schedule (24h grid) ──────────────────────────── */
  const powerSchedule = {
    get(date) {
      return get('/api/schedule', { params: { date } });
    },
    week() {
      return get('/api/schedule/week');
    },
    toggle(date, hour) {
      return post('/api/schedule/toggle', { body: { date, hour } });
    },
  };

  /* ── Admin config ───────────────────────────────────────── */
  const admin = {
    getConfig() {
      return get('/api/admin/config');
    },
    getConfigHistory(limit) {
      return get('/api/admin/config/history', { params: { limit } });
    },
    setGeneratorConfig(generator_id, param, value) {
      return post('/api/admin/config/generator', { body: { generator_id, param, value } });
    },
    setGlobalConfig(param, value) {
      return post('/api/admin/config/global', { body: { param, value } });
    },
    // Drivers
    getDrivers() {
      return get('/api/admin/drivers');
    },
    addDriver(name) {
      return post('/api/admin/drivers', { body: { name } });
    },
    deleteDriver(name) {
      return del('/api/admin/drivers', { body: { name } });
    },
    // Personnel
    getPersonnel() {
      return get('/api/admin/personnel');
    },
    addPersonnel(name) {
      return post('/api/admin/personnel', { body: { name } });
    },
    deletePersonnel(name) {
      return del('/api/admin/personnel', { body: { name } });
    },
    assignPersonnel(user_id, personnel) {
      return post('/api/admin/personnel/assign', { body: { user_id, personnel } });
    },
    // Sync
    sync() {
      return post('/api/admin/sync');
    },
    // Audit
    getAudit(params) {
      return get('/api/admin/audit', { params });
    },
    exportAudit(params) {
      return get('/api/admin/audit/export', { params });
    },
    // Backups
    getBackups() {
      return get('/api/admin/backups');
    },
    createBackup() {
      return post('/api/admin/backup');
    },
  };

  /* ── Analytics ───────────────────────────────────────────── */
  const analytics = {
    kpi(params) {
      return get('/api/analytics/kpi', { params });
    },
    fuelTimeline(params) {
      return get('/api/analytics/fuel-timeline', { params });
    },
    motorHours(params) {
      return get('/api/analytics/motor-hours', { params });
    },
    efficiency(params) {
      return get('/api/analytics/efficiency', { params });
    },
    calendar(params) {
      return get('/api/analytics/calendar', { params });
    },
    trends(params) {
      return get('/api/analytics/trends', { params });
    },
    forecast() {
      return get('/api/analytics/forecast');
    },
  };

  /* ── Reports ─────────────────────────────────────────────── */
  const reports = {
    excelUrl(type, days, generator) {
      const params = new URLSearchParams({ type: type || 'quick', days: days || 30 });
      if (generator) params.set('generator', generator);
      return `/api/report/excel/v2?${params}`;
    },
  };

  /* ── Notifications ───────────────────────────────────────── */
  const notifications = {
    getPreferences() {
      return get('/api/notifications/preferences');
    },
    setPreference(data) {
      return post('/api/notifications/preferences', { body: data });
    },
    setQuietHours(start, end) {
      return post('/api/notifications/quiet-hours', { body: { start, end } });
    },
    test() {
      return post('/api/notifications/test');
    },
  };

  return { auth, logs, events, maintenance, fuel, schedule, shifts, users, status, actions, powerSchedule, admin, analytics, reports, notifications, request };
})();

if (typeof module !== 'undefined') module.exports = api;
