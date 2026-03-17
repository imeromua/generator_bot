/**
 * sd-dashboard.js — Main dashboard application logic for ServiceDesk.
 *
 * Sections: dashboard, events, maintenance, fuel, schedule (24-hour power),
 *           shifts (monthly), admin, analytics, reports, users, profile.
 */

/* ── Guard ────────────────────────────────────────────────────── */
if (!SD_AUTH.isAuthenticated()) {
  window.location.replace('/sd/login.html');
}

/* ── Helpers ───────────────────────────────────────────────────── */
function el(id)  { return document.getElementById(id); }
function qs(sel) { return document.querySelector(sel); }

function toast(msg, type = 'info') {
  const c = el('toast-container');
  if (!c) return;
  const d = document.createElement('div');
  d.className = 'toast ' + type;
  d.textContent = msg;
  c.appendChild(d);
  setTimeout(() => d.remove(), 3500);
}

function renderLoader(target) {
  target.innerHTML = '<div class="loader-center"><div class="loader"></div></div>';
}

function fmtDate(iso) {
  if (!iso) return '—';
  try { return new Date(iso).toLocaleString('uk-UA', { dateStyle: 'short', timeStyle: 'short' }); }
  catch { return iso; }
}

function fmtDateShort(iso) {
  if (!iso) return '—';
  try { return new Date(iso).toLocaleDateString('uk-UA', { day: 'numeric', month: 'short' }); }
  catch { return iso; }
}

function statusBadge(status) {
  const m = {
    active:'badge-green', running:'badge-green', approved:'badge-green', completed:'badge-green', on:'badge-green',
    pending:'badge-yellow', waiting:'badge-yellow', scheduled:'badge-yellow',
    stopped:'badge-gray', inactive:'badge-gray', cancelled:'badge-gray', off:'badge-gray',
    error:'badge-red', failed:'badge-red', critical:'badge-red', overdue:'badge-red',
    maintenance:'badge-blue', info:'badge-blue',
  };
  return m[(status || '').toLowerCase()] || 'badge-gray';
}

function activatePanel(name) {
  document.querySelectorAll('.section-panel').forEach(p => {
    p.classList.toggle('active', p.id === 'panel-' + name);
  });
}

