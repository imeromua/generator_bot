/**
 * Settings page — System Configuration UI.
 * Manages fuel consumption rates for generators and fuel price.
 */

(function () {
    "use strict";

    // -------------------------------------------------------------------
    // Telegram WebApp перевірка доступу
    // -------------------------------------------------------------------
    const tg = window.Telegram && window.Telegram.WebApp;
    if (!tg || !tg.initData) {
        if (!window.location.pathname.includes("block.html")) {
            window.location.href = "/block.html";
        }
        return;
    }

    if (window._tgCheckTimer) clearTimeout(window._tgCheckTimer);
    const _splash = document.getElementById("tg-check-splash");
    if (_splash) _splash.remove();
    const _appEl = document.getElementById("app");
    if (_appEl) _appEl.style.display = "";

    if (tg) {
        tg.ready();
        tg.expand();
    }

    // -------------------------------------------------------------------
    // Стан
    // -------------------------------------------------------------------
    let _editingGenerator = null; // "main" | "emergency"
    let _currentConfig = null;

    // -------------------------------------------------------------------
    // Допоміжні функції
    // -------------------------------------------------------------------

    function $(id) { return document.getElementById(id); }

    function showToast(msg, type) {
        const el = document.createElement("div");
        el.className = "toast" + (type === "success" ? " toast-success" : "");
        el.textContent = msg;
        document.body.appendChild(el);
        setTimeout(() => el.remove(), 3500);
    }

    function showSuccess(msg) { showToast(msg, "success"); }
    function showError(msg) { showToast(msg, "error"); }

    function escapeHtml(str) {
        if (!str) return "";
        const div = document.createElement("div");
        div.textContent = str;
        return div.innerHTML;
    }

    function generatorLabel(id) {
        return id === "emergency" ? "Аварійний генератор" : "Основний генератор";
    }

    function paramLabel(configType, entityId, paramName) {
        if (paramName === "fuel_consumption_rate") {
            const gen = entityId === "emergency" ? "аварійного" : "основного";
            return `Витрати палива ${gen} генератора`;
        }
        if (paramName === "fuel_price") return "Вартість палива";
        return paramName;
    }

    function formatValue(val, paramName) {
        if (val === null || val === undefined) return "—";
        const num = parseFloat(val);
        if (isNaN(num)) return "—";
        return num.toFixed(1);
    }

    function unitFor(paramName) {
        if (paramName === "fuel_consumption_rate") return "л/год";
        if (paramName === "fuel_price") return "грн/л";
        return "";
    }

    // -------------------------------------------------------------------
    // Завантаження даних
    // -------------------------------------------------------------------

    async function loadConfig() {
        try {
            const data = await API.adminGetConfig();
            _currentConfig = data;

            // Основний генератор
            const mainRate = data.generators?.main?.fuel_consumption_rate;
            if (mainRate) {
                $("main-fuel-rate").textContent = formatValue(mainRate.value, "fuel_consumption_rate");
            }

            // Аварійний генератор
            const emergRate = data.generators?.emergency?.fuel_consumption_rate;
            if (emergRate) {
                $("emergency-fuel-rate").textContent = formatValue(emergRate.value, "fuel_consumption_rate");
            }

            // Вартість палива
            const fuelPrice = data.global?.fuel_price;
            if (fuelPrice) {
                $("fuel-price").textContent = formatValue(fuelPrice.value, "fuel_price");
                const meta = fuelPrice.last_updated
                    ? `Оновлено: ${escapeHtml(fuelPrice.last_updated)}`
                    : "";
                $("fuel-price-meta").textContent = meta;
            }
        } catch (e) {
            showError("Помилка завантаження налаштувань: " + e.message);
        }
    }

    async function loadHistory() {
        const listEl = $("history-list");
        const emptyEl = $("history-empty");
        try {
            const data = await API.adminGetConfigHistory(20);
            const history = data.history || [];

            if (!history.length) {
                emptyEl.style.display = "";
                return;
            }
            emptyEl.style.display = "none";

            // Render items
            const items = history.map((h) => {
                const entityLabel = h.config_type === "generator"
                    ? generatorLabel(h.entity_id)
                    : "Глобальні налаштування";
                const label = paramLabel(h.config_type, h.entity_id, h.param_name);
                const unit = unitFor(h.param_name);
                const oldVal = h.old_value !== null && h.old_value !== undefined
                    ? `${formatValue(h.old_value, h.param_name)} ${unit}`
                    : "—";
                const newVal = `${formatValue(h.new_value, h.param_name)} ${unit}`;
                const byName = h.changed_by_name ? `@${escapeHtml(h.changed_by_name)}` : "—";
                const date = escapeHtml(h.changed_at || "");

                return `<div class="history-item">
  <div class="history-item-date">${date}</div>
  <div class="history-item-entity">${escapeHtml(entityLabel)}</div>
  <div class="history-item-change">
    ${escapeHtml(label)}:
    <span class="old-val">${escapeHtml(oldVal)}</span>
    → <span class="new-val">${escapeHtml(newVal)}</span>
  </div>
  <div class="history-item-by">Змінив: ${byName}</div>
</div>`;
            });

            // Replace empty placeholder with actual items
            listEl.innerHTML = items.join("");
        } catch (e) {
            emptyEl.textContent = "Помилка завантаження історії";
            emptyEl.style.display = "";
        }
    }

    // -------------------------------------------------------------------
    // Редагування витрат генератора
    // -------------------------------------------------------------------

    function openEditGenerator(generatorId) {
        _editingGenerator = generatorId;
        $("edit-gen-name-label").textContent = "Генератор: " + generatorLabel(generatorId);

        // Pre-fill with current value
        const cfg = _currentConfig?.generators?.[generatorId]?.fuel_consumption_rate;
        const input = $("edit-gen-input");
        input.value = cfg?.value != null ? cfg.value : "";
        $("edit-gen-error").classList.add("hidden");
        $("edit-gen-error").textContent = "";

        $("modal-edit-generator").classList.remove("hidden");
        input.focus();
    }

    function closeEditGenerator() {
        $("modal-edit-generator").classList.add("hidden");
        _editingGenerator = null;
    }

    async function saveGenerator() {
        const input = $("edit-gen-input");
        const errorEl = $("edit-gen-error");
        const btn = $("btn-save-gen");

        errorEl.classList.add("hidden");
        const raw = input.value.trim().replace(/,/g, ".");
        const value = parseFloat(raw);

        if (!raw || isNaN(value)) {
            errorEl.textContent = "Введіть числове значення";
            errorEl.classList.remove("hidden");
            return;
        }
        if (value < 3.0 || value > 15.0) {
            errorEl.textContent = "Значення має бути в діапазоні 3.0 — 15.0 л/год";
            errorEl.classList.remove("hidden");
            return;
        }

        btn.disabled = true;
        btn.textContent = "Збереження...";
        try {
            await API.adminSetGeneratorConfig(_editingGenerator, "fuel_consumption_rate", value);
            closeEditGenerator();
            showSuccess("✅ Налаштування збережено");
            await loadConfig();
            await loadHistory();
        } catch (e) {
            errorEl.textContent = e.message || "Помилка збереження";
            errorEl.classList.remove("hidden");
        } finally {
            btn.disabled = false;
            btn.textContent = "💾 Зберегти";
        }
    }

    // -------------------------------------------------------------------
    // Редагування вартості палива
    // -------------------------------------------------------------------

    function openEditFuelPrice() {
        const cfg = _currentConfig?.global?.fuel_price;
        const input = $("edit-price-input");
        input.value = cfg?.value != null ? cfg.value : "";
        $("edit-price-error").classList.add("hidden");
        $("edit-price-error").textContent = "";

        $("modal-edit-price").classList.remove("hidden");
        input.focus();
    }

    function closeEditFuelPrice() {
        $("modal-edit-price").classList.add("hidden");
    }

    async function saveFuelPrice() {
        const input = $("edit-price-input");
        const errorEl = $("edit-price-error");
        const btn = $("btn-save-price");

        errorEl.classList.add("hidden");
        const raw = input.value.trim().replace(/,/g, ".");
        const value = parseFloat(raw);

        if (!raw || isNaN(value)) {
            errorEl.textContent = "Введіть числове значення";
            errorEl.classList.remove("hidden");
            return;
        }
        if (value < 10.0 || value > 200.0) {
            errorEl.textContent = "Значення має бути в діапазоні 10.0 — 200.0 грн/л";
            errorEl.classList.remove("hidden");
            return;
        }

        btn.disabled = true;
        btn.textContent = "Збереження...";
        try {
            await API.adminSetGlobalConfig("fuel_price", value);
            closeEditFuelPrice();
            showSuccess("✅ Вартість палива збережено");
            await loadConfig();
            await loadHistory();
        } catch (e) {
            errorEl.textContent = e.message || "Помилка збереження";
            errorEl.classList.remove("hidden");
        } finally {
            btn.disabled = false;
            btn.textContent = "💾 Зберегти";
        }
    }

    // -------------------------------------------------------------------
    // Закриття модальних вікон при кліку поза ними
    // -------------------------------------------------------------------
    document.querySelectorAll(".modal-overlay").forEach((overlay) => {
        overlay.addEventListener("click", (e) => {
            if (e.target === overlay) {
                overlay.classList.add("hidden");
                _editingGenerator = null;
            }
        });
    });

    // -------------------------------------------------------------------
    // Перевірка ролі адміна та ініціалізація
    // -------------------------------------------------------------------
    async function init() {
        try {
            const role = await API.getUserRole();
            if (!role.is_admin) {
                document.getElementById("app").innerHTML =
                    '<div style="padding:32px 16px;text-align:center;color:#e74c3c;">' +
                    '<div style="font-size:48px;margin-bottom:16px">🔒</div>' +
                    '<div style="font-size:16px;font-weight:600">Доступ тільки для адміністраторів</div>' +
                    "</div>";
                return;
            }
        } catch (e) {
            showError("Помилка перевірки ролі: " + e.message);
        }

        await loadConfig();
        await loadHistory();
    }

    // -------------------------------------------------------------------
    // Публічний API для onclick-обробників в HTML
    // -------------------------------------------------------------------
    window.Settings = {
        openEditGenerator,
        closeEditGenerator,
        saveGenerator,
        openEditFuelPrice,
        closeEditFuelPrice,
        saveFuelPrice,
    };

    // Запуск
    init();
})();
