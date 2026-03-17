/**
 * User management UI for admin panel.
 * Provides CRUD operations on Telegram users through the /api/admin/users API.
 */

const UsersManager = (() => {
    "use strict";

    let _page = 1;
    let _perPage = 20;
    let _total = 0;
    let _searchTimeout = null;

    const ROLE_LABELS = {
        superadmin: "🔑 Супер-адмін",
        admin: "👨‍💼 Адміністратор",
        operator: "⚙️ Оператор",
        viewer: "👁️ Спостерігач",
        user: "👤 Користувач",
    };

    function getRoleLabel(role) {
        return ROLE_LABELS[role] || role || "—";
    }

    function formatDate(ts) {
        if (!ts) return "—";
        try {
            const d = new Date(ts);
            if (isNaN(d.getTime())) return ts;
            return d.toLocaleDateString("uk-UA", {
                day: "2-digit", month: "2-digit", year: "numeric",
                hour: "2-digit", minute: "2-digit",
            });
        } catch (e) {
            return ts;
        }
    }

    function _el(id) {
        return document.getElementById(id);
    }

    async function load(resetPage) {
        if (resetPage) _page = 1;

        const role = (_el("filter-role") || {}).value || "";
        const status = (_el("filter-status") || {}).value || "";
        const search = (_el("search-users") || {}).value || "";

        const params = { page: _page, per_page: _perPage };
        if (role) params.role = role;
        if (status !== "") params.is_active = status;
        if (search) params.search = search;

        const container = _el("users-list");
        if (container) container.innerHTML = '<div class="hint-text" style="text-align:center;padding:20px">Завантаження...</div>';

        try {
            const data = await API.adminGetUsers(params);
            _total = data.total || 0;
            _render(data.users || []);
            _renderPagination();
        } catch (e) {
            if (container) container.innerHTML = `<div class="hint-text" style="color:var(--color-danger)">❌ ${e.message}</div>`;
        }
    }

    function _render(users) {
        const container = _el("users-list");
        if (!container) return;

        if (!users.length) {
            container.innerHTML = '<div class="hint-text" style="text-align:center;padding:20px">Немає користувачів</div>';
            return;
        }

        const rows = users.map(u => {
            const displayName = [u.first_name, u.last_name].filter(Boolean).join(" ") || u.full_name || "—";
            const usernameHtml = u.username ? `<span class="hint-text">@${u.username}</span>` : "";
            const statusClass = u.is_active ? "badge-ok" : "badge-warn";
            const statusLabel = u.is_active ? "✅ Активний" : "🚫 Заблокований";
            const roleOptions = Object.entries(ROLE_LABELS).map(([val, lbl]) =>
                `<option value="${val}" ${u.role === val ? "selected" : ""}>${lbl}</option>`
            ).join("");

            return `
            <div class="manage-item" style="flex-direction:column;align-items:stretch;padding:12px;gap:8px">
                <div style="display:flex;align-items:center;gap:10px">
                    <div style="flex:1;min-width:0">
                        <div style="font-weight:600;font-size:14px">${displayName} ${usernameHtml}</div>
                        <div class="hint-text">ID: ${u.user_id} · ${getRoleLabel(u.role)} · <span class="${statusClass}">${statusLabel}</span></div>
                        <div class="hint-text" style="font-size:11px">Реєстрація: ${formatDate(u.registered_at)}</div>
                    </div>
                </div>
                <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center">
                    <select class="form-input" style="flex:1;min-width:120px;font-size:13px"
                        onchange="UsersManager.updateRole(${u.user_id}, this.value)">
                        ${roleOptions}
                    </select>
                    ${u.is_active
                        ? `<button class="btn btn-danger" style="font-size:12px;padding:6px 10px"
                            onclick="UsersManager.blockUser(${u.user_id})">🚫 Блок</button>`
                        : `<button class="btn btn-secondary" style="font-size:12px;padding:6px 10px"
                            onclick="UsersManager.unblockUser(${u.user_id})">✅ Розблок</button>`
                    }
                    <button class="btn btn-danger" style="font-size:12px;padding:6px 10px;background:var(--color-surface)"
                        onclick="UsersManager.deleteUser(${u.user_id})">🗑</button>
                </div>
            </div>`;
        }).join("");

        container.innerHTML = rows;
    }

    function _renderPagination() {
        const pag = _el("users-pagination");
        const info = _el("users-page-info");
        const prev = _el("btn-users-prev");
        const next = _el("btn-users-next");
        if (!pag) return;

        const totalPages = Math.ceil(_total / _perPage) || 1;
        if (_total <= _perPage) {
            pag.style.display = "none";
            return;
        }
        pag.style.display = "block";
        if (info) info.textContent = `Стор. ${_page} / ${totalPages} (всього: ${_total})`;
        if (prev) prev.disabled = _page <= 1;
        if (next) next.disabled = _page >= totalPages;
    }

    function prevPage() {
        if (_page > 1) { _page--; load(); }
    }

    function nextPage() {
        const totalPages = Math.ceil(_total / _perPage) || 1;
        if (_page < totalPages) { _page++; load(); }
    }

    async function updateRole(userId, role) {
        try {
            await API.adminUpdateUserRole(userId, role);
            if (typeof App !== "undefined" && App.showToast) {
                App.showToast("✅ Роль оновлено", "success");
            }
        } catch (e) {
            if (typeof App !== "undefined" && App.showToast) {
                App.showToast("❌ " + e.message, "error");
            }
            load();
        }
    }

    async function blockUser(userId) {
        const reason = prompt("🚫 Причина блокування (необов'язково):");
        if (reason === null) return; // cancelled
        try {
            await API.adminBlockUser(userId, reason || null);
            if (typeof App !== "undefined" && App.showToast) {
                App.showToast("✅ Користувача заблоковано", "success");
            }
            load();
        } catch (e) {
            if (typeof App !== "undefined" && App.showToast) {
                App.showToast("❌ " + e.message, "error");
            }
        }
    }

    async function unblockUser(userId) {
        try {
            await API.adminUnblockUser(userId);
            if (typeof App !== "undefined" && App.showToast) {
                App.showToast("✅ Користувача розблоковано", "success");
            }
            load();
        } catch (e) {
            if (typeof App !== "undefined" && App.showToast) {
                App.showToast("❌ " + e.message, "error");
            }
        }
    }

    async function deleteUser(userId) {
        if (!confirm("Видалити користувача? Запис буде позначено як видалений.")) return;
        try {
            await API.adminDeleteUser(userId);
            if (typeof App !== "undefined" && App.showToast) {
                App.showToast("✅ Користувача видалено", "success");
            }
            load();
        } catch (e) {
            if (typeof App !== "undefined" && App.showToast) {
                App.showToast("❌ " + e.message, "error");
            }
        }
    }

    function onSearchInput() {
        if (_searchTimeout) clearTimeout(_searchTimeout);
        _searchTimeout = setTimeout(() => load(true), 300);
    }

    return { load, prevPage, nextPage, updateRole, blockUser, unblockUser, deleteUser, onSearchInput };
})();
