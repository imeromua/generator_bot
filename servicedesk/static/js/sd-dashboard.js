/**
 * sd-dashboard.js — Main dashboard application logic.
 *
 * Initialises the SPA after the DOM is ready:
 *   1. Checks authentication, redirects to login if absent.
 *   2. Loads the current user profile and renders the sidebar footer.
 *   3. Registers hash-based routes and renders the initial section.
 *
 * Each section (dashboard, logs, maintenance, fuel, schedule, users, profile)
 * is contained in a <div class="section-panel" id="panel-{name}"> in the HTML.
 * The router activates the correct panel and calls the matching loader function.
 */

/* ── Guard: redirect to login if not authenticated ─────────── */
if (!SD_AUTH.isAuthenticated()) {
  window.location.replace('/sd/login.html');
}

/* ── Helpers ────────────────────────────────────────────────── */

function el(id)  { return document.getElementById(id); }
function qs(sel) { return document.querySelector(sel); }

/** Show a toast message. */
function toast(msg, type = 'info') {
  const container = el('toast-container');
  if (!container) return;
  const div = document.createElement('div');
  div.className = `toast ${type}`;
  div.textContent = msg;
  container.appendChild(div);
  setTimeout(() => div.remove(), 3500);
}

/** Render a simple loader placeholder inside an element. */
function renderLoader(target) {
  target.innerHTML = '<div class="loader-center"><div class="loader"></div></div>';
}

/** Format an ISO date string to a locale-friendly representation. */
function fmtDate(iso) {
  if (!iso) return '—';
  try { return new Date(iso).toLocaleString('uk-UA', { dateStyle: 'short', timeStyle: 'short' }); }
  catch { return iso; }
}

/** Map a status string to a badge class. */
function statusBadge(status) {
  const map = {
    active: 'badge-green', running: 'badge-green', approved: 'badge-green', completed: 'badge-green',
    pending: 'badge-yellow', waiting: 'badge-yellow',
    stopped: 'badge-gray',  inactive: 'badge-gray', cancelled: 'badge-gray',
    error: 'badge-red',     failed: 'badge-red',
    maintenance: 'badge-blue',
  };
  return map[(status || '').toLowerCase()] || 'badge-gray';
}

/** Activate a section panel and deactivate all others. */
function activatePanel(name) {
  document.querySelectorAll('.section-panel').forEach(p => {
    p.classList.toggle('active', p.id === `panel-${name}`);
  });
}

/* ── Sidebar & mobile nav ────────────────────────────────────── */

function initNav() {
  // Close mobile sidebar when overlay is clicked
  const overlay = el('sidebar-overlay');
  if (overlay) overlay.addEventListener('click', closeSidebar);

  const toggle = el('menu-toggle');
  if (toggle) toggle.addEventListener('click', () => document.body.classList.toggle('sidebar-open'));
}

function closeSidebar() {
  document.body.classList.remove('sidebar-open');
}

/* ── Auth: load user profile ────────────────────────────────── */

async function loadUserProfile() {
  let user = SD_AUTH.getUser();
  if (!user) {
    try {
      user = await api.auth.me();
      SD_AUTH.saveUser(user);
    } catch (e) {
      console.error('Failed to load user profile', e);
      return;
    }
  }
  renderUserInSidebar(user);
  // Show admin-only items
  if (user.role === 'admin') {
    document.querySelectorAll('[data-admin-only]').forEach(el => el.classList.remove('hidden'));
  }
}

function renderUserInSidebar(user) {
  const nameEl = el('sidebar-user-name');
  const roleEl = el('sidebar-user-role');
  if (nameEl) nameEl.textContent = user.full_name || user.login || '';
  if (roleEl) roleEl.textContent = user.role || 'user';
}

/* ── Section loaders ─────────────────────────────────────────── */

/* ·· #dashboard ·················································· */
async function loadDashboard() {
  const panel = el('panel-dashboard');
  if (!panel) return;
  renderLoader(panel);
  try {
    const data = await api.status.current();
    panel.innerHTML = renderDashboardHTML(data);
  } catch (e) {
    panel.innerHTML = `<div class="alert alert-error">${e.message}</div>`;
  }
}

