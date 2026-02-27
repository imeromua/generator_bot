/**
 * Mini App генератора — головний модуль інтерфейсу.
 *
 * Ініціалізація Telegram WebApp, навігація по вкладках,
 * повний функціонал: управління зміни, прийом палива, графік,
 * ТО, перемикання генераторів, звіти — все в одному WebApp.
 */

(function () {
    "use strict";

    // -------------------------------------------------------------------
    // Telegram WebApp SDK
    // -------------------------------------------------------------------
    const tg = window.Telegram && window.Telegram.WebApp;
    if (tg) {
        tg.ready();
        tg.expand();
    }

    // -------------------------------------------------------------------
    // Глобальний стан
    // -------------------------------------------------------------------
    let currentTab = "dashboard";
    let userRole = { is_admin: false, personnel: null, has_personnel: false, user_id: null };
    let currentStatus = null;   // останній стан з /api/status
    let scheduleDate = null;
    let isAdminScheduleEdit = false;
    // Захист від паралельних завантажень дашборду (напр. при швидких свайпах)
    let dashboardLoadInProgress = false;

    // Стан форми прийому палива
    const refuelState = { driver: null, liters: null, step: 1 };
    // Вибраний водій / персонал в адмін-панелі
    let selectedDriver = null;
    let selectedPersonnel = null;
    // Стан форми ТО
    let pendingMnt = { action: null, generator: null };
    // Стан форми мотогодин
    let pendingHoursGen = null;

    // -------------------------------------------------------------------
    // Константи
    // -------------------------------------------------------------------
    const FUEL_CRITICAL = 15;   // поріг критичного рівня палива (л)
    const FUEL_WARNING  = 40;   // поріг попереджувального рівня палива (л)

    // -------------------------------------------------------------------
    // Допоміжні функції
    // -------------------------------------------------------------------

    function $(id) { return document.getElementById(id); }

    /**
     * Екранує рядок для безпечного вставляння у innerHTML (захист від XSS).
     */
    function escapeHtml(str) {
        if (!str) return "";
        const div = document.createElement("div");
        div.textContent = str;
        return div.innerHTML;
    }

    function shiftName(code) {
        return { m: "🌅 Зміна 1", d: "☀️ Зміна 2", e: "🌙 Зміна 3", x: "⚡ Екстра" }[code] || code;
    }

    function eventLabel(type) {
        const map = {
            m_start: "🌅 Старт зміни 1", m_end: "🌅 Кінець зміни 1",
            d_start: "☀️ Старт зміни 2", d_end: "☀️ Кінець зміни 2",
            e_start: "🌙 Старт зміни 3", e_end: "🌙 Кінець зміни 3",
            x_start: "⚡ Старт екстра",  x_end: "⚡ Кінець екстра",
            refill: "⛽ Прийом палива",   corr_fuel_set: "🔧 Корекція палива",
            sync: "🔄 Синхронізація",    mnt_oil: "🛢 Заміна мастила",
            mnt_spark: "🕯 Заміна свічок", mnt_maintenance: "🔧 Планове ТО",
            mnt_set_hours: "⏱ Корекція мотогодин", auto_stop: "⏰ Авто-зупинка",
            fuel_ordered: "📦 Паливо замовлено",
        };
        return map[type] || type;
    }

    function eventIcon(type) {
        if (type.includes("start")) return "▶️";
        if (type.includes("end") || type === "auto_stop") return "⏹";
        if (type === "refill") return "⛽";
        if (type === "sync") return "🔄";
        if (type.startsWith("mnt_")) return "🔧";
        if (type.startsWith("corr_")) return "✏️";
        return "📋";
    }

    function mntIcon(type) {
        return { oil: "🛢", spark: "🕯", maintenance: "🔧" }[type] || "🔧";
    }

    function mntLabel(type) {
        return { oil: "Заміна мастила", spark: "Заміна свічок", maintenance: "Планове ТО" }[type] || type;
    }

    function formatDate(dateStr) {
        if (!dateStr) return "—";
        try {
            const d = new Date(dateStr);
            return d.toLocaleDateString("uk-UA", { day: "2-digit", month: "2-digit" });
        } catch { return dateStr; }
    }

    function formatDateLong(dateStr) {
        if (!dateStr) return "—";
        try {
            const d = new Date(dateStr + "T00:00:00");
            const days = ["неділя","понеділок","вівторок","середа","четвер","п'ятниця","субота"];
            return `${d.getDate().toString().padStart(2,"0")}.${(d.getMonth()+1).toString().padStart(2,"0")} (${days[d.getDay()]})`;
        } catch { return dateStr; }
    }

    function formatTime(ts) {
        if (!ts) return "";
        try {
            const d = new Date(ts);
            return d.toLocaleString("uk-UA", {
                day: "2-digit", month: "2-digit",
                hour: "2-digit", minute: "2-digit",
            });
        } catch { return ts; }
    }

    function showToast(msg, type) {
        const el = document.createElement("div");
        el.className = "toast" + (type === "success" ? " toast-success" : "");
        el.textContent = msg;
        document.body.appendChild(el);
        setTimeout(() => el.remove(), 3500);
    }

    function showSuccess(msg) { showToast(msg, "success"); }
    function showError(msg)   { showToast(msg, "error"); }

    function setLoading(show) {
        const loader = $("loader");
        if (show) loader.classList.add("visible");
        else loader.classList.remove("visible");
    }

    function el(tag, cls, text) {
        const e = document.createElement(tag);
        if (cls) e.className = cls;
        if (text !== undefined) e.textContent = text;
        return e;
    }

    // -------------------------------------------------------------------
    // Навігація по вкладках
    // -------------------------------------------------------------------
    function switchTab(tab) {
        if (currentTab === tab) return;
        currentTab = tab;
        document.querySelectorAll(".tab").forEach((btn) => {
            btn.classList.toggle("active", btn.dataset.tab === tab);
        });
        document.querySelectorAll(".page").forEach((page) => {
            page.classList.toggle("active", page.id === "page-" + tab);
        });
        loadTabData(tab);
    }

    document.querySelectorAll(".tab").forEach((btn) => {
        btn.addEventListener("click", () => switchTab(btn.dataset.tab));
    });

    // -------------------------------------------------------------------
    // Завантаження даних
    // -------------------------------------------------------------------
    function loadTabData(tab) {
        switch (tab) {
            case "dashboard":   loadDashboard(); break;
            case "schedule":    loadSchedule();  break;
            case "events":      loadEvents();    break;
            case "maintenance": loadMaintenance(); break;
            case "admin":       loadAdmin();     break;
        }
    }

    // --- Dashboard ---
    async function loadDashboard() {
        if (dashboardLoadInProgress) return;
        dashboardLoadInProgress = true;
        try {
            const [status, week] = await Promise.all([
                API.getStatus(),
                API.getWeek(),
            ]);
            currentStatus = status;
            renderStatus(status);
            renderWeek(week);
            renderActionButtons(status);
        } catch (e) {
            showError("Помилка завантаження: " + e.message);
        } finally {
            dashboardLoadInProgress = false;
        }
    }

    function renderStatus(data) {
        const indicator = $("gen-indicator");
        const label     = $("gen-label");
        const badge     = $("badge-status");

        const isOn = data.status === "ON";
        indicator.className = "indicator " + (isOn ? "on" : "off");
        label.textContent = isOn ? "Генератор працює" : "Генератор вимкнено";
        badge.className = "badge " + (isOn ? "on" : "off");
        badge.textContent = isOn ? "ON" : "OFF";

        $("stat-generator").textContent = data.generator_name || data.generator;

        if (data.active_shift && data.active_shift !== "none") {
            const code = data.active_shift.split("_")[0];
            $("stat-shift").textContent = shiftName(code);
        } else {
            $("stat-shift").textContent = "Немає";
        }

        const fuelEl = $("stat-fuel");
        const fuel = isOn ? data.estimated_fuel : data.current_fuel;
        let fuelText = fuel + " л";
        if (isOn && data.estimated_fuel !== data.current_fuel) fuelText += " (оцінка)";
        fuelEl.textContent = fuelText;
        fuelEl.className = "stat-value";
        if (fuel < FUEL_CRITICAL) fuelEl.classList.add("fuel-low");
        else if (fuel < FUEL_WARNING) fuelEl.classList.add("fuel-warn");

        $("stat-hours").textContent = data.total_hours + " год";
        $("stat-rate").textContent  = data.fuel_rate + " л/год";
        $("stat-work-hours").textContent = data.work_start + " — " + data.work_end;

        const shifts = ["m", "d", "e", "x"];
        const completed = new Set(data.completed_shifts || []);
        const activeCode = data.active_shift !== "none" ? data.active_shift.split("_")[0] : null;

        shifts.forEach((s) => {
            const item = $("shift-" + s);
            const statusEl = $("shift-" + s + "-status");
            item.className = "shift-item";
            if (activeCode === s) {
                item.classList.add("active");
                statusEl.textContent = "Працює";
                statusEl.className = "shift-status running";
            } else if (completed.has(s)) {
                item.classList.add("completed");
                statusEl.textContent = "✓ Виконано";
                statusEl.className = "shift-status done";
            } else {
                statusEl.textContent = "Очікує";
                statusEl.className = "shift-status";
            }
        });
    }

    function renderActionButtons(data) {
        const body = $("actions-body");
        const noPers = $("actions-no-personnel");
        const btnsDiv = $("actions-buttons");
        const userLabel = $("user-name-label");
        const refuelCard = $("card-refuel");

        if (!userRole.has_personnel) {
            noPers.classList.remove("hidden");
            btnsDiv.classList.add("hidden");
            refuelCard.classList.add("hidden");
            return;
        }

        noPers.classList.add("hidden");
        btnsDiv.classList.remove("hidden");
        if (userRole.personnel) {
            userLabel.textContent = "👤 " + userRole.personnel;
        }

        // Показуємо кнопку прийому палива
        refuelCard.classList.remove("hidden");

        const isOn = data.status === "ON";
        const completed = new Set(data.completed_shifts || []);
        const activeCode = isOn ? data.active_shift.split("_")[0] : null;

        btnsDiv.innerHTML = "";

        if (isOn && activeCode) {
            // Кнопка СТОП
            const btn = el("button", "btn btn-danger btn-full");
            btn.textContent = `🏁 ${shiftName(activeCode)} — СТОП`;
            btn.onclick = function() { doStopShift(activeCode, this); };
            btnsDiv.appendChild(btn);
        } else {
            // Кнопки СТАРТ
            const order = ["m", "d", "e"];
            let nextStart = null;
            for (const s of order) {
                if (!completed.has(s)) { nextStart = s; break; }
            }

            if (nextStart) {
                const btn = el("button", "btn btn-success btn-full");
                btn.textContent = `▶ ${shiftName(nextStart)} — СТАРТ`;
                btn.onclick = function() { doStartShift(nextStart, this); };
                btnsDiv.appendChild(btn);
            }

            // Екстра-зміна — якщо всі три виконані
            if (["m","d","e"].every(s => completed.has(s)) && !completed.has("x")) {
                const btnX = el("button", "btn btn-primary btn-full");
                btnX.textContent = `▶ ${shiftName("x")} — СТАРТ`;
                btnX.onclick = function() { doStartShift("x", this); };
                btnsDiv.appendChild(btnX);
            }

            if (btnsDiv.children.length === 0) {
                btnsDiv.innerHTML = `<div class="empty-state"><div class="empty-state-icon">✅</div>Всі зміни сьогодні виконано</div>`;
            }
        }
    }

    async function doStartShift(shift, btn) {
        if (btn) { btn.disabled = true; btn.textContent = "⏳ Запуск..."; }
        try {
            const res = await API.startShift(shift);
            showSuccess(res.message || "Зміну запущено");
            await loadDashboard();
        } catch (e) {
            showError(e.message);
            await loadDashboard();
        }
    }

    async function doStopShift(shift, btn) {
        if (btn) { btn.disabled = true; btn.textContent = "⏳ Зупинка..."; }
        try {
            const res = await API.stopShift(shift);
            showSuccess(res.message || `Зміна закрита. Тривалість: ${res.duration}, витрата: ${res.fuel_consumed} л`);
            await loadDashboard();
        } catch (e) {
            showError(e.message);
            await loadDashboard();
        }
    }

    function renderWeek(data) {
        const grid = $("week-grid");
        if (!data || !data.days) {
            grid.innerHTML = '<div class="empty-state">Немає даних</div>';
            return;
        }
        const today = new Date().toISOString().slice(0, 10);
        grid.innerHTML = data.days.map((day) => {
            const dateNum = day.date.slice(8, 10);
            const isToday = day.date === today;
            return `<div class="week-day${isToday ? " today" : ""}" data-date="${day.date}">
                <span class="week-day-name">${day.weekday}</span>
                <span class="week-day-num">${dateNum}</span>
                ${day.off_hours > 0
                    ? `<span class="week-day-off">${day.off_hours}г</span>`
                    : `<span class="week-day-off" style="color:var(--color-on)">✓</span>`
                }
            </div>`;
        }).join("");

        grid.querySelectorAll(".week-day").forEach((el) => {
            el.addEventListener("click", () => {
                scheduleDate = el.dataset.date;
                switchTab("schedule");
            });
        });
    }

    // --- Schedule ---
    function getToday() {
        const now = new Date();
        return `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,"0")}-${String(now.getDate()).padStart(2,"0")}`;
    }

    function shiftDateStr(dateStr, days) {
        const d = new Date(dateStr + "T00:00:00");
        d.setDate(d.getDate() + days);
        return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`;
    }

    async function loadSchedule() {
        if (!scheduleDate) scheduleDate = getToday();
        $("sched-date-label").textContent = formatDateLong(scheduleDate);
        const adminHint = $("sched-admin-hint");
        if (userRole.is_admin) adminHint.classList.remove("hidden");
        else adminHint.classList.add("hidden");

        try {
            const data = await API.getSchedule(scheduleDate);
            renderSchedule(data);
        } catch (e) {
            showError("Помилка: " + e.message);
        }
    }

    function renderSchedule(data) {
        const grid = $("schedule-grid");
        const summary = $("schedule-summary");

        if (!data || !data.hours) {
            grid.innerHTML = '<div class="empty-state">Немає даних</div>';
            summary.textContent = "";
            return;
        }

        let offCount = 0;
        grid.innerHTML = data.hours.map((h) => {
            if (h.off) offCount++;
            const cls = h.off ? "off" : "on";
            const icon = h.off ? "🔴" : "🟢";
            const editAttr = userRole.is_admin ? ` data-edit="1" data-hour="${h.hour}" style="cursor:pointer"` : "";
            return `<div class="sched-hour ${cls}"${editAttr}>
                <span>${h.label}</span>
                <span class="sched-hour-icon">${icon}</span>
            </div>`;
        }).join("");

        // Адмін: кліки для редагування
        if (userRole.is_admin) {
            grid.querySelectorAll("[data-edit]").forEach((cell) => {
                cell.addEventListener("click", async () => {
                    const hour = parseInt(cell.dataset.hour);
                    try {
                        const res = await API.toggleSchedule(scheduleDate, hour);
                        // Оновлюємо конкретну клітинку
                        const isOff = res.off;
                        cell.className = "sched-hour " + (isOff ? "off" : "on");
                        cell.querySelector(".sched-hour-icon").textContent = isOff ? "🔴" : "🟢";
                        // Оновлюємо підсумок
                        const allOff = Object.values(res.schedule || {}).filter(v => v).length;
                        updateScheduleSummary(24 - allOff, allOff, summary);
                    } catch (e) {
                        showError(e.message);
                    }
                });
            });
        }

        updateScheduleSummary(24 - offCount, offCount, summary);
    }

    function updateScheduleSummary(onCount, offCount, el) {
        if (offCount === 0) {
            el.textContent = "✅ Відключень немає — електроенергія є цілий день";
        } else {
            el.textContent = `⚡ Є світло: ${onCount} год  •  🔴 Відключення: ${offCount} год`;
        }
    }

    $("sched-prev").addEventListener("click", () => {
        scheduleDate = shiftDateStr(scheduleDate || getToday(), -1);
        loadSchedule();
    });
    $("sched-next").addEventListener("click", () => {
        scheduleDate = shiftDateStr(scheduleDate || getToday(), 1);
        loadSchedule();
    });

    // --- Events ---
    async function loadEvents() {
        try {
            const data = await API.getEvents(50);
            renderEvents(data);
        } catch (e) {
            showError("Помилка: " + e.message);
        }
    }

    function renderEvents(data) {
        const list = $("events-list");
        if (!data || !data.events || data.events.length === 0) {
            list.innerHTML = `<div class="empty-state"><div class="empty-state-icon">📭</div>Подій поки немає</div>`;
            return;
        }
        list.innerHTML = data.events.map((ev) => {
            const icon = eventIcon(ev.event_type);
            const label = eventLabel(ev.event_type);
            const time = formatTime(ev.timestamp);
            let meta = time;
            if (ev.actor)   meta += ` • ${escapeHtml(ev.actor)}`;
            if (ev.driver)  meta += ` • Водій: ${escapeHtml(ev.driver)}`;
            if (ev.receipt) meta += ` • Чек: ${escapeHtml(ev.receipt)}`;
            return `<div class="event-item">
                <span class="event-icon">${icon}</span>
                <div class="event-body">
                    <div class="event-type">${label}</div>
                    <div class="event-meta">${meta}</div>
                    ${ev.value ? `<div class="event-value">${escapeHtml(ev.value)}</div>` : ""}
                </div>
            </div>`;
        }).join("");
    }

    $("events-refresh").addEventListener("click", loadEvents);

    // --- Maintenance ---
    async function loadMaintenance() {
        try {
            const data = await API.getMaintenance();
            renderMaintenance(data);
            // Показуємо кнопки ТО тільки для адмінів
            $("card-mnt-actions-main").style.display  = userRole.is_admin ? "" : "none";
            $("card-mnt-actions-emerg").style.display = userRole.is_admin ? "" : "none";
        } catch (e) {
            showError("Помилка: " + e.message);
        }
    }

    function renderMaintenance(data) {
        const statsEl   = $("mnt-stats");
        const historyEl = $("mnt-history");

        if (!data || !data.stats) {
            statsEl.innerHTML = `<div class="empty-state"><div class="empty-state-icon">🔧</div>Дані ТО недоступні</div>`;
            historyEl.innerHTML = "";
            return;
        }

        const stats = data.stats;
        const items = [
            { label: "🛢 Заміна мастила",  key: "oil_needed",         intervalKey: "oil_interval" },
            { label: "🕯 Заміна свічок",   key: "spark_needed",       intervalKey: "spark_interval" },
            { label: "🔧 Планове ТО",      key: "maintenance_needed", intervalKey: "maintenance_interval" },
        ];

        const totalHours = stats.total_hours || 0;
        statsEl.innerHTML = `
            <div class="mnt-item">
                <span class="mnt-item-label">⏱ Мотогодини (${data.generator})</span>
                <span class="mnt-item-value">${totalHours} год</span>
            </div>
        ` + items.map((item) => {
            const remaining = stats[item.key];
            if (remaining === undefined || remaining === null) return "";
            const interval = stats[item.intervalKey] || 100;
            const pct = Math.max(0, Math.min(100, (remaining / interval) * 100));
            let cls = "ok";
            if (pct < 15) cls = "danger";
            else if (pct < 40) cls = "warn";
            return `<div class="mnt-item" style="flex-direction:column;align-items:stretch;">
                <div style="display:flex;justify-content:space-between;">
                    <span class="mnt-item-label">${item.label}</span>
                    <span class="mnt-item-value ${cls}">${remaining} год</span>
                </div>
                <div class="mnt-progress">
                    <div class="mnt-progress-bar ${cls}" style="width:${pct}%"></div>
                </div>
            </div>`;
        }).join("");

        if (!data.history || data.history.length === 0) {
            historyEl.innerHTML = `<div class="empty-state">Записів ТО ще немає</div>`;
            return;
        }
        historyEl.innerHTML = data.history.map((h) => {
            return `<div class="mnt-history-item">
                <span class="mnt-history-icon">${mntIcon(h.type)}</span>
                <div class="mnt-history-body">
                    <div class="mnt-history-type">${mntLabel(h.type)}</div>
                    <div class="mnt-history-meta">${formatTime(h.date)} • ${h.admin || "—"} • ${h.hours} год</div>
                </div>
            </div>`;
        }).join("");
    }

    // --- Admin panel ---
    async function loadAdmin() {
        if (!userRole.is_admin) return;
        try {
            const [genData, status] = await Promise.all([
                API.getGenerators(),
                API.getStatus(),
            ]);
            renderGenStats(genData, status);
            const fuelInput = $("admin-fuel-input");
            if (fuelInput && status) fuelInput.value = status.current_fuel || "";
        } catch (e) {
            showError("Помилка: " + e.message);
        }
        // Load management lists in parallel (errors non-fatal)
        Promise.all([
            App.refreshAdminDrivers(),
            App.refreshAdminPersonnel(),
            App.refreshAdminUsers(),
        ]).catch(() => {});
    }

    function renderGenStats(data, status) {
        const el = $("gen-stats");
        if (!data) { el.innerHTML = ""; return; }

        const active = data.active;
        el.innerHTML = `
            <div class="gen-card ${active === 'main' ? 'active' : ''}">
                <div class="gen-card-header">🔋 Основний${active === 'main' ? ' <span class="badge on">АКТИВНИЙ</span>' : ''}</div>
                <div class="gen-card-body">
                    <div>⏱ Мотогодини: <b>${data.main.total_hours} год</b></div>
                    <div>🛢 Від заміни мастила: <b>${data.main.last_oil_change} год</b></div>
                    <div>🕯 Від заміни свічок: <b>${data.main.last_spark_change} год</b></div>
                </div>
            </div>
            <div class="gen-card ${active === 'emergency' ? 'active' : ''}">
                <div class="gen-card-header">⚠️ Аварійний${active === 'emergency' ? ' <span class="badge warn">АКТИВНИЙ</span>' : ''}</div>
                <div class="gen-card-body">
                    <div>⏱ Мотогодини: <b>${data.emergency.total_hours} год</b></div>
                    <div>🛢 Від заміни мастила: <b>${data.emergency.last_oil_change} год</b></div>
                    <div>🕯 Від заміни свічок: <b>${data.emergency.last_spark_change} год</b></div>
                </div>
            </div>
        `;

        // Оновлюємо кнопки переключення
        const btnMain  = $("btn-switch-main");
        const btnEmerg = $("btn-switch-emergency");
        if (btnMain)  btnMain.disabled  = (active === "main");
        if (btnEmerg) btnEmerg.disabled = (active === "emergency");
    }

    // -------------------------------------------------------------------
    // Публічний API додатку (для onclick у HTML)
    // -------------------------------------------------------------------
    const App = {
        // --- Генератор ---
        async switchGenerator(target) {
            if (!confirm(`Перемкнути на ${target === "main" ? "ОСНОВНИЙ" : "АВАРІЙНИЙ"} генератор?`)) return;
            try {
                const res = await API.switchGenerator(target);
                showSuccess(res.message || "Генератор перемкнено");
                await loadAdmin();
                await loadDashboard();
            } catch (e) {
                showError(e.message);
            }
        },

        // --- ТО ---
        mntPerform(action, generator) {
            pendingMnt = { action, generator };
            const actionNames = { oil: "Заміну мастила", spark: "Заміну свічок", maintenance: "Планове ТО" };
            const genNames    = { main: "🔋 Основний", emergency: "⚠️ Аварійний" };
            $("confirm-mnt-text").textContent =
                `Виконати "${actionNames[action]}" для генератора "${genNames[generator]}"?`;
            openModal("modal-confirm-mnt");
        },

        async confirmMnt() {
            closeModal("modal-confirm-mnt");
            try {
                const res = await API.performMaintenance(pendingMnt.action, pendingMnt.generator);
                showSuccess(res.message || "ТО виконано");
                await loadMaintenance();
            } catch (e) {
                showError(e.message);
            }
        },

        mntSetHoursDialog(generator) {
            pendingHoursGen = generator;
            const genNames = { main: "🔋 Основний", emergency: "⚠️ Аварійний" };
            $("set-hours-gen-name").textContent = genNames[generator] || generator;
            $("set-hours-input").value = "";
            openModal("modal-set-hours");
            // Показуємо поточне значення
            API.getGenerators().then(data => {
                const stats = data[generator];
                if (stats) {
                    $("set-hours-current").textContent = `Поточне значення: ${stats.total_hours} год`;
                }
            }).catch(() => {});
        },

        async submitSetHours() {
            const val = parseFloat($("set-hours-input").value);
            if (isNaN(val) || val < 0 || val > 100000) {
                showError("Введіть коректне значення (0 – 100000)");
                return;
            }
            closeModal("modal-set-hours");
            try {
                const res = await API.setHours(pendingHoursGen, val);
                showSuccess(res.message || "Мотогодини оновлено");
                await loadMaintenance();
            } catch (e) {
                showError(e.message);
            }
        },

        // --- Паливо (адмін) ---
        async adminSetFuel() {
            const val = parseFloat($("admin-fuel-input").value);
            if (isNaN(val) || val < 0) {
                showError("Введіть коректне значення");
                return;
            }
            if (!confirm(`Встановити рівень палива: ${val.toFixed(1)} л?`)) return;
            try {
                const res = await API.setFuel(val);
                showSuccess(res.message || "Паливо оновлено");
                await loadDashboard();
            } catch (e) {
                showError(e.message);
            }
        },

        // --- Звіти ---
        downloadReport(generator) {
            const days = $("report-days-select").value || "30";
            let url = API.getReportUrl(days, generator || "");
            // initData передається як query-параметр для прямого завантаження
            const initData = window.Telegram?.WebApp?.initData;
            if (initData) {
                url += (url.includes("?") ? "&" : "?") + "init_data=" + encodeURIComponent(initData);
            }
            // Абсолютний URL для Telegram openLink
            const absUrl = url.startsWith("http") ? url : (window.location.origin + url);
            if (window.Telegram?.WebApp?.openLink) {
                window.Telegram.WebApp.openLink(absUrl);
            } else {
                window.open(absUrl, "_blank");
            }
        },

        // --- Sync Google Sheets ---
        async syncSheets() {
            const btn = $("btn-sync-sheets");
            const resultEl = $("sync-result");
            if (btn) { btn.disabled = true; btn.textContent = "⏳ Синхронізація..."; }
            if (resultEl) resultEl.style.display = "none";
            try {
                const res = await API.adminSync();
                showSuccess(res.message || "Синхронізацію виконано");
                if (resultEl) {
                    resultEl.textContent = res.message || "Готово";
                    resultEl.style.display = "";
                }
            } catch (e) {
                showError("Помилка синхронізації: " + e.message);
                if (resultEl) {
                    resultEl.textContent = "Помилка: " + e.message;
                    resultEl.style.display = "";
                }
            } finally {
                if (btn) { btn.disabled = false; btn.textContent = "🔄 Синхронізувати з Sheets"; }
            }
        },

        // --- Drivers admin ---
        async refreshAdminDrivers() {
            const listEl = $("admin-drivers-list");
            if (!listEl) return;
            listEl.innerHTML = '<div class="spinner-small"></div>';
            try {
                const data = await API.adminGetDrivers();
                const drivers = data.drivers || [];
                if (drivers.length === 0) {
                    listEl.innerHTML = '<div class="empty-state">Водіїв немає</div>';
                    return;
                }
                listEl.innerHTML = "";
                drivers.forEach((d) => {
                    const row = document.createElement("div");
                    row.className = "manage-item" + (selectedDriver === d ? " selected" : "");
                    const name = document.createElement("span");
                    name.className = "manage-item-name";
                    name.textContent = d;
                    row.appendChild(name);
                    row.addEventListener("click", () => App.selectDriver(d));
                    listEl.appendChild(row);
                });
            } catch (e) {
                listEl.innerHTML = `<div class="empty-state">Помилка: ${e.message}</div>`;
            }
        },

        async adminAddDriver() {
            const inp = $("new-driver-name");
            const name = (inp ? inp.value : "").trim();
            if (!name) { showError("Введіть ім'я водія"); return; }
            try {
                const res = await API.adminAddDriver(name);
                showSuccess(res.message || "Додано");
                if (inp) inp.value = "";
                await App.refreshAdminDrivers();
            } catch (e) {
                showError(e.message);
            }
        },

        async adminDeleteDriver(name) {
            if (!confirm(`Видалити водія «${name}»?`)) return;
            try {
                const res = await API.adminDeleteDriver(name);
                showSuccess(res.message || "Видалено");
                await App.refreshAdminDrivers();
            } catch (e) {
                showError(e.message);
            }
        },

        selectDriver(name) {
            selectedDriver = name;
            $("selected-driver-name").textContent = name;
            $("driver-actions-panel").classList.remove("hidden");
            App.refreshAdminDrivers();
        },
        clearDriverSelection() {
            selectedDriver = null;
            $("driver-actions-panel").classList.add("hidden");
            App.refreshAdminDrivers();
        },
        async adminDeleteSelectedDriver() {
            if (!selectedDriver) return;
            if (!confirm(`Видалити водія «${selectedDriver}»?`)) return;
            try {
                const res = await API.adminDeleteDriver(selectedDriver);
                showSuccess(res.message || "Видалено");
                selectedDriver = null;
                $("driver-actions-panel").classList.add("hidden");
                await App.refreshAdminDrivers();
            } catch (e) {
                showError(e.message);
            }
        },

        // --- Personnel admin ---
        async refreshAdminPersonnel() {
            const listEl = $("admin-personnel-list");
            if (!listEl) return;
            listEl.innerHTML = '<div class="spinner-small"></div>';
            try {
                const data = await API.adminGetPersonnel();
                const personnel = data.personnel || [];
                if (personnel.length === 0) {
                    listEl.innerHTML = '<div class="empty-state">Персоналу немає</div>';
                    return;
                }
                listEl.innerHTML = "";
                personnel.forEach((p) => {
                    const row = document.createElement("div");
                    row.className = "manage-item" + (selectedPersonnel === p ? " selected" : "");
                    const name = document.createElement("span");
                    name.className = "manage-item-name";
                    name.textContent = p;
                    row.appendChild(name);
                    row.addEventListener("click", () => App.selectPersonnel(p));
                    listEl.appendChild(row);
                });
            } catch (e) {
                listEl.innerHTML = `<div class="empty-state">Помилка: ${e.message}</div>`;
            }
        },

        async adminAddPersonnel() {
            const inp = $("new-personnel-name");
            const name = (inp ? inp.value : "").trim();
            if (!name) { showError("Введіть ПІБ персоналу"); return; }
            try {
                const res = await API.adminAddPersonnel(name);
                showSuccess(res.message || "Додано");
                if (inp) inp.value = "";
                await App.refreshAdminPersonnel();
            } catch (e) {
                showError(e.message);
            }
        },

        async adminDeletePersonnel(name) {
            if (!confirm(`Видалити персонал «${name}»?`)) return;
            try {
                const res = await API.adminDeletePersonnel(name);
                showSuccess(res.message || "Видалено");
                await App.refreshAdminPersonnel();
                await App.refreshAdminUsers();
            } catch (e) {
                showError(e.message);
            }
        },

        selectPersonnel(name) {
            selectedPersonnel = name;
            $("selected-personnel-name").textContent = name;
            $("personnel-actions-panel").classList.remove("hidden");
            App.refreshAdminPersonnel();
        },
        clearPersonnelSelection() {
            selectedPersonnel = null;
            $("personnel-actions-panel").classList.add("hidden");
            App.refreshAdminPersonnel();
        },
        async adminDeleteSelectedPersonnel() {
            if (!selectedPersonnel) return;
            if (!confirm(`Видалити персонал «${selectedPersonnel}»?`)) return;
            try {
                const res = await API.adminDeletePersonnel(selectedPersonnel);
                showSuccess(res.message || "Видалено");
                selectedPersonnel = null;
                $("personnel-actions-panel").classList.add("hidden");
                await App.refreshAdminPersonnel();
                await App.refreshAdminUsers();
            } catch (e) {
                showError(e.message);
            }
        },

        // --- Users + personnel assignment ---
        async refreshAdminUsers() {
            const listEl = $("admin-users-list");
            if (!listEl) return;
            listEl.innerHTML = '<div class="spinner-small"></div>';
            try {
                const data = await API.adminGetPersonnel();
                const users = data.users || [];
                const personnelNames = data.personnel || [];
                if (users.length === 0) {
                    listEl.innerHTML = '<div class="empty-state">Зареєстрованих користувачів немає</div>';
                    return;
                }
                listEl.innerHTML = "";
                users.forEach((u) => {
                    const row = document.createElement("div");
                    row.className = "manage-item";
                    const info = document.createElement("div");
                    info.style.flex = "1";
                    const nameSpan = document.createElement("div");
                    nameSpan.className = "manage-item-name";
                    nameSpan.textContent = u.full_name || `User ${u.user_id}`;
                    const idSpan = document.createElement("div");
                    idSpan.className = "hint-text";
                    idSpan.style.fontSize = "11px";
                    idSpan.textContent = `ID: ${u.user_id}`;
                    info.appendChild(nameSpan);
                    info.appendChild(idSpan);

                    const sel = document.createElement("select");
                    sel.className = "form-input";
                    sel.style.width = "auto";
                    sel.style.fontSize = "12px";
                    sel.style.padding = "4px 6px";
                    const optNone = document.createElement("option");
                    optNone.value = "";
                    optNone.textContent = "— без прив'язки —";
                    sel.appendChild(optNone);
                    personnelNames.forEach((p) => {
                        const opt = document.createElement("option");
                        opt.value = p;
                        opt.textContent = p;
                        if (u.personnel === p) opt.selected = true;
                        sel.appendChild(opt);
                    });

                    const saveBtn = document.createElement("button");
                    saveBtn.className = "btn btn-primary btn-sm-icon";
                    saveBtn.textContent = "💾";
                    saveBtn.title = "Зберегти";
                    saveBtn.addEventListener("click", async () => {
                        const chosen = sel.value || null;
                        try {
                            const res = await API.adminAssignPersonnel(u.user_id, chosen);
                            showSuccess(res.message || "Збережено");
                        } catch (e) {
                            showError(e.message);
                        }
                    });

                    row.appendChild(info);
                    row.appendChild(sel);
                    row.appendChild(saveBtn);
                    listEl.appendChild(row);
                });
            } catch (e) {
                listEl.innerHTML = `<div class="empty-state">Помилка: ${e.message}</div>`;
            }
        },

        // --- Прийом палива (модальне вікно) ---
        openRefuel() { openRefuelModal(); },
        closeModal,

        selectFuelAmount(liters) {
            $("refuel-liters").value = liters;
        },

        refuelNextStep() {
            const liters = parseFloat($("refuel-liters").value);
            if (!liters || liters <= 0 || liters > 500) {
                showError("Введіть кількість літрів (1 – 500)");
                return;
            }
            refuelState.liters = liters;
            $("refuel-summary").textContent = `Водій: ${refuelState.driver} • Літри: ${liters.toFixed(1)} л`;
            $("refuel-receipt").value = "";

            showRefuelStep(3);
        },

        refuelPrevStep() {
            if (refuelState.step === 2) showRefuelStep(1);
            else if (refuelState.step === 3) showRefuelStep(2);
        },

        async submitRefuel() {
            const receipt = ($("refuel-receipt").value || "").trim();
            if (!receipt || receipt.length > 50) {
                showError("Введіть номер чека (1–50 символів)");
                return;
            }
            closeModal("modal-refuel");
            try {
                const res = await API.refuel(refuelState.driver, refuelState.liters, receipt);
                showSuccess(res.message || "Паливо прийнято");
                await loadDashboard();
            } catch (e) {
                showError(e.message);
            }
        },
    };

    // Прив'язуємо App до window для onclick у HTML
    window.App = App;

    // -------------------------------------------------------------------
    // Модальні вікна
    // -------------------------------------------------------------------
    function openModal(id) {
        const el = $(id);
        if (el) el.classList.remove("hidden");
    }

    function closeModal(id) {
        const el = $(id);
        if (el) el.classList.add("hidden");
    }

    // Закриття по кліку поза модальним вікном
    document.querySelectorAll(".modal-overlay").forEach((overlay) => {
        overlay.addEventListener("click", (e) => {
            if (e.target === overlay) {
                overlay.classList.add("hidden");
            }
        });
    });

    // --- Прийом палива ---
    function showRefuelStep(step) {
        refuelState.step = step;
        $("refuel-step-driver").classList.toggle("hidden", step !== 1);
        $("refuel-step-liters").classList.toggle("hidden", step !== 2);
        $("refuel-step-receipt").classList.toggle("hidden", step !== 3);
        $("refuel-back-btn").style.display = step > 1 ? "" : "none";
    }

    async function openRefuelModal() {
        showRefuelStep(1);
        refuelState.driver = null;
        refuelState.liters = null;

        const driversList = $("drivers-list");
        driversList.innerHTML = `<div class="spinner-small"></div>`;
        openModal("modal-refuel");

        try {
            const data = await API.getDrivers();
            const drivers = data.drivers || [];
            if (drivers.length === 0) {
                driversList.innerHTML = `<div class="empty-state">Водіїв не знайдено.<br>Зверніться до адміністратора.</div>`;
                return;
            }
            // Будуємо кнопки без onclick-рядків (уникаємо XSS)
            driversList.innerHTML = "";
            drivers.forEach((d) => {
                const btn = document.createElement("button");
                btn.className = "btn btn-driver";
                btn.textContent = d;
                btn.addEventListener("click", () => selectDriver(d));
                driversList.appendChild(btn);
            });
        } catch (e) {
            driversList.innerHTML = `<div class="empty-state">Помилка завантаження водіїв</div>`;
        }
    }

    function selectDriver(driverName) {
        refuelState.driver = driverName;
        $("refuel-driver-name").textContent = "Водій: " + driverName;
        showRefuelStep(2);
    }

    $("btn-refuel-open").addEventListener("click", openRefuelModal);

    // -------------------------------------------------------------------
    // Автооновлення
    // -------------------------------------------------------------------
    const REFRESH_INTERVAL_ON  = 10000; // 10 сек — поки генератор працює
    const REFRESH_INTERVAL_OFF = 30000; // 30 сек — в стані спокою

    setInterval(() => {
        if (currentTab === "dashboard") {
            loadDashboard();
        }
    }, REFRESH_INTERVAL_OFF);

    // Швидке оновлення показників (паливо, мотогодини) під час роботи генератора
    setInterval(() => {
        if (currentTab !== "dashboard") return;
        if (!currentStatus || currentStatus.status !== "ON") return;
        // Оновлюємо лише числові показники без повного перезавантаження
        API.getStatus().then((data) => {
            currentStatus = data;
            // Оновлюємо лише паливо та мотогодини (уникаємо мерехтіння)
            if (data.status === "ON") {
                const fuelEl = $("stat-fuel");
                if (fuelEl) {
                    const fuel = data.estimated_fuel;
                    fuelEl.textContent = fuel + " л (оцінка)";
                    fuelEl.className = "stat-value";
                    if (fuel < FUEL_CRITICAL) fuelEl.classList.add("fuel-low");
                    else if (fuel < FUEL_WARNING) fuelEl.classList.add("fuel-warn");
                }
            }
        }).catch(() => {});
    }, REFRESH_INTERVAL_ON);

    // -------------------------------------------------------------------
    // Свайп між вкладками
    // -------------------------------------------------------------------
    (function initSwipe() {
        const pages = document.getElementById("app");
        let touchStartX = 0;
        let touchStartY = 0;
        const SWIPE_THRESHOLD = 50; // мінімальна відстань свайпу (px)
        const TAB_ORDER = ["dashboard", "schedule", "events", "maintenance", "admin"];

        function getVisibleTabs() {
            return TAB_ORDER.filter((t) => {
                const btn = document.querySelector(`.tab[data-tab="${t}"]`);
                return btn && !btn.classList.contains("hidden");
            });
        }

        pages.addEventListener("touchstart", (e) => {
            touchStartX = e.changedTouches[0].clientX;
            touchStartY = e.changedTouches[0].clientY;
        }, { passive: true });

        pages.addEventListener("touchend", (e) => {
            const dx = e.changedTouches[0].clientX - touchStartX;
            const dy = e.changedTouches[0].clientY - touchStartY;
            // Ігноруємо вертикальні свайпи та занадто короткі
            if (Math.abs(dy) > Math.abs(dx) || Math.abs(dx) < SWIPE_THRESHOLD) return;
            const tabs = getVisibleTabs();
            const idx = tabs.indexOf(currentTab);
            if (dx < 0 && idx < tabs.length - 1) {
                switchTab(tabs[idx + 1]);
            } else if (dx > 0 && idx > 0) {
                switchTab(tabs[idx - 1]);
            }
        }, { passive: true });
    })();

    // -------------------------------------------------------------------
    // Ініціалізація
    // -------------------------------------------------------------------
    async function init() {
        setLoading(true);
        try {
            // Отримуємо роль користувача
            try {
                userRole = await API.getUserRole();
            } catch (e) {
                userRole = { is_admin: false, personnel: null, has_personnel: false };
            }

            // Показуємо вкладку Адмін тільки для адмінів
            if (userRole.is_admin) {
                const tabAdmin = $("tab-admin");
                if (tabAdmin) tabAdmin.classList.remove("hidden");
            }

            await loadDashboard();
        } catch {
            // Ігноруємо — помилка вже показана через toast
        } finally {
            setLoading(false);
        }
    }

    init();
})();

