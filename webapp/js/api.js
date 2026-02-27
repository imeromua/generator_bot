/**
 * API-клієнт для Mini App генератора.
 * Відповідає за взаємодію з бекендом.
 */

const API = (() => {
    "use strict";

    // Базовий URL визначається автоматично (відносний)
    const BASE = "";

    /**
     * Повертає заголовки для запиту (включно з Telegram initData).
     */
    function _headers() {
        const h = { "Content-Type": "application/json" };
        if (window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.initData) {
            h["X-Telegram-Init-Data"] = window.Telegram.WebApp.initData;
        }
        return h;
    }

    /**
     * GET-запит до API.
     */
    async function get(path, params) {
        let url = BASE + path;
        if (params) {
            const qs = new URLSearchParams(params).toString();
            if (qs) url += "?" + qs;
        }
        let resp;
        try {
            resp = await fetch(url, { headers: _headers() });
        } catch (e) {
            if (e instanceof TypeError) {
                throw new Error("Немає з'єднання з сервером. Перевірте інтернет.");
            }
            throw e;
        }
        if (!resp.ok) {
            const body = await resp.json().catch(() => ({}));
            throw new Error(body.error || `HTTP ${resp.status}: ${resp.statusText}`);
        }
        return resp.json();
    }

    /**
     * POST-запит до API.
     */
    async function post(path, data) {
        let resp;
        try {
            resp = await fetch(BASE + path, {
                method: "POST",
                headers: _headers(),
                body: JSON.stringify(data || {}),
            });
        } catch (e) {
            if (e instanceof TypeError) {
                throw new Error("Немає з'єднання з сервером. Перевірте інтернет.");
            }
            throw e;
        }
        if (!resp.ok) {
            const body = await resp.json().catch(() => ({}));
            throw new Error(body.error || `HTTP ${resp.status}: ${resp.statusText}`);
        }
        return resp.json();
    }

    /**
     * DELETE-запит до API.
     */
    async function _delete(path, data) {
        let resp;
        try {
            resp = await fetch(BASE + path, {
                method: "DELETE",
                headers: _headers(),
                body: JSON.stringify(data || {}),
            });
        } catch (e) {
            if (e instanceof TypeError) {
                throw new Error("Немає з'єднання з сервером. Перевірте інтернет.");
            }
            throw e;
        }
        if (!resp.ok) {
            const body = await resp.json().catch(() => ({}));
            throw new Error(body.error || `HTTP ${resp.status}: ${resp.statusText}`);
        }
        return resp.json();
    }

    return {
        // --- GET ---
        /** Стан генератора */
        getStatus: () => get("/api/status"),
        /** Графік відключень на дату */
        getSchedule: (date) => get("/api/schedule", date ? { date } : undefined),
        /** Тижневий огляд */
        getWeek: () => get("/api/schedule/week"),
        /** Останні події */
        getEvents: (limit) => get("/api/events", limit ? { limit } : undefined),
        /** Стан ТО */
        getMaintenance: () => get("/api/maintenance"),
        /** Роль поточного користувача */
        getUserRole: () => get("/api/user/role"),
        /** Список водіїв */
        getDrivers: () => get("/api/drivers"),
        /** Статистика генераторів */
        getGenerators: () => get("/api/generators"),
        /** Персонал поточного користувача */
        getPersonnelMe: () => get("/api/personnel/me"),
        /** Завантаження Excel-звіту (повертає URL) */
        getReportUrl: (days, generator) => {
            let url = BASE + "/api/report/excel?days=" + (days || "30");
            if (generator) url += "&generator=" + encodeURIComponent(generator);
            return url;
        },

        // --- Admin CRUD ---
        /** Список водіїв (адмін) */
        adminGetDrivers: () => get("/api/admin/drivers"),
        /** Список персоналу (адмін) */
        adminGetPersonnel: () => get("/api/admin/personnel"),
        /** Синхронізація з Google Sheets */
        adminSync: () => post("/api/admin/sync", {}),

        // --- POST ---
        /** Старт зміни */
        startShift: (shift) => post("/api/action/start", { shift }),
        /** Зупинка зміни */
        stopShift: (shift) => post("/api/action/stop", { shift }),
        /** Прийом палива */
        refuel: (driver, liters, receipt) => post("/api/action/refill", { driver, liters, receipt }),
        /** Перемикання години графіка */
        toggleSchedule: (date, hour) => post("/api/schedule/toggle", { date, hour }),
        /** Перемикання генератора */
        switchGenerator: (target) => post("/api/generator/switch", { target }),
        /** Виконання ТО */
        performMaintenance: (action, generator) => post("/api/maintenance/perform", { action, generator }),
        /** Встановлення мотогодин */
        setHours: (generator, hours) => post("/api/maintenance/set-hours", { generator, hours }),
        /** Встановлення рівня палива */
        setFuel: (fuel) => post("/api/fuel/set", { fuel }),
        /** Додати водія */
        adminAddDriver: (name) => post("/api/admin/drivers", { name }),
        /** Видалити водія */
        adminDeleteDriver: (name) => _delete("/api/admin/drivers", { name }),
        /** Додати персонал */
        adminAddPersonnel: (name) => post("/api/admin/personnel", { name }),
        /** Видалити персонал */
        adminDeletePersonnel: (name) => _delete("/api/admin/personnel", { name }),
        /** Прив'язати персонал до користувача */
        adminAssignPersonnel: (user_id, personnel) => post("/api/admin/personnel/assign", { user_id, personnel }),

        // Task 5: Notification preferences
        /** Отримати налаштування сповіщень */
        getNotificationPreferences: () => get("/api/notifications/preferences"),
        /** Зберегти налаштування сповіщення */
        setNotificationPreference: (notification_type, enabled, quiet_hours_start, quiet_hours_end) =>
            post("/api/notifications/preferences", { notification_type, enabled, quiet_hours_start, quiet_hours_end }),
        /** Тест сповіщення */
        testNotification: () => post("/api/notifications/test", {}),

        // Task 6: Fuel orders
        /** Список замовлень палива */
        getFuelOrders: (status) => get("/api/fuel/orders", status ? { status } : undefined),
        /** Створити замовлення палива */
        createFuelOrder: (data) => post("/api/fuel/orders", data),
        /** Оновити статус замовлення */
        updateFuelOrder: (data) => post("/api/fuel/orders/update", data),

        // Task 8: Shift schedule
        /** Отримати розклад змін */
        getShifts: (params) => get("/api/shifts/schedule", params),
        /** Зберегти зміну */
        setShift: (data) => post("/api/shifts/schedule", data),
        /** Авто-планування */
        autoSchedule: (month, save) => post("/api/shifts/auto", { month, save }),
        /** Аналітика змін */
        getShiftAnalytics: (month) => get("/api/shifts/analytics", month ? { month } : undefined),
    };
})();