function renderDashboardHTML(data) {
  const gen = data || {};
  const genStatus = gen.status || 'unknown';
  const fuelPct   = gen.fuel_level_pct ?? gen.fuel_pct ?? '—';
  const motorH    = gen.motor_hours ?? '—';
  const running   = gen.is_running ?? false;

  return `
    <div class="section-header"><h2>Поточний стан</h2></div>
    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-label">Стан генератора</div>
        <div class="stat-value">
          <span class="badge ${statusBadge(genStatus)}">${genStatus}</span>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Рівень пального</div>
        <div class="stat-value">${fuelPct !== '—' ? fuelPct + '%' : '—'}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Моточасів</div>
        <div class="stat-value">${motorH}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Режим роботи</div>
        <div class="stat-value">${running ? '<span class="badge badge-green">Працює</span>' : '<span class="badge badge-gray">Зупинено</span>'}</div>
      </div>
    </div>
    ${gen.generators ? renderGeneratorsTable(gen.generators) : ''}
  `;
}

function renderGeneratorsTable(gens) {
  if (!gens || !gens.length) return '';
  return `
    <div class="card" style="margin-top:1rem">
      <div class="section-header"><h2>Генератори</h2></div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Назва</th><th>Стан</th><th>Паливо</th><th>Моточаси</th></tr></thead>
          <tbody>
            ${gens.map(g => `
              <tr>
                <td>${g.name || g.generator_id || '—'}</td>
                <td><span class="badge ${statusBadge(g.status)}">${g.status || '—'}</span></td>
                <td>${g.fuel_level_pct != null ? g.fuel_level_pct + '%' : '—'}</td>
                <td>${g.motor_hours ?? '—'}</td>
              </tr>`).join('')}
          </tbody>
        </table>
      </div>
    </div>`;
}

/* ·· #logs ························································ */
async function loadLogs() {
  const panel = el('panel-logs');
  if (!panel) return;
  panel.innerHTML = `
    <div class="section-header">
      <h2>Журнал подій</h2>
      <button class="btn btn-ghost" id="logs-refresh">↻ Оновити</button>
    </div>
    <div class="filters">
      <input id="logs-search" type="text" class="input" placeholder="Пошук…" style="min-width:200px">
      <select id="logs-limit">
        <option value="50">50 записів</option>
        <option value="100">100 записів</option>
        <option value="200">200 записів</option>
      </select>
    </div>
    <div id="logs-body" class="loader-center"><div class="loader"></div></div>`;

  let _logsSearchTimer = null;

  const fetchLogs = async () => {
    const body = el('logs-body');
    const search = (el('logs-search') || {}).value || '';
    const limit  = (el('logs-limit')  || {}).value || 50;
    renderLoader(body);
    try {
      const data = await api.logs.list({ limit, search });
      const items = Array.isArray(data) ? data : (data.items || data.records || []);
      if (!items.length) { body.innerHTML = '<p class="text-muted" style="padding:1rem">Записів не знайдено</p>'; return; }
      body.innerHTML = `<div class="table-wrap"><table>
        <thead><tr><th>Час</th><th>Дія</th><th>Користувач</th><th>Деталі</th></tr></thead>
        <tbody>${items.map(r => `
          <tr>
            <td class="text-sm text-muted">${fmtDate(r.created_at || r.timestamp)}</td>
            <td>${r.action || r.event_type || '—'}</td>
            <td>${r.user || r.username || r.performed_by || '—'}</td>
            <td class="text-sm">${r.details || r.description || ''}</td>
          </tr>`).join('')}
        </tbody></table></div>`;
    } catch (e) {
      body.innerHTML = `<div class="alert alert-error">${e.message}</div>`;
    }
  };

  fetchLogs();
  el('logs-refresh').addEventListener('click', fetchLogs);
  el('logs-search').addEventListener('input', () => {
    clearTimeout(_logsSearchTimer);
    _logsSearchTimer = setTimeout(fetchLogs, 400);
  });
  el('logs-limit').addEventListener('change', fetchLogs);
}

