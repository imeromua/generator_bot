/**
 * ⚡ Генератор — Telegram Mini App
 * Головний модуль додатку
 */

(function () {
    'use strict';

    // --- Telegram WebApp ---
    const tg = window.Telegram && window.Telegram.WebApp;
    let initData = '';

    if (tg) {
        tg.ready();
        tg.expand();
        initData = tg.initData || '';
    }

    // --- Елементи DOM ---
    const $ = (sel) => document.querySelector(sel);
    const $$ = (sel) => document.querySelectorAll(sel);

    const loadingEl = $('#loading');
    const errorEl = $('#error-screen');
    const navEl = $('#bottom-nav');

    // --- Стан ---
    let currentPage = 'dashboard';
    let statusData = null;
    let refreshTimer = null;

    // --- API ---
    async function apiGet(endpoint) {
        const headers = {};
        if (initData) {
            headers['X-Telegram-Init-Data'] = initData;
        }

        const resp = await fetch('/api/' + endpoint, { headers });
        if (!resp.ok) {
            throw new Error('API error: ' + resp.status);
        }
        return resp.json();
    }

    // --- Ініціалізація ---
    async function init() {
        if (!initData) {
            loadingEl.classList.add('hidden');
            errorEl.classList.remove('hidden');
            navEl.classList.add('hidden');
            return;
        }

        try {
            statusData = await apiGet('status');
            loadingEl.classList.add('hidden');
            navEl.classList.remove('hidden');
            showPage('dashboard');
            startAutoRefresh();
        } catch (e) {
            loadingEl.classList.add('hidden');
            errorEl.classList.remove('hidden');
            navEl.classList.add('hidden');
        }
    }

    // --- Навігація ---
    function showPage(page) {
        currentPage = page;

        $$('.page').forEach((p) => p.classList.add('hidden'));
        $$('.nav-btn').forEach((b) => b.classList.remove('active'));

        const pageEl = $('#page-' + page);
        const navBtn = document.querySelector(`.nav-btn[data-page="${page}"]`);

        if (pageEl) pageEl.classList.remove('hidden');
        if (navBtn) navBtn.classList.add('active');

        // Завантажуємо дані для сторінки
        switch (page) {
            case 'dashboard':
                loadDashboard();
                break;
            case 'schedule':
                loadSchedule();
                break;
            case 'events':
                loadEvents();
                break;
            case 'maintenance':
                loadMaintenance();
                break;
            case 'generators':
                loadGenerators();
                break;
        }
    }

    // --- Автооновлення ---
    function startAutoRefresh() {
        if (refreshTimer) clearInterval(refreshTimer);
        refreshTimer = setInterval(() => {
            if (currentPage === 'dashboard') {
                loadDashboard();
            }
        }, 30000); // 30 секунд
    }

    // --- ДАШБОРД ---
    async function loadDashboard() {
        try {
            statusData = await apiGet('status');
            renderDashboard(statusData);
        } catch (e) {
            // Тиха помилка при оновленні
        }
    }

    function renderDashboard(data) {
        const isOn = data.status === 'ON';

        // Статус
        const dot = $('#status-dot');
        const text = $('#status-text');
        dot.className = 'status-dot' + (isOn ? ' on' : '');
        text.textContent = isOn ? 'ПРАЦЮЄ' : 'ВИМКНЕНО';

        // Зміна
        $('#shift-value').textContent = data.active_shift_name || '—';
        const startRow = $('#start-time-row');
        if (isOn && data.start_time) {
            startRow.classList.remove('hidden');
            $('#start-time-value').textContent = data.start_time;
        } else {
            startRow.classList.add('hidden');
        }

        // Паливо
        const fuel = data.current_fuel || 0;
        $('#fuel-value').textContent = fuel.toFixed(1) + ' л';
        const fuelPct = Math.min(100, Math.max(0, (fuel / 200) * 100));
        const fuelBar = $('#fuel-progress');
        fuelBar.style.width = fuelPct + '%';
        fuelBar.className = 'progress-fill fuel-progress';
        if (fuelPct < 15) fuelBar.classList.add('critical');
        else if (fuelPct < 30) fuelBar.classList.add('low');

        // Мотогодини
        $('#hours-value').textContent = (data.total_hours || 0).toFixed(1);

        // Витрата
        $('#consumption-value').textContent = (data.fuel_consumption || 0) + ' л/год';

        // Зміни
        const completed = data.completed_shifts || [];
        $('#shifts-completed').textContent = completed.length + ' / 3';

        // Бейдж генератора
        $('#generator-badge').textContent = data.generator_name || '🔋 Основний';
    }

    // --- ГРАФІК ---
    async function loadSchedule() {
        try {
            const data = await apiGet('schedule');
            renderSchedule(data);
        } catch (e) {
            $('#schedule-grid').innerHTML = '<p class="events-empty">Помилка завантаження</p>';
        }
    }

    function renderSchedule(data) {
        const dateStr = data.date || '';
        if (dateStr) {
            const parts = dateStr.split('-');
            $('#schedule-date').textContent = parts[2] + '.' + parts[1] + '.' + parts[0];
        }

        const grid = $('#schedule-grid');
        const currentHour = new Date().getHours();
        let html = '';

        (data.hours || []).forEach((h) => {
            const cls = h.is_off ? 'off' : 'on';
            const isCurrent = h.hour === currentHour ? ' current' : '';
            html += `<div class="schedule-hour ${cls}${isCurrent}">${h.label}</div>`;
        });

        grid.innerHTML = html;
    }

    // --- ПОДІЇ ---
    async function loadEvents() {
        try {
            const data = await apiGet('events?limit=30');
            renderEvents(data);
        } catch (e) {
            $('#events-list').innerHTML = '<p class="events-empty">Помилка завантаження</p>';
        }
    }

    function renderEvents(data) {
        const list = $('#events-list');
        const events = data.events || [];

        if (events.length === 0) {
            list.innerHTML = '<p class="events-empty">Подій поки немає</p>';
            return;
        }

        const typeNames = {
            m_start: 'Зміна 1 — старт',
            m_end: 'Зміна 1 — стоп',
            d_start: 'Зміна 2 — старт',
            d_end: 'Зміна 2 — стоп',
            e_start: 'Зміна 3 — старт',
            e_end: 'Зміна 3 — стоп',
            x_start: 'Екстра — старт',
            x_end: 'Екстра — стоп',
            refill: 'Заправка',
            oil: 'Заміна мастила',
            spark: 'Заміна свічок',
            maintenance: 'Планове ТО',
            sync: 'Синхронізація',
            corr_fuel_set: 'Корекція палива',
            corr_hours_set: 'Корекція годин',
        };

        let html = '';
        events.forEach((ev) => {
            const name = typeNames[ev.type] || ev.type;
            const ts = formatTimestamp(ev.timestamp);
            let meta = ev.user || '';
            if (ev.value) meta += (meta ? ' · ' : '') + ev.value;
            if (ev.driver) meta += (meta ? ' · ' : '') + '🚛 ' + ev.driver;
            if (ev.receipt) meta += (meta ? ' · ' : '') + '🧾 ' + ev.receipt;

            html += `
                <div class="event-item">
                    <div class="event-icon">${ev.icon}</div>
                    <div class="event-content">
                        <div class="event-type">${name}</div>
                        ${meta ? `<div class="event-meta">${meta}</div>` : ''}
                    </div>
                    <div class="event-time">${ts}</div>
                </div>`;
        });

        list.innerHTML = html;
    }

    // --- ТО ---
    async function loadMaintenance() {
        try {
            const data = await apiGet('maintenance');
            renderMaintenance(data);
        } catch (e) {
            // Тиха помилка
        }
    }

    function renderMaintenance(data) {
        $('#maint-generator').textContent = data.generator_name || '';

        // Мастило
        const oilPct = Math.min(100, (data.oil_used / data.oil_interval) * 100);
        const oilBar = $('#oil-progress');
        oilBar.style.width = oilPct + '%';
        oilBar.className = 'progress-fill oil-progress';
        if (oilPct >= 90) oilBar.classList.add('danger');
        else if (oilPct >= 70) oilBar.classList.add('warning');
        $('#oil-used').textContent = data.oil_used;
        $('#oil-interval').textContent = data.oil_interval;
        $('#oil-remaining').textContent = 'Залишилось: ' + data.oil_remaining + ' год';

        // Свічки
        const sparkPct = Math.min(100, (data.spark_used / data.spark_interval) * 100);
        const sparkBar = $('#spark-progress');
        sparkBar.style.width = sparkPct + '%';
        sparkBar.className = 'progress-fill spark-progress';
        if (sparkPct >= 90) sparkBar.classList.add('danger');
        else if (sparkPct >= 70) sparkBar.classList.add('warning');
        $('#spark-used').textContent = data.spark_used;
        $('#spark-interval').textContent = data.spark_interval;
        $('#spark-remaining').textContent = 'Залишилось: ' + data.spark_remaining + ' год';

        // Планове ТО
        $('#maint-remaining').textContent = 'Залишилось: ' + data.maintenance_remaining + ' год';

        // Історія
        const histEl = $('#maint-history');
        const history = data.history || [];
        if (history.length === 0) {
            histEl.innerHTML = '<p class="maint-history-empty">Історія порожня</p>';
            return;
        }

        let html = '';
        history.forEach((item) => {
            const date = formatTimestamp(item.date);
            html += `
                <div class="maint-history-item">
                    <span class="maint-history-type">${item.type}</span>
                    <span class="maint-history-info">${date} · ${item.admin} · ${item.hours} год</span>
                </div>`;
        });
        histEl.innerHTML = html;
    }

    // --- ГЕНЕРАТОРИ ---
    async function loadGenerators() {
        try {
            const data = await apiGet('generators');
            renderGenerators(data);
        } catch (e) {
            // Тиха помилка
        }
    }

    function renderGenerators(data) {
        const container = $('#gen-cards');
        const gens = data.generators || {};
        let html = '';

        ['main', 'emergency'].forEach((key) => {
            const gen = gens[key];
            if (!gen) return;
            const isActive = gen.is_active;
            html += `
                <div class="gen-card${isActive ? ' active' : ''}">
                    <div class="gen-card-header">
                        <span class="gen-card-name">${gen.name}</span>
                        <span class="gen-card-status ${isActive ? 'active' : 'inactive'}">
                            ${isActive ? '● Активний' : 'Неактивний'}
                        </span>
                    </div>
                    <div class="gen-card-stats">
                        <div class="gen-stat">
                            <div class="gen-stat-label">Мотогодини</div>
                            <div class="gen-stat-value">${gen.total_hours}</div>
                        </div>
                        <div class="gen-stat">
                            <div class="gen-stat-label">Після мастила</div>
                            <div class="gen-stat-value">${gen.last_oil_change}</div>
                        </div>
                        <div class="gen-stat">
                            <div class="gen-stat-label">Після свічок</div>
                            <div class="gen-stat-value">${gen.last_spark_change}</div>
                        </div>
                    </div>
                </div>`;
        });

        container.innerHTML = html;

        // Паливо
        const fuel = data.current_fuel || 0;
        $('#gen-fuel-value').textContent = fuel.toFixed(1) + ' л';
        const fuelPct = Math.min(100, Math.max(0, (fuel / 200) * 100));
        const fuelBar = $('#gen-fuel-progress');
        fuelBar.style.width = fuelPct + '%';
        fuelBar.className = 'progress-fill fuel-progress';
        if (fuelPct < 15) fuelBar.classList.add('critical');
        else if (fuelPct < 30) fuelBar.classList.add('low');
    }

    // --- Утиліти ---
    function formatTimestamp(ts) {
        if (!ts) return '';
        // "2026-02-12 14:30:00" → "12.02 14:30"
        const match = ts.match(/(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2})/);
        if (match) {
            return match[3] + '.' + match[2] + ' ' + match[4] + ':' + match[5];
        }
        return ts;
    }

    // --- Обробники подій ---
    navEl.addEventListener('click', (e) => {
        const btn = e.target.closest('.nav-btn');
        if (!btn) return;
        const page = btn.dataset.page;
        if (page) showPage(page);
    });

    // --- Старт ---
    init();
})();
