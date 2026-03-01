/**
 * Notification preferences UI for admin panel.
 * Provides toggle controls, quiet-hours settings, and test notification
 * through the /api/notifications/* API endpoints.
 */

const Notifications = (() => {
    "use strict";

    const CATEGORY_LABELS = {
        critical:  "🔴 Критичні",
        important: "⚠️ Важливі",
        info:      "ℹ️ Інформаційні",
    };

    function _el(id) {
        return document.getElementById(id);
    }

    function _showToast(msg, type) {
        if (typeof App !== "undefined" && App.showToast) {
            App.showToast(msg, type);
        }
    }

    // -----------------------------------------------------------------------
    // Load & render
    // -----------------------------------------------------------------------

    async function load() {
        const container = _el("notif-types-list");
        if (!container) return;
        container.innerHTML = '<div class="loading">Завантаження...</div>';
        try {
            const data = await API.getNotificationPreferences();
            _render(data);
            _populateQuietHours(data.preferences || {});
        } catch (e) {
            container.innerHTML = `<div class="hint-text" style="color:var(--color-danger)">❌ ${e.message}</div>`;
        }
    }

    function _render(data) {
        const container = _el("notif-types-list");
        if (!container) return;

        const prefs = data.preferences || {};
        const types = data.types || {};

        const grouped = { critical: [], important: [], info: [] };
        Object.entries(types).forEach(([key, meta]) => {
            const cat = meta.category || "info";
            (grouped[cat] = grouped[cat] || []).push({ key, label: meta.label, category: cat });
        });

        let html = "";
        Object.entries(CATEGORY_LABELS).forEach(([cat, catLabel]) => {
            const items = grouped[cat] || [];
            if (!items.length) return;

            html += `<div class="card">
                <div class="card-title">${catLabel}</div>`;
            items.forEach((item) => {
                const pref = prefs[item.key] || {};
                const checked = pref.enabled !== false ? "checked" : "";
                const disabled = item.category === "critical" ? "disabled" : "";
                html += `<div class="manage-item">
                    <span style="flex:1">${item.label}</span>
                    <label class="toggle-switch">
                        <input type="checkbox" ${checked} ${disabled}
                            onchange="Notifications.toggleNotification('${item.key}', this.checked)">
                        <span class="toggle-slider"></span>
                    </label>
                </div>`;
            });
            html += `</div>`;
        });

        container.innerHTML = html || '<div class="hint-text">Немає типів сповіщень</div>';
    }

    function _populateQuietHours(prefs) {
        // Find first preference that has quiet hours set
        let start = "", end = "";
        Object.values(prefs).forEach((p) => {
            if (!start && p.quiet_hours_start) start = p.quiet_hours_start;
            if (!end && p.quiet_hours_end) end = p.quiet_hours_end;
        });
        const startEl = _el("notif-quiet-start");
        const endEl = _el("notif-quiet-end");
        if (startEl) startEl.value = start || "22:00";
        if (endEl) endEl.value = end || "08:00";
    }

    // -----------------------------------------------------------------------
    // Toggle individual notification type
    // -----------------------------------------------------------------------

    async function toggleNotification(notificationType, enabled) {
        try {
            const res = await API.setNotificationPreference(notificationType, enabled, null, null);
            _showToast(res.message || "Збережено", "success");
        } catch (e) {
            _showToast("❌ " + e.message, "error");
            await load();
        }
    }

    // -----------------------------------------------------------------------
    // Save quiet hours
    // -----------------------------------------------------------------------

    async function saveQuietHours() {
        const start = (_el("notif-quiet-start") || {}).value || "";
        const end = (_el("notif-quiet-end") || {}).value || "";
        try {
            const res = await API.setNotificationPreference("fuel_warning", true, start || null, end || null);
            _showToast(res.message || "Тихий час збережено", "success");
        } catch (e) {
            _showToast("❌ " + e.message, "error");
        }
    }

    // -----------------------------------------------------------------------
    // Test notification
    // -----------------------------------------------------------------------

    async function testNotification() {
        try {
            const res = await API.testNotification();
            _showToast(res.message || "Тест відправлено", "success");
        } catch (e) {
            _showToast("❌ " + e.message, "error");
        }
    }

    return { load, toggleNotification, saveQuietHours, testNotification };
})();