function esc(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

function escAttr(s) {
  return esc(s).replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

/* ── Sidebar & mobile nav ──────────────────────────────────────── */
function initNav() {
  const overlay = el('sidebar-overlay');
  if (overlay) overlay.addEventListener('click', closeSidebar);
  const toggle = el('menu-toggle');
  if (toggle) toggle.addEventListener('click', () => document.body.classList.toggle('sidebar-open'));
}

function closeSidebar() {
  document.body.classList.remove('sidebar-open');
}

/* ── Auth: load user profile ───────────────────────────────────── */
let _currentUser = null;

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
  _currentUser = user;
  renderUserInSidebar(user);
  if (user.role === 'admin' || user.role === 'superadmin') {
    document.querySelectorAll('[data-admin-only]').forEach(el => el.classList.remove('hidden'));
  }
}

function renderUserInSidebar(user) {
  const n = el('sidebar-user-name');
  const r = el('sidebar-user-role');
  if (n) n.textContent = user.full_name || user.login || '';
  if (r) r.textContent = user.role || 'user';
}

function isAdmin() {
  return _currentUser && (_currentUser.role === 'admin' || _currentUser.role === 'superadmin');
}

/* ════════════════════════════════════════════════════════════════
   SECTION LOADERS
   ════════════════════════════════════════════════════════════════ */

/* ── #dashboard ────────────────────────────────────────────────── */
async function loadDashboard() {
  const panel = el('panel-dashboard');
  if (!panel) return;
  renderLoader(panel);
  try {
    const data = await api.status.current();
    panel.innerHTML = renderDashboardHTML(data);
  } catch (e) {
    panel.innerHTML = '<div class="alert alert-error">' + esc(e.message) + '</div>';
  }
}

function renderDashboardHTML(data) {
  const g = data || {};
  const genStatus = g.status || g.generator_status || 'unknown';
  const fuelPct   = g.fuel_level_pct ?? g.fuel_pct ?? '—';
  const motorH    = g.motor_hours ?? '—';
  const running   = g.is_running ?? false;
  const fuelL     = g.fuel_liters ?? g.fuel_level ?? '';
  const rate      = g.consumption_rate ?? '';
  const workH     = g.work_hours_today ?? '';
  const fuelDur   = g.fuel_duration_hours ?? '';
  const activeGen = g.active_generator ?? '';
  const currentShift = g.current_shift ?? '';

  let html = '<div class="section-header"><h2>Поточний стан</h2></div>';
  html += '<div class="stats-grid">';
  html += statCard('Генератор', esc(genStatus), activeGen ? 'Активний: ' + esc(String(activeGen)) : '');
  html += statCard('Рівень пального', fuelPct !== '—' ? fuelPct + '%' : '—', fuelL ? esc(String(fuelL)) + ' л' : '');
  html += statCard('Моточаси', motorH, '');
  html += statCard('Режим', running ? '🟢 Працює' : '⚪ Зупинено', '');
  if (rate) html += statCard('Витрата', esc(String(rate)) + ' л/год', '');
  if (workH) html += statCard('Відпрацьовано', esc(String(workH)) + ' год', 'Сьогодні');
  if (fuelDur) html += statCard('Запас палива', esc(String(fuelDur)) + ' год', '');
  if (currentShift) html += statCard('Зміна', esc(String(currentShift)), '');
  html += '</div>';

  if (g.generators) html += renderGeneratorsTable(g.generators);
  return html;
}

function statCard(label, value, sub) {
  return '<div class="stat-card"><div class="stat-label">' + esc(label) + '</div><div class="stat-value">' + value + '</div>' + (sub ? '<div class="stat-sub">' + sub + '</div>' : '') + '</div>';
}

function renderGeneratorsTable(gens) {
  if (!gens || !gens.length) return '';
  return '<div class="card" style="margin-top:1rem"><div class="section-header"><h2>Генератори</h2></div><div class="table-wrap"><table>' +
    '<thead><tr><th>Назва</th><th>Стан</th><th>Паливо</th><th>Моточаси</th></tr></thead><tbody>' +
    gens.map(g => '<tr><td>' + esc(g.name || g.generator_id || '—') + '</td><td><span class="badge ' + statusBadge(g.status) + '">' + esc(g.status || '—') + '</span></td><td>' + (g.fuel_level_pct != null ? g.fuel_level_pct + '%' : '—') + '</td><td>' + (g.motor_hours ?? '—') + '</td></tr>').join('') +
    '</tbody></table></div></div>';
}

/* ── #events ───────────────────────────────────────────────────── */
async function loadEvents() {
  const panel = el('panel-events');
  if (!panel) return;
  panel.innerHTML =
    '<div class="section-header"><h2>Журнал подій</h2><button class="btn btn-ghost" id="events-refresh">↻ Оновити</button></div>' +
    '<div class="filters"><input id="events-limit-sel" type="number" class="input" value="50" min="10" max="500" style="width:80px" title="Кількість записів"></div>' +
    '<div id="events-body" class="loader-center"><div class="loader"></div></div>';

  const fetchEvents = async () => {
    const body = el('events-body');
    const limit = (el('events-limit-sel') || {}).value || 50;
    renderLoader(body);
    try {
      const data = await api.events.list({ limit });
      const items = Array.isArray(data) ? data : (data.events || data.items || []);
      if (!items.length) { body.innerHTML = '<p class="text-muted" style="padding:1rem">Подій не знайдено</p>'; return; }
      body.innerHTML = '<div class="table-wrap"><table><thead><tr><th>Час</th><th>Подія</th><th>Деталі</th></tr></thead><tbody>' +
        items.map(r => '<tr><td class="text-sm text-muted">' + fmtDate(r.created_at || r.timestamp) + '</td><td>' + esc(r.event_type || r.action || r.type || '—') + '</td><td class="text-sm">' + esc(r.details || r.description || r.message || '') + '</td></tr>').join('') +
        '</tbody></table></div>';
    } catch (e) {
      body.innerHTML = '<div class="alert alert-error">' + esc(e.message) + '</div>';
    }
  };

  fetchEvents();
  el('events-refresh').addEventListener('click', fetchEvents);
  el('events-limit-sel').addEventListener('change', fetchEvents);
}

/* ── #maintenance ──────────────────────────────────────────────── */
async function loadMaintenance() {
  const panel = el('panel-maintenance');
  if (!panel) return;
  panel.innerHTML =
    '<div class="section-header"><h2>Технічне обслуговування</h2><button class="btn btn-ghost" id="maint-refresh">↻ Оновити</button></div>' +
    '<div id="maint-body" class="loader-center"><div class="loader"></div></div>';

  const fetchMaint = async () => {
    const body = el('maint-body');
    renderLoader(body);
    try {
      const data = await api.maintenance.list();
      // data may be object with status fields or array of records
      if (data && (data.oil_change || data.spark_plugs || data.routine)) {
        body.innerHTML = renderMaintenanceStatus(data);
      } else {
        const items = Array.isArray(data) ? data : (data.items || data.records || []);
        if (!items.length) { body.innerHTML = '<p class="text-muted" style="padding:1rem">Немає записів</p>'; return; }
        body.innerHTML = '<div class="table-wrap"><table><thead><tr><th>Тип</th><th>Статус</th><th>Дата</th><th>Примітки</th></tr></thead><tbody>' +
          items.map(r => '<tr><td>' + esc(r.maintenance_type || r.type || '—') + '</td><td><span class="badge ' + statusBadge(r.status) + '">' + esc(r.status || '—') + '</span></td><td class="text-sm text-muted">' + fmtDate(r.scheduled_date || r.created_at) + '</td><td class="text-sm">' + esc(r.notes || '') + '</td></tr>').join('') +
          '</tbody></table></div>';
      }
    } catch (e) {
      body.innerHTML = '<div class="alert alert-error">' + esc(e.message) + '</div>';
    }
  };

  fetchMaint();
  el('maint-refresh').addEventListener('click', fetchMaint);
}

function renderMaintenanceStatus(data) {
  function bar(item, label) {
    if (!item) return '';
    const pct = item.progress_pct ?? (item.current && item.interval && item.interval > 0 ? Math.min(100, Math.round(item.current / item.interval * 100)) : 0);
    const color = pct >= 90 ? 'red' : pct >= 70 ? 'yellow' : 'green';
    return '<div class="card" style="margin-bottom:0.75rem"><div class="flex justify-between items-center" style="margin-bottom:0.5rem"><span class="font-bold">' + esc(label) + '</span><span class="text-sm text-muted">' + (item.current ?? '—') + ' / ' + (item.interval ?? '—') + ' год</span></div><div class="progress-bar"><div class="progress-fill ' + color + '" style="width:' + pct + '%"></div></div></div>';
  }
  let html = '';
  html += bar(data.oil_change, 'Заміна масла');
  html += bar(data.spark_plugs, 'Свічки запалювання');
  html += bar(data.routine, 'Планове ТО');
  if (data.history && data.history.length) {
    html += '<h3 style="margin:1rem 0 0.5rem">Історія</h3><div class="table-wrap"><table><thead><tr><th>Тип</th><th>Дата</th><th>Примітки</th></tr></thead><tbody>' +
      data.history.map(r => '<tr><td>' + esc(r.type || '—') + '</td><td class="text-sm text-muted">' + fmtDate(r.created_at) + '</td><td class="text-sm">' + esc(r.notes || '') + '</td></tr>').join('') +
      '</tbody></table></div>';
  }
  return html;
}

/* ── #fuel ──────────────────────────────────────────────────────── */
async function loadFuel() {
  const panel = el('panel-fuel');
  if (!panel) return;
  panel.innerHTML =
    '<div class="section-header"><h2>Замовлення пального</h2><button class="btn btn-primary" id="fuel-add-btn">+ Нове замовлення</button></div>' +
    '<div id="fuel-body" class="loader-center"><div class="loader"></div></div>' +
    '<div id="fuel-modal" class="modal-backdrop hidden"><div class="modal"><div class="modal-header"><h3>Нове замовлення пального</h3><button class="modal-close" id="fuel-modal-close" aria-label="Закрити">&times;</button></div><div class="modal-body"><form id="fuel-order-form" class="flex-col gap-4"><div class="form-group"><label for="fuel-volume">Об\'єм (літри)</label><input id="fuel-volume" type="number" min="1" step="0.5" class="input" placeholder="0" required></div><div class="form-group"><label for="fuel-notes">Примітки</label><textarea id="fuel-notes" class="input" rows="3" placeholder="Необов\'язково"></textarea></div><div style="display:flex;gap:0.5rem;justify-content:flex-end"><button type="button" class="btn btn-ghost" id="fuel-cancel-btn">Скасувати</button><button type="submit" class="btn btn-primary">Замовити</button></div></form></div></div></div>';

  el('fuel-add-btn').addEventListener('click', openFuelModal);
  el('fuel-modal-close').addEventListener('click', closeFuelModal);
  el('fuel-cancel-btn').addEventListener('click', closeFuelModal);
  el('fuel-order-form').addEventListener('submit', submitFuelOrder);

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
    body.innerHTML = '<div class="table-wrap"><table><thead><tr><th>ID</th><th>Об\'єм (л)</th><th>Статус</th><th>Дата</th><th>Дія</th></tr></thead><tbody>' +
      items.map(r => {
        const oid = Number(r.order_id || r.id || 0);
        return '<tr><td>' + (oid || '—') + '</td><td>' + (r.volume_liters ?? r.amount ?? '—') + '</td><td><span class="badge ' + statusBadge(r.status) + '">' + esc(r.status || '—') + '</span></td><td class="text-sm text-muted">' + fmtDate(r.created_at) + '</td><td>' +
          (r.status === 'pending' && oid ? '<button class="btn btn-ghost js-approve-fuel" data-oid="' + oid + '" style="font-size:0.78rem;padding:0.2rem 0.5rem">Схвалити</button>' : '') + '</td></tr>';
      }).join('') + '</tbody></table></div>';

    body.querySelectorAll('.js-approve-fuel').forEach(btn => {
      btn.addEventListener('click', () => updateFuelStatus(Number(btn.dataset.oid), 'approved'));
    });
  } catch (e) {
    body.innerHTML = '<div class="alert alert-error">' + esc(e.message) + '</div>';
  }
}

