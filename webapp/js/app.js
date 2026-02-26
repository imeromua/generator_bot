/**
 * Mini App генератора — головний модуль інтерфейсу.
 *
 * Ініціалізація Telegram WebApp, навігація по вкладках,
 * рендеринг даних дашборду, графіку, подій та ТО.
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
    // Допоміжні функції
    // -------------------------------------------------------------------

    /** Повертає DOM-елемент за id. */
    function $(id) {
        return document.getElementById(id);
    }

    /** Назва типу зміни. */
    function shiftName(code) {
        return { m: "🌅 Зміна 1", d: "☀️ Зміна 2", e: "🌙 Зміна 3", x: "⚡ Екстра" }[code] || code;
    }

    /** Назва типу події. */
    function eventLabel(type) {
        const map = {
            m_start: "🌅 Старт зміни 1",
            m_end: "🌅 Кінець зміни 1",
            d_start: "☀️ Старт зміни 2",
            d_end: "☀️ Кінець зміни 2",
            e_start: "🌙 Старт зміни 3",
            e_end: "🌙 Кінець зміни 3",
            x_start: "⚡ Старт екстра",
            x_end: "⚡ Кінець екстра",
            refill: "⛽ Заправка",
            corr_fuel_set: "🔧 Корекція палива",
            sync: "🔄 Синхронізація",
            mnt_oil: "🛢 Заміна мастила",
            mnt_spark: "🕯 Заміна свічок",
            mnt_maintenance: "🔧 Планове ТО",
            mnt_set_hours: "⏱ Корекція мотогодин",
            auto_stop: "⏰ Авто-зупинка",
        };
        return map[type] || type;
    }

    /** Іконка для типу події. */
    function eventIcon(type) {
        if (type.includes("start")) return "▶️";
        if (type.includes("end") || type === "auto_stop") return "⏹";
        if (type === "refill") return "⛽";
        if (type === "sync") return "🔄";
        if (type.startsWith("mnt_")) return "🔧";
        if (type.startsWith("corr_")) return "✏️";
        return "📋";
    }

    /** Іконка для типу ТО. */
    function mntIcon(type) {
        return { oil: "🛢", spark: "🕯", maintenance: "🔧" }[type] || "🔧";
    }

    /** Назва типу ТО. */
    function mntLabel(type) {
        return { oil: "Заміна мастила", spark: "Заміна свічок", maintenance: "Планове ТО" }[type] || type;
    }

    /** Форматує дату в зручний вигляд. */
    function formatDate(dateStr) {
        if (!dateStr) return "—";
        try {
            const d = new Date(dateStr);
            return d.toLocaleDateString("uk-UA", { day: "2-digit", month: "2-digit" });
        } catch {
            return dateStr;
        }
    }

    /** Форматує timestamp. */
    function formatTime(ts) {
        if (!ts) return "";
        try {
            const d = new Date(ts);
            return d.toLocaleString("uk-UA", {
                day: "2-digit", month: "2-digit",
                hour: "2-digit", minute: "2-digit",
            });
        } catch {
            return ts;
        }
    }

    /** Показати тост-повідомлення про помилку. */
    function showToast(msg) {
        const el = document.createElement("div");
        el.className = "toast";
        el.textContent = msg;
        document.body.appendChild(el);
        setTimeout(() => el.remove(), 3200);
    }

    // -------------------------------------------------------------------
    // Навігація по вкладках
    // -------------------------------------------------------------------
    let currentTab = "dashboard";

    function switchTab(tab) {
        if (currentTab === tab) return;
        currentTab = tab;

        document.querySelectorAll(".tab").forEach((btn) => {
            btn.classList.toggle("active", btn.dataset.tab === tab);
        });
        document.querySelectorAll(".page").forEach((page) => {
            page.classList.toggle("active", page.id === "page-" + tab);
        });

        // Завантажити дані для вкладки
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
            case "dashboard": loadDashboard(); break;
            case "schedule": loadSchedule(); break;
            case "events": loadEvents(); break;
            case "maintenance": loadMaintenance(); break;
        }
    }

    // --- Dashboard ---
    async function loadDashboard() {
        try {
            const [status, week] = await Promise.all([
                API.getStatus(),
                API.getWeek(),
            ]);
            renderStatus(status);
            renderWeek(week);
        } catch (e) {
            showToast("Помилка завантаження: " + e.message);
        }
    }

    function renderStatus(data) {
        // Статус-бар
        const indicator = $("gen-indicator");
        const label = $("gen-label");
        const badge = $("badge-status");

        const isOn = data.status === "ON";
        indicator.className = "indicator " + (isOn ? "on" : "off");
        label.textContent = isOn
            ? "Генератор працює"
            : "Генератор вимкнено";

        badge.className = "badge " + (isOn ? "on" : "off");
        badge.textContent = isOn ? "ON" : "OFF";

        // Статистика
        $("stat-generator").textContent = data.generator_name || data.generator;

        // Зміна
        if (data.active_shift && data.active_shift !== "none") {
            const code = data.active_shift.split("_")[0];
            $("stat-shift").textContent = shiftName(code);
        } else {
            $("stat-shift").textContent = "Немає";
        }

        // Паливо
        const fuelEl = $("stat-fuel");
        const fuel = isOn ? data.estimated_fuel : data.current_fuel;
        let fuelText = fuel + " л";
        if (isOn && data.estimated_fuel !== data.current_fuel) {
            fuelText += " (оцінка)";
        }
        fuelEl.textContent = fuelText;
        fuelEl.className = "stat-value";
        if (fuel < 15) fuelEl.classList.add("fuel-low");
        else if (fuel < 40) fuelEl.classList.add("fuel-warn");

        // Мотогодини
        $("stat-hours").textContent = data.total_hours + " год";

        // Витрата
        $("stat-rate").textContent = data.fuel_rate + " л/год";

        // Робочий час
        $("stat-work-hours").textContent = data.work_start + " — " + data.work_end;

        // Зміни
        const shifts = ["m", "d", "e", "x"];
        const completed = new Set(data.completed_shifts || []);
        const activeCode = data.active_shift !== "none"
            ? data.active_shift.split("_")[0]
            : null;

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

        // Клік по дню → перехід на графік
        grid.querySelectorAll(".week-day").forEach((el) => {
            el.addEventListener("click", () => {
                scheduleDate = el.dataset.date;
                switchTab("schedule");
            });
        });
    }

    // --- Schedule ---
    let scheduleDate = null;

    function getToday() {
        const now = new Date();
        const y = now.getFullYear();
        const m = String(now.getMonth() + 1).padStart(2, "0");
        const d = String(now.getDate()).padStart(2, "0");
        return `${y}-${m}-${d}`;
    }

    function shiftDate(dateStr, days) {
        const d = new Date(dateStr + "T00:00:00");
        d.setDate(d.getDate() + days);
        const y = d.getFullYear();
        const m = String(d.getMonth() + 1).padStart(2, "0");
        const dd = String(d.getDate()).padStart(2, "0");
        return `${y}-${m}-${dd}`;
    }

    async function loadSchedule() {
        if (!scheduleDate) scheduleDate = getToday();

        $("sched-date-label").textContent = formatDate(scheduleDate);

        try {
            const data = await API.getSchedule(scheduleDate);
            renderSchedule(data);
        } catch (e) {
            showToast("Помилка: " + e.message);
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
            return `<div class="sched-hour ${cls}">
                <span>${h.label}</span>
                <span class="sched-hour-icon">${icon}</span>
            </div>`;
        }).join("");

        const onCount = 24 - offCount;
        if (offCount === 0) {
            summary.textContent = "✅ Відключень немає — електроенергія є цілий день";
        } else {
            summary.textContent = `⚡ Є світло: ${onCount} год  •  🔴 Відключення: ${offCount} год`;
        }
    }

    $("sched-prev").addEventListener("click", () => {
        scheduleDate = shiftDate(scheduleDate || getToday(), -1);
        loadSchedule();
    });

    $("sched-next").addEventListener("click", () => {
        scheduleDate = shiftDate(scheduleDate || getToday(), 1);
        loadSchedule();
    });

    // --- Events ---
    async function loadEvents() {
        try {
            const data = await API.getEvents(30);
            renderEvents(data);
        } catch (e) {
            showToast("Помилка: " + e.message);
        }
    }

    function renderEvents(data) {
        const list = $("events-list");

        if (!data || !data.events || data.events.length === 0) {
            list.innerHTML = `<div class="empty-state">
                <div class="empty-state-icon">📭</div>
                Подій поки немає
            </div>`;
            return;
        }

        list.innerHTML = data.events.map((ev) => {
            const icon = eventIcon(ev.event_type);
            const label = eventLabel(ev.event_type);
            const time = formatTime(ev.timestamp);

            let meta = time;
            if (ev.actor) meta += ` • ${ev.actor}`;
            if (ev.driver) meta += ` • Водій: ${ev.driver}`;
            if (ev.receipt) meta += ` • Чек: ${ev.receipt}`;

            return `<div class="event-item">
                <span class="event-icon">${icon}</span>
                <div class="event-body">
                    <div class="event-type">${label}</div>
                    <div class="event-meta">${meta}</div>
                    ${ev.value ? `<div class="event-value">${ev.value}</div>` : ""}
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
        } catch (e) {
            showToast("Помилка: " + e.message);
        }
    }

    function renderMaintenance(data) {
        const statsEl = $("mnt-stats");
        const historyEl = $("mnt-history");

        if (!data || !data.stats) {
            statsEl.innerHTML = `<div class="empty-state">
                <div class="empty-state-icon">🔧</div>
                Дані ТО недоступні
            </div>`;
            historyEl.innerHTML = "";
            return;
        }

        const stats = data.stats;
        const items = [
            { label: "🛢 Заміна мастила", key: "hours_until_oil", interval: "oil_interval" },
            { label: "🕯 Заміна свічок", key: "hours_until_spark", interval: "spark_interval" },
            { label: "🔧 Планове ТО", key: "hours_until_maintenance", interval: "maintenance_interval" },
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

            const interval = stats[item.interval] || 100;
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

        // Історія
        if (!data.history || data.history.length === 0) {
            historyEl.innerHTML = `<div class="empty-state">Записів ТО ще немає</div>`;
            return;
        }

        historyEl.innerHTML = data.history.map((h) => {
            const icon = mntIcon(h.type);
            const label = mntLabel(h.type);
            const date = formatTime(h.date);
            return `<div class="mnt-history-item">
                <span class="mnt-history-icon">${icon}</span>
                <div class="mnt-history-body">
                    <div class="mnt-history-type">${label}</div>
                    <div class="mnt-history-meta">${date} • ${h.admin || "—"} • ${h.hours} год</div>
                </div>
            </div>`;
        }).join("");
    }

    // -------------------------------------------------------------------
    // Автооновлення
    // -------------------------------------------------------------------
    const REFRESH_INTERVAL = 30000; // 30 секунд

    setInterval(() => {
        if (currentTab === "dashboard") loadDashboard();
    }, REFRESH_INTERVAL);

    // -------------------------------------------------------------------
    // Ініціалізація
    // -------------------------------------------------------------------
    async function init() {
        const loader = $("loader");
        loader.classList.add("visible");

        try {
            await loadDashboard();
        } catch {
            // Ігноруємо — помилка вже показана через toast
        } finally {
            loader.classList.remove("visible");
        }
    }

    init();
})();
