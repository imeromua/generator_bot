/**
 * API-клієнт для Mini App генератора.
 * Відповідає за взаємодію з бекендом.
 */

const API = (() => {
    "use strict";

    // Базовий URL визначається автоматично (відносний)
    const BASE = "";

    /**
     * Виконати GET-запит до API.
     * @param {string} path — шлях (наприклад, "/api/status")
     * @param {Object} [params] — query-параметри
     * @returns {Promise<Object>} — JSON-відповідь
     */
    async function get(path, params) {
        let url = BASE + path;
        if (params) {
            const qs = new URLSearchParams(params).toString();
            if (qs) url += "?" + qs;
        }

        const headers = {};

        // Telegram WebApp initData для авторизації
        if (window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.initData) {
            headers["X-Telegram-Init-Data"] = window.Telegram.WebApp.initData;
        }

        const resp = await fetch(url, { headers });

        if (!resp.ok) {
            const body = await resp.json().catch(() => ({}));
            throw new Error(body.error || `HTTP ${resp.status}`);
        }

        return resp.json();
    }

    return {
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
    };
})();