async function updateFuelStatus(orderId, newStatus) {
  try {
    await api.fuel.updateStatus({ order_id: orderId, status: newStatus });
    toast('Статус оновлено', 'success');
    fetchFuelOrders();
  } catch (e) { toast(e.message, 'error'); }
}

function openFuelModal()  { const m = el('fuel-modal'); if (m) m.classList.remove('hidden'); }
function closeFuelModal() { const m = el('fuel-modal'); if (m) m.classList.add('hidden'); }

async function submitFuelOrder(e) {
  e.preventDefault();
  const volume = el('fuel-volume').value;
  const notes  = el('fuel-notes').value;
  try {
    await api.fuel.create({ volume_liters: parseFloat(volume), notes });
    toast('Замовлення створено', 'success');
    closeFuelModal();
    el('fuel-order-form').reset();
    fetchFuelOrders();
  } catch (err) { toast(err.message, 'error'); }
}

/* ── #schedule (24-hour power schedule) ────────────────────────── */
let _scheduleDate = new Date().toISOString().slice(0, 10);

async function loadSchedule() {
  const panel = el('panel-schedule');
  if (!panel) return;
  panel.innerHTML =
    '<div class="section-header"><h2>Графік електропостачання</h2></div>' +
    '<div class="flex items-center gap-2" style="margin-bottom:1rem">' +
      '<button class="btn btn-ghost" id="sched-prev">◀</button>' +
      '<span id="sched-date" class="font-bold">' + esc(_scheduleDate) + '</span>' +
      '<button class="btn btn-ghost" id="sched-next">▶</button>' +
      '<button class="btn btn-ghost" id="sched-today" style="margin-left:0.5rem">Сьогодні</button>' +
    '</div>' +
    '<div id="sched-body" class="loader-center"><div class="loader"></div></div>' +
    '<div id="sched-summary" class="text-sm text-muted" style="margin-top:0.75rem"></div>';

  const nav = (dir) => {
    const d = new Date(_scheduleDate);
    d.setDate(d.getDate() + dir);
    _scheduleDate = d.toISOString().slice(0, 10);
    el('sched-date').textContent = _scheduleDate;
    fetchSchedule();
  };
  el('sched-prev').addEventListener('click', () => nav(-1));
  el('sched-next').addEventListener('click', () => nav(1));
  el('sched-today').addEventListener('click', () => {
    _scheduleDate = new Date().toISOString().slice(0, 10);
    el('sched-date').textContent = _scheduleDate;
    fetchSchedule();
  });

  fetchSchedule();
}

