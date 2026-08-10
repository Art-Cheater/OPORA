/**
 * Опора — основной JavaScript
 */

document.addEventListener("DOMContentLoaded", () => {
    initFlashMessages();
    initSidebar();
    initSearchShortcut();
    initMessengerUnreadBadge();
});

function initFlashMessages() {
    document.querySelectorAll(".alert:not(.alert-danger)").forEach((alert) => {
        setTimeout(() => {
            const bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
            bsAlert.close();
        }, 5000);
    });
}

function initSidebar() {
    const sidebar = document.getElementById("sidebar");
    const overlay = document.getElementById("sidebarOverlay");
    const toggle = document.getElementById("sidebarToggle");
    const close = document.getElementById("sidebarClose");

    if (!sidebar) return;

    const openSidebar = () => {
        sidebar.classList.add("open");
        overlay?.classList.add("show");
        document.body.style.overflow = "hidden";
    };

    const closeSidebar = () => {
        sidebar.classList.remove("open");
        overlay?.classList.remove("show");
        document.body.style.overflow = "";
    };

    toggle?.addEventListener("click", openSidebar);
    close?.addEventListener("click", closeSidebar);
    overlay?.addEventListener("click", closeSidebar);
}

function initSearchShortcut() {
    const searchInput = document.getElementById("globalSearchInput") || document.querySelector(".topbar__search-input");
    if (!searchInput || searchInput.id === "globalSearchInput") return;

    document.addEventListener("keydown", (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === "k") {
            e.preventDefault();
            searchInput.focus();
        }
    });
}

function initMessengerUnreadBadge() {
    const badge = document.getElementById("messengerUnreadBadge");
    const dot = document.getElementById("topbarMessengerDot");
    if (!badge && !dot) return;

    let etag = null;
    const intervalMs = Number(
        document.body?.dataset?.messengerUnreadInterval || 45000
    );

    async function refresh() {
        if (document.hidden) return;
        try {
            const headers = {};
            if (etag) headers["If-None-Match"] = etag;
            const res = await fetch("/messenger/api/unread-count", { headers });
            if (res.status === 304) return;
            if (!res.ok) return;
            etag = res.headers.get("ETag") || etag;
            const data = await res.json();
            const total = data.total || 0;
            if (badge) {
                if (total > 0) {
                    badge.textContent = total > 99 ? "99+" : String(total);
                    badge.classList.remove("d-none");
                } else {
                    badge.classList.add("d-none");
                }
            }
            if (dot) {
                dot.classList.toggle("d-none", total === 0);
            }
        } catch {
            /* ignore */
        }
    }

    refresh();
    setInterval(refresh, intervalMs);
}