/* ·· #maintenance ·················································· */
async function loadMaintenance() {
  const panel = el('panel-maintenance');
  if (!panel) return;
  panel.innerHTML = `
    <div class="section-header">
      <h2>Технічне обслуговування</h2>
      <button class="btn btn-ghost" onclick="loadMaintenance()">↻ Оновити</button>
    </div>
    <div id="maint-body" class="loader-center"><div class="loader"></div></div>`;

  try {
    const data = await api.maintenance.list();
    const items = Array.isArray(data) ? data : (data.items || []);
    const body = el('maint-body');
    if (!items.length) { body.innerHTML = '<p class="text-muted" style="padding:1rem">Немає записів</p>'; return; }
    body.innerHTML = `<div class="table-wrap"><table>
      <thead><tr><th>Тип</th><th>Статус</th><th>Дата</th><th>Примітки</th></tr></thead>
      <tbody>${items.map(r => `
        <tr>
          <td>${r.maintenance_type || r.type || '—'}</td>
          <td><span class="badge ${statusBadge(r.status)}">${r.status || '—'}</span></td>
          <td class="text-sm text-muted">${fmtDate(r.scheduled_date || r.created_at)}</td>
          <td class="text-sm">${r.notes || ''}</td>
        </tr>`).join('')}
      </tbody></table></div>`;
  } catch (e) {
    el('maint-body').innerHTML = `<div class="alert alert-error">${e.message}</div>`;
  }
}

/* ·· #fuel ·················································· */
async function loadFuel() {
  const panel = el('panel-fuel');
  if (!panel) return;
  panel.innerHTML = `
    <div class="section-header">
      <h2>Замовлення пального</h2>
      <button class="btn btn-primary" onclick="openFuelModal()">+ Нове замовлення</button>
    </div>
    <div id="fuel-body" class="loader-center"><div class="loader"></div></div>`;

  await fetchFuelOrders();
}

async function fetchFuelOrders() {
  const body = el('fuel-body');
  if (!body) return;
  renderLoader(body);
  try {
    const data = await api.fuel.list();
    const items = Array.isArray(data) ? data : (data.items || data.orders || []);
    if (!items.length) { body.innerHTML = '<p class="text-muted" style="padding:1rem">Замовлень немає</p>'; return; }
    body.innerHTML = `<div class="table-wrap"><table>
      <thead><tr><th>ID</th><th>Об'єм (л)</th><th>Статус</th><th>Дата</th><th>Дія</th></tr></thead>
      <tbody>${items.map(r => {
        const oid = Number(r.order_id || r.id || 0);
        return `
        <tr>
          <td>${oid || '—'}</td>
          <td>${r.volume_liters ?? r.amount ?? '—'}</td>
          <td><span class="badge ${statusBadge(r.status)}">${r.status || '—'}</span></td>
          <td class="text-sm text-muted">${fmtDate(r.created_at)}</td>
          <td>
            ${r.status === 'pending' && oid ? `
              <button class="btn btn-ghost js-approve-fuel" data-order-id="${oid}"
                style="font-size:0.78rem;padding:0.2rem 0.5rem">Схвалити</button>` : ''}
          </td>
        </tr>`;
      }).join('')}
      </tbody></table></div>`;

    // Attach approve handlers via event delegation
    body.querySelectorAll('.js-approve-fuel').forEach(btn => {
      btn.addEventListener('click', () => updateFuelStatus(Number(btn.dataset.orderId), 'approved'));
    });
  } catch (e) {
    body.innerHTML = `<div class="alert alert-error">${e.message}</div>`;
  }
}

async function updateFuelStatus(orderId, newStatus) {
  try {
    await api.fuel.updateStatus({ order_id: orderId, status: newStatus });
    toast('Статус оновлено', 'success');
    fetchFuelOrders();
  } catch (e) {
    toast(e.message, 'error');
  }
}

function openFuelModal() {
  const modal = el('fuel-modal');
  if (modal) modal.classList.remove('hidden');
}
function closeFuelModal() {
  const modal = el('fuel-modal');
  if (modal) modal.classList.add('hidden');
}