async function fetchSchedule() {
  const body = el('sched-body');
  if (!body) return;
  renderLoader(body);
  try {
    const data = await api.powerSchedule.get(_scheduleDate);
    const hours = data.hours || data.schedule || data;
    if (!hours || typeof hours !== 'object') {
      body.innerHTML = '<p class="text-muted">Немає даних</p>';
      return;
    }

    const isArr = Array.isArray(hours);
    let onCount = 0;
    let html = '<div class="hour-grid">';
    for (let h = 0; h < 24; h++) {
      const val = isArr ? hours[h] : hours[String(h)];
      const isOn = val === 1 || val === true || val === 'on';
      if (isOn) onCount++;
      const cls = isOn ? 'on' : 'off';
      const editable = isAdmin() ? ' editable' : '';
      html += '<div class="hour-cell ' + cls + editable + '" data-hour="' + h + '">' + String(h).padStart(2, '0') + ':00</div>';
    }
    html += '</div>';
    body.innerHTML = html;

    const summary = el('sched-summary');
    if (summary) summary.textContent = '🟢 Світло: ' + onCount + ' год | 🔴 Без світла: ' + (24 - onCount) + ' год';

    if (isAdmin()) {
      body.querySelectorAll('.hour-cell.editable').forEach(cell => {
        cell.addEventListener('click', async () => {
          const hour = Number(cell.dataset.hour);
          try {
            await api.powerSchedule.toggle(_scheduleDate, hour);
            toast('Графік оновлено', 'success');
            fetchSchedule();
          } catch (err) { toast(err.message, 'error'); }
        });
      });
    }
  } catch (e) {
    body.innerHTML = '<div class="alert alert-error">' + esc(e.message) + '</div>';
  }
}

/* ── #shifts (monthly shift schedule) ──────────────────────────── */
async function loadShifts() {
  const panel = el('panel-shifts');
  if (!panel) return;
  panel.innerHTML =
    '<div class="section-header"><h2>Розклад змін</h2><button class="btn btn-ghost" id="shifts-refresh">↻ Оновити</button></div>' +
    '<div id="shifts-body" class="loader-center"><div class="loader"></div></div>';

  const fetchShifts = async () => {
    const body = el('shifts-body');
    renderLoader(body);
    try {
      const data = await api.shifts.list();
      const items = Array.isArray(data) ? data : (data.schedule || data.shifts || data.items || []);
      if (!items.length) { body.innerHTML = '<p class="text-muted" style="padding:1rem">Розклад порожній</p>'; return; }
      body.innerHTML = '<div class="table-wrap"><table><thead><tr><th>Дата</th><th>Час</th><th>Виконавець</th><th>Статус</th></tr></thead><tbody>' +
        items.map(r => '<tr><td>' + fmtDate(r.date || r.shift_date) + '</td><td>' + (r.start_time || '') + (r.end_time ? ' – ' + r.end_time : '') + '</td><td>' + esc(r.driver || r.assignee || r.full_name || '—') + '</td><td><span class="badge ' + statusBadge(r.status) + '">' + esc(r.status || '—') + '</span></td></tr>').join('') +
        '</tbody></table></div>';
    } catch (e) {
      body.innerHTML = '<div class="alert alert-error">' + esc(e.message) + '</div>';
    }
  };

  fetchShifts();
  el('shifts-refresh').addEventListener('click', fetchShifts);
}

/* ── #admin ─────────────────────────────────────────────────────── */
async function loadAdmin() {
  const panel = el('panel-admin');
  if (!panel) return;
  panel.innerHTML =
    '<div class="section-header"><h2>Адміністрування</h2></div>' +
    '<div class="panel-tabs">' +
      '<button class="panel-tab active" data-atab="generators">Генератори</button>' +
      '<button class="panel-tab" data-atab="drivers">Водії</button>' +
      '<button class="panel-tab" data-atab="personnel">Персонал</button>' +
      '<button class="panel-tab" data-atab="settings">Налаштування</button>' +
      '<button class="panel-tab" data-atab="sync">Синхронізація</button>' +
      '<button class="panel-tab" data-atab="backups">Резервні копії</button>' +
      '<button class="panel-tab" data-atab="audit">Аудит</button>' +
    '</div>' +
    '<div id="admin-body"></div>';

  panel.querySelectorAll('.panel-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      panel.querySelectorAll('.panel-tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      loadAdminTab(tab.dataset.atab);
    });
  });

  loadAdminTab('generators');
}

async function loadAdminTab(tab) {
  const body = el('admin-body');
  if (!body) return;
  renderLoader(body);

  try {
    switch (tab) {
      case 'generators': await loadAdminGenerators(body); break;
      case 'drivers':    await loadAdminDrivers(body); break;
      case 'personnel':  await loadAdminPersonnel(body); break;
      case 'settings':   await loadAdminSettings(body); break;
      case 'sync':       await loadAdminSync(body); break;
      case 'backups':    await loadAdminBackups(body); break;
      case 'audit':      await loadAdminAudit(body); break;
      default: body.innerHTML = '<p class="text-muted">Невідома вкладка</p>';
    }
  } catch (e) {
    body.innerHTML = '<div class="alert alert-error">' + esc(e.message) + '</div>';
  }
}

async function loadAdminGenerators(body) {
  const data = await api.status.generators();
  const gens = Array.isArray(data) ? data : (data.generators || []);
  let html = '<div class="stats-grid" style="margin-bottom:1rem">';
  gens.forEach(g => {
    html += '<div class="stat-card"><div class="stat-label">' + esc(g.name || g.generator_id || '—') + '</div><div class="stat-value"><span class="badge ' + statusBadge(g.status) + '">' + esc(g.status || '—') + '</span></div><div class="stat-sub">Паливо: ' + (g.fuel_level_pct ?? '—') + '% | Моточаси: ' + (g.motor_hours ?? '—') + '</div></div>';
  });
  html += '</div>';

  html += '<div class="card" style="margin-bottom:1rem"><h3 style="margin-bottom:0.75rem">Переключити генератор</h3><div class="flex gap-2"><button class="btn btn-primary" id="switch-main">🔋 Основний</button><button class="btn btn-danger" id="switch-emergency">⚠️ Аварійний</button></div></div>';

  html += '<div class="card"><h3 style="margin-bottom:0.75rem">Встановити рівень палива</h3><div class="flex gap-2 items-center"><input id="admin-fuel-val" type="number" class="input" style="width:120px" min="0" step="0.5" placeholder="Літри"><button class="btn btn-primary" id="admin-fuel-set">Зберегти</button></div></div>';

  body.innerHTML = html;

  el('switch-main').addEventListener('click', async () => {
    try { await api.actions.switchGenerator('main'); toast('Переключено на основний', 'success'); loadAdminTab('generators'); }
    catch (e) { toast(e.message, 'error'); }
  });
  el('switch-emergency').addEventListener('click', async () => {
    if (!confirm('Переключити на аварійний генератор?')) return;
    try { await api.actions.switchGenerator('emergency'); toast('Переключено на аварійний', 'success'); loadAdminTab('generators'); }
    catch (e) { toast(e.message, 'error'); }
  });
  el('admin-fuel-set').addEventListener('click', async () => {
    const val = parseFloat(el('admin-fuel-val').value);
    if (isNaN(val) || val < 0) { toast('Введіть коректне значення', 'error'); return; }
    try { await api.actions.setFuel(val); toast('Рівень палива оновлено', 'success'); }
    catch (e) { toast(e.message, 'error'); }
  });
}

async function loadAdminDrivers(body) {
  const data = await api.admin.getDrivers();
  const items = Array.isArray(data) ? data : (data.drivers || []);
  let html = '<div class="flex gap-2 items-center" style="margin-bottom:1rem"><input id="add-driver-name" type="text" class="input" placeholder="Ім\'я водія" style="max-width:300px"><button class="btn btn-primary" id="add-driver-btn">Додати</button></div>';
  if (items.length) {
    html += '<div class="table-wrap"><table><thead><tr><th>Ім\'я</th><th>Дія</th></tr></thead><tbody>' +
      items.map(d => {
        const name = typeof d === 'string' ? d : (d.name || d.driver_name || '—');
        return '<tr><td>' + esc(name) + '</td><td><button class="btn btn-danger js-del-driver" data-name="' + escAttr(name) + '" style="font-size:0.78rem;padding:0.2rem 0.5rem">Видалити</button></td></tr>';
      }).join('') + '</tbody></table></div>';
  } else {
    html += '<p class="text-muted">Водіїв не знайдено</p>';
  }
  body.innerHTML = html;

  el('add-driver-btn').addEventListener('click', async () => {
    const name = el('add-driver-name').value.trim();
    if (!name) return;
    try { await api.admin.addDriver(name); toast('Водія додано', 'success'); el('add-driver-name').value = ''; loadAdminTab('drivers'); }
    catch (e) { toast(e.message, 'error'); }
  });
  body.querySelectorAll('.js-del-driver').forEach(btn => {
    btn.addEventListener('click', async () => {
      if (!confirm('Видалити водія ' + btn.dataset.name + '?')) return;
      try { await api.admin.deleteDriver(btn.dataset.name); toast('Видалено', 'success'); loadAdminTab('drivers'); }
      catch (e) { toast(e.message, 'error'); }
    });
  });
}

async function loadAdminPersonnel(body) {
  const data = await api.admin.getPersonnel();
  const items = Array.isArray(data) ? data : (data.personnel || []);
  let html = '<div class="flex gap-2 items-center" style="margin-bottom:1rem"><input id="add-person-name" type="text" class="input" placeholder="Ім\'я працівника" style="max-width:300px"><button class="btn btn-primary" id="add-person-btn">Додати</button></div>';
  if (items.length) {
    html += '<div class="table-wrap"><table><thead><tr><th>Ім\'я</th><th>Дія</th></tr></thead><tbody>' +
      items.map(p => {
        const name = typeof p === 'string' ? p : (p.name || p.full_name || '—');
        return '<tr><td>' + esc(name) + '</td><td><button class="btn btn-danger js-del-person" data-name="' + escAttr(name) + '" style="font-size:0.78rem;padding:0.2rem 0.5rem">Видалити</button></td></tr>';
      }).join('') + '</tbody></table></div>';
  } else {
    html += '<p class="text-muted">Персонал не знайдено</p>';
  }
  body.innerHTML = html;

  el('add-person-btn').addEventListener('click', async () => {
    const name = el('add-person-name').value.trim();
    if (!name) return;
    try { await api.admin.addPersonnel(name); toast('Працівника додано', 'success'); el('add-person-name').value = ''; loadAdminTab('personnel'); }
    catch (e) { toast(e.message, 'error'); }
  });
  body.querySelectorAll('.js-del-person').forEach(btn => {
    btn.addEventListener('click', async () => {
      if (!confirm('Видалити працівника ' + btn.dataset.name + '?')) return;
      try { await api.admin.deletePersonnel(btn.dataset.name); toast('Видалено', 'success'); loadAdminTab('personnel'); }
      catch (e) { toast(e.message, 'error'); }
    });
  });
}