async function submitFuelOrder(e) {
  e.preventDefault();
  const volume = el('fuel-volume').value;
  const notes  = el('fuel-notes').value;
  try {
    await api.fuel.create({ volume_liters: parseFloat(volume), notes });
    toast('Замовлення створено', 'success');
    closeFuelModal();
    fetchFuelOrders();
  } catch (err) {
    toast(err.message, 'error');
  }
}

/* ·· #schedule ·················································· */
async function loadSchedule() {
  const panel = el('panel-schedule');
  if (!panel) return;
  panel.innerHTML = `
    <div class="section-header">
      <h2>Розклад змін</h2>
      <button class="btn btn-ghost" onclick="loadSchedule()">↻ Оновити</button>
    </div>
    <div id="schedule-body" class="loader-center"><div class="loader"></div></div>`;

  try {
    const data = await api.schedule.list();
    const items = Array.isArray(data) ? data : (data.schedule || data.shifts || data.items || []);
    const body = el('schedule-body');
    if (!items.length) { body.innerHTML = '<p class="text-muted" style="padding:1rem">Розклад порожній</p>'; return; }
    body.innerHTML = `<div class="table-wrap"><table>
      <thead><tr><th>Дата</th><th>Час</th><th>Виконавець</th><th>Статус</th></tr></thead>
      <tbody>${items.map(r => `
        <tr>
          <td>${fmtDate(r.date || r.shift_date)}</td>
          <td>${r.start_time || ''}${r.end_time ? ' – ' + r.end_time : ''}</td>
          <td>${r.driver || r.assignee || r.full_name || '—'}</td>
          <td><span class="badge ${statusBadge(r.status)}">${r.status || '—'}</span></td>
        </tr>`).join('')}
      </tbody></table></div>`;
  } catch (e) {
    el('schedule-body').innerHTML = `<div class="alert alert-error">${e.message}</div>`;
  }
}

/* ·· #users (admin only) ·········································· */
async function loadUsers() {
  const panel = el('panel-users');
  if (!panel) return;
  panel.innerHTML = `
    <div class="section-header">
      <h2>Управління користувачами</h2>
      <button class="btn btn-ghost" onclick="loadUsers()">↻ Оновити</button>
    </div>
    <div id="users-body" class="loader-center"><div class="loader"></div></div>`;

  try {
    const data = await api.users.list();
    const items = Array.isArray(data) ? data : (data.users || data.items || []);
    const body = el('users-body');
    if (!items.length) { body.innerHTML = '<p class="text-muted" style="padding:1rem">Немає користувачів</p>'; return; }
    body.innerHTML = `<div class="table-wrap"><table>
      <thead><tr><th>Логін</th><th>Ім'я</th><th>Роль</th><th>Статус</th><th>Дії</th></tr></thead>
      <tbody>${items.map(u => {
        const uid = Number(u.user_id || 0);
        const active = u.is_active !== false;
        return `
        <tr>
          <td>${u.web_login || u.login || u.username || '—'}</td>
          <td>${u.full_name || '—'}</td>
          <td><span class="badge badge-blue">${u.role || 'user'}</span></td>
          <td><span class="badge ${active ? 'badge-green' : 'badge-red'}">${active ? 'Активний' : 'Заблоковано'}</span></td>
          <td>
            ${uid ? (active
              ? `<button class="btn btn-danger js-block-user" data-user-id="${uid}" style="font-size:0.78rem;padding:0.2rem 0.5rem">Блок</button>`
              : `<button class="btn btn-ghost js-unblock-user" data-user-id="${uid}" style="font-size:0.78rem;padding:0.2rem 0.5rem">Розблок</button>`)
              : ''}
          </td>
        </tr>`;
      }).join('')}
      </tbody></table></div>`;

    // Attach block/unblock handlers via event delegation
    body.querySelectorAll('.js-block-user').forEach(btn => {
      btn.addEventListener('click', () => blockUser(Number(btn.dataset.userId)));
    });
    body.querySelectorAll('.js-unblock-user').forEach(btn => {
      btn.addEventListener('click', () => unblockUser(Number(btn.dataset.userId)));
    });
  } catch (e) {
    el('users-body').innerHTML = `<div class="alert alert-error">${e.message}</div>`;
  }
}