async function loadAdminSettings(body) {
  const cfg = await api.admin.getConfig();
  const history = await api.admin.getConfigHistory(20).catch(() => []);
  const items = Array.isArray(history) ? history : (history.items || history.records || []);

  let html = '<div class="card" style="margin-bottom:1rem"><h3 style="margin-bottom:0.75rem">Параметри генераторів</h3>';
  if (cfg.generators) {
    (Array.isArray(cfg.generators) ? cfg.generators : [cfg.generators]).forEach(g => {
      html += '<div class="flex justify-between items-center" style="padding:0.5rem 0;border-bottom:1px solid var(--border)"><span>' + esc(g.name || g.generator_id || '—') + '</span><span class="text-muted text-sm">Витрата: ' + (g.consumption_rate ?? '—') + ' л/год</span></div>';
    });
  }
  if (cfg.fuel_price != null) {
    html += '<div style="margin-top:0.75rem"><span class="text-muted text-sm">Ціна палива:</span> <span class="font-bold">' + cfg.fuel_price + ' грн/л</span></div>';
  }
  html += '</div>';

  if (items.length) {
    html += '<div class="card"><h3 style="margin-bottom:0.75rem">Історія змін</h3><div class="table-wrap"><table><thead><tr><th>Час</th><th>Параметр</th><th>Значення</th><th>Ким</th></tr></thead><tbody>' +
      items.map(r => '<tr><td class="text-sm text-muted">' + fmtDate(r.created_at || r.timestamp) + '</td><td>' + esc(r.param || r.parameter || '—') + '</td><td>' + esc(String(r.value ?? r.new_value ?? '—')) + '</td><td class="text-sm">' + esc(r.user || r.changed_by || '—') + '</td></tr>').join('') +
      '</tbody></table></div></div>';
  }
  body.innerHTML = html;
}

async function loadAdminSync(body) {
  body.innerHTML = '<div class="card"><h3 style="margin-bottom:0.75rem">Синхронізація з Google Sheets</h3><p class="text-muted text-sm" style="margin-bottom:1rem">Синхронізація даних з підключеними Google таблицями.</p><button class="btn btn-primary" id="do-sync">🔄 Синхронізувати</button><div id="sync-result" style="margin-top:1rem"></div></div>';
  el('do-sync').addEventListener('click', async () => {
    el('do-sync').disabled = true;
    try {
      const res = await api.admin.sync();
      el('sync-result').innerHTML = '<div class="alert alert-success">Синхронізацію завершено' + (res.message ? ': ' + esc(res.message) : '') + '</div>';
    } catch (e) {
      el('sync-result').innerHTML = '<div class="alert alert-error">' + esc(e.message) + '</div>';
    } finally { el('do-sync').disabled = false; }
  });
}

async function loadAdminBackups(body) {
  const data = await api.admin.getBackups();
  const items = Array.isArray(data) ? data : (data.backups || data.items || []);
  let html = '<div class="flex gap-2 items-center" style="margin-bottom:1rem"><button class="btn btn-primary" id="create-backup">💾 Створити резервну копію</button></div>';
  if (items.length) {
    html += '<div class="table-wrap"><table><thead><tr><th>Файл</th><th>Дата</th><th>Розмір</th></tr></thead><tbody>' +
      items.map(b => '<tr><td>' + esc(b.filename || b.name || '—') + '</td><td class="text-sm text-muted">' + fmtDate(b.created_at) + '</td><td class="text-sm">' + (b.size ? esc(String(b.size)) : '—') + '</td></tr>').join('') +
      '</tbody></table></div>';
  } else {
    html += '<p class="text-muted">Резервних копій немає</p>';
  }
  body.innerHTML = html;

  el('create-backup').addEventListener('click', async () => {
    el('create-backup').disabled = true;
    try { await api.admin.createBackup(); toast('Резервну копію створено', 'success'); loadAdminTab('backups'); }
    catch (e) { toast(e.message, 'error'); }
    finally { el('create-backup').disabled = false; }
  });
}

async function loadAdminAudit(body) {
  renderLoader(body);
  const data = await api.admin.getAudit({ limit: 100 });
  const items = Array.isArray(data) ? data : (data.items || data.records || []);
  if (!items.length) { body.innerHTML = '<p class="text-muted" style="padding:1rem">Записів аудиту немає</p>'; return; }
  body.innerHTML = '<div class="table-wrap"><table><thead><tr><th>Час</th><th>Дія</th><th>Користувач</th><th>Деталі</th></tr></thead><tbody>' +
    items.map(r => '<tr><td class="text-sm text-muted">' + fmtDate(r.created_at || r.timestamp) + '</td><td>' + esc(r.action || r.event_type || '—') + '</td><td>' + esc(r.user || r.username || r.performed_by || '—') + '</td><td class="text-sm">' + esc(r.details || r.description || '') + '</td></tr>').join('') +
    '</tbody></table></div>';
}

/* ── #analytics ─────────────────────────────────────────────────── */
async function loadAnalytics() {
  const panel = el('panel-analytics');
  if (!panel) return;
  panel.innerHTML =
    '<div class="section-header"><h2>Аналітика</h2></div>' +
    '<div class="flex gap-2" style="margin-bottom:1rem">' +
      '<button class="btn btn-ghost anal-period active" data-days="7">7 днів</button>' +
      '<button class="btn btn-ghost anal-period" data-days="14">14 днів</button>' +
      '<button class="btn btn-ghost anal-period" data-days="30">30 днів</button>' +
      '<button class="btn btn-ghost anal-period" data-days="90">90 днів</button>' +
    '</div>' +
    '<div id="analytics-body" class="loader-center"><div class="loader"></div></div>';

  panel.querySelectorAll('.anal-period').forEach(btn => {
    btn.addEventListener('click', () => {
      panel.querySelectorAll('.anal-period').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      fetchAnalytics(Number(btn.dataset.days));
    });
  });

  fetchAnalytics(7);
}

async function fetchAnalytics(days) {
  const body = el('analytics-body');
  if (!body) return;
  renderLoader(body);
  try {
    const [kpi, trends] = await Promise.all([
      api.analytics.kpi({ days }),
      api.analytics.trends({ days }).catch(() => null),
    ]);

    let html = '<div class="stats-grid" style="margin-bottom:1.5rem">';
    if (kpi) {
      html += statCard('Моточаси', kpi.total_motor_hours ?? '—', '');
      html += statCard('Сер. год/день', kpi.avg_hours_per_day ?? '—', '');
      html += statCard('Витрата л/год', kpi.fuel_consumption_rate ?? '—', '');
      html += statCard('Витрати (грн)', kpi.total_fuel_cost ?? '—', '');
      html += statCard('Ефективність', kpi.efficiency_pct != null ? kpi.efficiency_pct + '%' : '—', '');
      html += statCard('Спожито палива', kpi.total_fuel_consumed ?? '—', 'літрів');
    }
    html += '</div>';

    if (trends && Array.isArray(trends.insights || trends)) {
      const tList = trends.insights || trends;
      html += '<div class="card"><h3 style="margin-bottom:0.75rem">Тренди</h3>';
      tList.forEach(t => {
        const icon = t.direction === 'up' ? '↗' : t.direction === 'down' ? '↘' : '→';
        html += '<div style="padding:0.5rem 0;border-bottom:1px solid var(--border)"><span style="font-size:1.2rem;margin-right:0.5rem">' + icon + '</span>' + esc(t.description || t.text || t.message || '—') + '</div>';
      });
      html += '</div>';
    }

    body.innerHTML = html;
  } catch (e) {
    body.innerHTML = '<div class="alert alert-error">' + esc(e.message) + '</div>';
  }
}

/* ── #reports ───────────────────────────────────────────────────── */
async function loadReports() {
  const panel = el('panel-reports');
  if (!panel) return;
  panel.innerHTML =
    '<div class="section-header"><h2>Звіти Excel</h2></div>' +
    '<div class="card">' +
      '<div class="form-group" style="margin-bottom:1rem"><label>Тип звіту</label><select id="report-type" class="input" style="width:auto">' +
        '<option value="quick">Швидкий</option><option value="detailed">Детальний</option><option value="personnel">Персонал</option><option value="technical">Технічний</option><option value="financial">Фінансовий</option>' +
      '</select></div>' +
      '<div class="form-group" style="margin-bottom:1rem"><label>Період (днів)</label><select id="report-days" class="input" style="width:auto">' +
        '<option value="7">7 днів</option><option value="14">14 днів</option><option value="30" selected>30 днів</option><option value="60">60 днів</option><option value="90">90 днів</option>' +
      '</select></div>' +
      '<div class="form-group" style="margin-bottom:1rem"><label>Генератор</label><select id="report-gen" class="input" style="width:auto">' +
        '<option value="">Усі</option><option value="main">Основний</option><option value="emergency">Аварійний</option>' +
      '</select></div>' +
      '<button class="btn btn-primary" id="download-report">📥 Завантажити</button>' +
    '</div>';

  el('download-report').addEventListener('click', () => {
    const type = el('report-type').value;
    const days = el('report-days').value;
    const gen  = el('report-gen').value;
    const url = api.reports.excelUrl(type, days, gen);
    const token = SD_AUTH.getAccessToken();
    // Fetch with auth header and trigger download via blob URL
    fetch(url, { headers: token ? { 'Authorization': 'Bearer ' + token } : {} })
      .then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.blob(); })
      .then(blob => { const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'report.xlsx'; a.click(); URL.revokeObjectURL(a.href); })
      .catch(e => toast(e.message, 'error'));
  });
}

/* ── #users ──────────────────────────────────────────────────────── */
async function loadUsers() {
  const panel = el('panel-users');
  if (!panel) return;
  panel.innerHTML =
    '<div class="section-header"><h2>Управління користувачами</h2><button class="btn btn-ghost" id="users-refresh">↻ Оновити</button></div>' +
    '<div class="filters">' +
      '<input id="users-search" type="text" class="input" placeholder="Пошук…" style="min-width:180px">' +
      '<select id="users-role-filter" class="input" style="width:auto"><option value="">Усі ролі</option><option value="superadmin">Superadmin</option><option value="admin">Admin</option><option value="operator">Operator</option><option value="viewer">Viewer</option><option value="user">User</option></select>' +
      '<select id="users-status-filter" class="input" style="width:auto"><option value="">Усі статуси</option><option value="active">Активні</option><option value="blocked">Заблоковані</option></select>' +
    '</div>' +
    '<div id="users-body" class="loader-center"><div class="loader"></div></div>';

  let _usersTimer = null;
  const fetchUsers = async () => {
    const body = el('users-body');
    renderLoader(body);
    const params = {};
    const search = (el('users-search') || {}).value;
    const role = (el('users-role-filter') || {}).value;
    const status = (el('users-status-filter') || {}).value;
    if (search) params.search = search;
    if (role) params.role = role;
    if (status) params.status = status;
    try {
      const data = await api.users.list(params);
      const items = Array.isArray(data) ? data : (data.users || data.items || []);
      if (!items.length) { body.innerHTML = '<p class="text-muted" style="padding:1rem">Немає користувачів</p>'; return; }
      body.innerHTML = '<div class="table-wrap"><table><thead><tr><th>Логін</th><th>Ім\'я</th><th>Роль</th><th>Статус</th><th>Дії</th></tr></thead><tbody>' +
        items.map(u => {
          const uid = Number(u.user_id || 0);
          const active = u.is_active !== false && !u.blocked_at;
          return '<tr><td>' + esc(u.web_login || u.login || u.username || '—') + '</td><td>' + esc(u.full_name || '—') + '</td>' +
            '<td><select class="input js-role-sel" data-uid="' + uid + '" style="padding:0.2rem;font-size:0.78rem;width:auto">' +
              ['user','viewer','operator','admin','superadmin'].map(r => '<option value="' + r + '"' + (u.role === r ? ' selected' : '') + '>' + r + '</option>').join('') +
            '</select></td>' +
            '<td><span class="badge ' + (active ? 'badge-green' : 'badge-red') + '">' + (active ? 'Активний' : 'Заблоковано') + '</span></td>' +
            '<td class="flex gap-2">' +
              (uid ? (active
                ? '<button class="btn btn-danger js-block-user" data-uid="' + uid + '" style="font-size:0.78rem;padding:0.2rem 0.5rem">Блок</button>'
                : '<button class="btn btn-ghost js-unblock-user" data-uid="' + uid + '" style="font-size:0.78rem;padding:0.2rem 0.5rem">Розблок</button>')
              : '') +
              (uid ? '<button class="btn btn-danger js-del-user" data-uid="' + uid + '" style="font-size:0.78rem;padding:0.2rem 0.5rem">🗑</button>' : '') +
            '</td></tr>';
        }).join('') + '</tbody></table></div>';

      body.querySelectorAll('.js-role-sel').forEach(sel => {
        sel.addEventListener('change', async () => {
          try { await api.users.updateRole(Number(sel.dataset.uid), sel.value); toast('Роль оновлено', 'success'); }
          catch (e) { toast(e.message, 'error'); fetchUsers(); }
        });
      });
      body.querySelectorAll('.js-block-user').forEach(btn => {
        btn.addEventListener('click', async () => {
          if (!confirm('Заблокувати?')) return;
          try { await api.users.block(Number(btn.dataset.uid)); toast('Заблоковано', 'success'); fetchUsers(); }
          catch (e) { toast(e.message, 'error'); }
        });
      });
      body.querySelectorAll('.js-unblock-user').forEach(btn => {
        btn.addEventListener('click', async () => {
          try { await api.users.unblock(Number(btn.dataset.uid)); toast('Розблоковано', 'success'); fetchUsers(); }
          catch (e) { toast(e.message, 'error'); }
        });
      });
      body.querySelectorAll('.js-del-user').forEach(btn => {
        btn.addEventListener('click', async () => {
          if (!confirm('Видалити користувача?')) return;
          try { await api.users.deleteUser(Number(btn.dataset.uid)); toast('Видалено', 'success'); fetchUsers(); }
          catch (e) { toast(e.message, 'error'); }
        });
      });
    } catch (e) {
      body.innerHTML = '<div class="alert alert-error">' + esc(e.message) + '</div>';
    }
  };

  fetchUsers();
  el('users-refresh').addEventListener('click', fetchUsers);
  el('users-search').addEventListener('input', () => { clearTimeout(_usersTimer); _usersTimer = setTimeout(fetchUsers, 400); });
  el('users-role-filter').addEventListener('change', fetchUsers);
  el('users-status-filter').addEventListener('change', fetchUsers);
}