async function blockUser(userId) {
  if (!confirm('Заблокувати користувача?')) return;
  try {
    await api.users.block(userId);
    toast('Заблоковано', 'success');
    loadUsers();
  } catch (e) { toast(e.message, 'error'); }
}

async function unblockUser(userId) {
  try {
    await api.users.unblock(userId);
    toast('Розблоковано', 'success');
    loadUsers();
  } catch (e) { toast(e.message, 'error'); }
}

/* ·· #profile ·················································· */
async function loadProfile() {
  const panel = el('panel-profile');
  if (!panel) return;
  const user = SD_AUTH.getUser() || await api.auth.me().catch(() => ({}));
  panel.innerHTML = `
    <div class="section-header"><h2>Профіль</h2></div>
    <div class="card" style="max-width:440px">
      <div style="margin-bottom:1rem">
        <div class="text-muted text-sm">Логін</div>
        <div class="font-bold">${user.login || '—'}</div>
      </div>
      <div style="margin-bottom:1rem">
        <div class="text-muted text-sm">Повне ім'я</div>
        <div>${user.full_name || '—'}</div>
      </div>
      <div style="margin-bottom:1.5rem">
        <div class="text-muted text-sm">Роль</div>
        <div><span class="badge badge-blue">${user.role || 'user'}</span></div>
      </div>
      <hr style="border-color:var(--border);margin-bottom:1rem">
      <h3 style="margin-bottom:0.75rem;font-size:0.95rem">Змінити пароль</h3>
      <form id="change-pw-form" onsubmit="changePassword(event)" class="flex-col gap-2">
        <div class="form-group">
          <label>Поточний пароль</label>
          <input id="pw-old" type="password" class="input" required autocomplete="current-password">
        </div>
        <div class="form-group">
          <label>Новий пароль</label>
          <input id="pw-new" type="password" class="input" required autocomplete="new-password">
        </div>
        <div id="pw-error" class="hidden"></div>
        <button type="submit" class="btn btn-primary">Зберегти</button>
      </form>
    </div>`;
}

async function changePassword(e) {
  e.preventDefault();
  const oldPw = el('pw-old').value;
  const newPw = el('pw-new').value;
  const errEl = el('pw-error');
  errEl.className = 'hidden';
  try {
    await api.auth.changePassword(oldPw, newPw);
    toast('Пароль змінено', 'success');
    el('change-pw-form').reset();
  } catch (err) {
    errEl.className = 'alert alert-error';
    errEl.textContent = err.message;
  }
}

/* ── Logout ─────────────────────────────────────────────────── */

async function doLogout() {
  if (!confirm('Вийти з системи?')) return;
  await SD_AUTH.logout(true);
}

/* ── Router setup ───────────────────────────────────────────── */

function setupRoutes() {
  router
    .on('dashboard',   () => { activatePanel('dashboard');   loadDashboard();   closeSidebar(); })
    .on('logs',        () => { activatePanel('logs');        loadLogs();        closeSidebar(); })
    .on('maintenance', () => { activatePanel('maintenance'); loadMaintenance(); closeSidebar(); })
    .on('fuel',        () => { activatePanel('fuel');        loadFuel();        closeSidebar(); })
    .on('schedule',    () => { activatePanel('schedule');    loadSchedule();    closeSidebar(); })
    .on('users',       () => { activatePanel('users');       loadUsers();       closeSidebar(); })
    .on('profile',     () => { activatePanel('profile');     loadProfile();     closeSidebar(); });
}

/* ── Bootstrap ──────────────────────────────────────────────── */

document.addEventListener('DOMContentLoaded', async () => {
  initNav();
  setupRoutes();

  // Logout button
  const logoutBtn = el('btn-logout');
  if (logoutBtn) logoutBtn.addEventListener('click', doLogout);

  // Fuel modal form
  const fuelForm = el('fuel-order-form');
  if (fuelForm) fuelForm.addEventListener('submit', submitFuelOrder);
  const fuelModalClose = el('fuel-modal-close');
  if (fuelModalClose) fuelModalClose.addEventListener('click', closeFuelModal);

  await loadUserProfile();
  router.start('dashboard');
});