/* ── #profile ──────────────────────────────────────────────────── */
async function loadProfile() {
  const panel = el('panel-profile');
  if (!panel) return;
  const user = SD_AUTH.getUser() || await api.auth.me().catch(() => ({}));
  panel.innerHTML =
    '<div class="section-header"><h2>Профіль</h2></div>' +
    '<div class="card" style="max-width:440px">' +
      '<div style="margin-bottom:1rem"><div class="text-muted text-sm">Логін</div><div class="font-bold">' + esc(user.login || user.web_login || '—') + '</div></div>' +
      '<div style="margin-bottom:1rem"><div class="text-muted text-sm">Повне ім\'я</div><div>' + esc(user.full_name || '—') + '</div></div>' +
      '<div style="margin-bottom:1rem"><div class="text-muted text-sm">Email</div><div>' + esc(user.email || '—') + '</div></div>' +
      '<div style="margin-bottom:1.5rem"><div class="text-muted text-sm">Роль</div><div><span class="badge badge-blue">' + esc(user.role || 'user') + '</span></div></div>' +
      '<hr style="border-color:var(--border);margin-bottom:1rem">' +
      '<h3 style="margin-bottom:0.75rem;font-size:0.95rem">Змінити пароль</h3>' +
      '<form id="change-pw-form" class="flex-col gap-2">' +
        '<div class="form-group"><label>Поточний пароль</label><input id="pw-old" type="password" class="input" required autocomplete="current-password"></div>' +
        '<div class="form-group"><label>Новий пароль</label><input id="pw-new" type="password" class="input" required autocomplete="new-password"></div>' +
        '<div id="pw-error" class="hidden"></div>' +
        '<button type="submit" class="btn btn-primary">Зберегти</button>' +
      '</form>' +
    '</div>';

  el('change-pw-form').addEventListener('submit', changePassword);
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

/* ── Logout ────────────────────────────────────────────────────── */
async function doLogout() {
  if (!confirm('Вийти з системи?')) return;
  await SD_AUTH.logout(true);
}

/* ── Topbar titles ─────────────────────────────────────────────── */
const _titles = {
  dashboard: 'Dashboard',
  events: 'Журнал подій',
  maintenance: 'Технічне обслуговування',
  fuel: 'Замовлення пального',
  schedule: 'Графік електропостачання',
  shifts: 'Розклад змін',
  admin: 'Адміністрування',
  analytics: 'Аналітика',
  reports: 'Звіти',
  users: 'Користувачі',
  profile: 'Профіль',
};

/* ── Router setup ──────────────────────────────────────────────── */
function setupRoutes() {
  const go = (name, loader) => () => {
    activatePanel(name);
    const t = el('topbar-title');
    if (t) t.textContent = _titles[name] || name;
    loader();
    closeSidebar();
  };
  router
    .on('dashboard',   go('dashboard', loadDashboard))
    .on('events',      go('events', loadEvents))
    .on('maintenance', go('maintenance', loadMaintenance))
    .on('fuel',        go('fuel', loadFuel))
    .on('schedule',    go('schedule', loadSchedule))
    .on('shifts',      go('shifts', loadShifts))
    .on('admin',       go('admin', loadAdmin))
    .on('analytics',   go('analytics', loadAnalytics))
    .on('reports',     go('reports', loadReports))
    .on('users',       go('users', loadUsers))
    .on('profile',     go('profile', loadProfile));
}

/* ── Bootstrap ─────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', async () => {
  initNav();
  setupRoutes();

  const logoutBtn = el('btn-logout');
  if (logoutBtn) logoutBtn.addEventListener('click', doLogout);

  await loadUserProfile();
  router.start('dashboard');
});
