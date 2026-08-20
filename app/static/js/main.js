/**
 * Опора — основной JavaScript
 */

document.addEventListener("DOMContentLoaded", () => {
    initFlashMessages();
    initSidebar();
    initSearchShortcut();
    initMessengerUnreadBadge();
});

window.OporaMessengerNotify = (() => {
    let audioCtx = null;
    let lastNotifiedMessageId = null;
    let permissionAsked = false;

    function ensureAudio() {
        if (audioCtx) return audioCtx;
        const Ctx = window.AudioContext || window.webkitAudioContext;
        if (!Ctx) return null;
        audioCtx = new Ctx();
        return audioCtx;
    }

    function playSound() {
        try {
            const ctx = ensureAudio();
            if (!ctx) return;
            if (ctx.state === "suspended") ctx.resume();
            const now = ctx.currentTime;
            [
                { freq: 880, start: 0, dur: 0.12 },
                { freq: 1175, start: 0.1, dur: 0.16 },
            ].forEach(({ freq, start, dur }) => {
                const osc = ctx.createOscillator();
                const gain = ctx.createGain();
                osc.type = "sine";
                osc.frequency.value = freq;
                gain.gain.setValueAtTime(0.0001, now + start);
                gain.gain.exponentialRampToValueAtTime(0.07, now + start + 0.02);
                gain.gain.exponentialRampToValueAtTime(0.0001, now + start + dur);
                osc.connect(gain);
                gain.connect(ctx.destination);
                osc.start(now + start);
                osc.stop(now + start + dur + 0.02);
            });
        } catch {
            /* ignore */
        }
    }

    function requestPermission() {
        if (!("Notification" in window)) return;
        if (Notification.permission !== "default" || permissionAsked) return;
        permissionAsked = true;
        Notification.requestPermission().catch(() => {});
    }

    function showBrowserNotification({ title, body, url, tag }) {
        if (!("Notification" in window)) return;
        if (Notification.permission !== "granted") return;
        try {
            const n = new Notification(title || "Новое сообщение", {
                body: body || "",
                tag: tag || "opora-messenger",
                renotify: true,
                silent: true,
            });
            n.onclick = () => {
                window.focus();
                if (url) window.location.href = url;
                n.close();
            };
            setTimeout(() => n.close(), 8000);
        } catch {
            /* ignore */
        }
    }

    /**
     * Звук + браузерное уведомление о входящем сообщении.
     * skipUiNoise — если пользователь уже смотрит этот чат во вкладке.
     */
    function notifyNewMessage({ title, body, url, messageId, conversationId, skipSound, skipBrowser }) {
        if (messageId && messageId === lastNotifiedMessageId) return;
        if (messageId) lastNotifiedMessageId = messageId;

        if (!skipSound) playSound();
        if (!skipBrowser) {
            showBrowserNotification({
                title: title || "Новое сообщение",
                body: body || "",
                url: url || "/messenger/",
                tag: conversationId ? `msg-${conversationId}` : "opora-messenger",
            });
        }
    }

    function onUnreadIncrease(total, preview, options = {}) {
        if (!preview && total <= 0) return;
        const activeId = options.activeConversationId || null;
        const viewingChat =
            !document.hidden &&
            preview?.conversation_id &&
            activeId &&
            String(activeId) === String(preview.conversation_id);

        notifyNewMessage({
            title: preview?.peer_name || "Мессенджер",
            body: preview?.body || `Непрочитанных: ${total}`,
            url: "/messenger/",
            messageId: preview?.message_id || null,
            conversationId: preview?.conversation_id || null,
            skipSound: viewingChat,
            skipBrowser: viewingChat,
        });
    }

    return {
        playSound,
        requestPermission,
        notifyNewMessage,
        onUnreadIncrease,
    };
})();

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

    initInstantNav(sidebar, closeSidebar);
}

function initInstantNav(sidebar, closeSidebar) {
    const loading = document.getElementById("pageLoading");
    const loadingTitle = document.getElementById("pageLoadingTitle");
    if (!loading) return;

    const hideLoading = () => {
        document.body.classList.remove("is-page-loading");
        loading.hidden = true;
    };

    window.addEventListener("pageshow", hideLoading);
    window.addEventListener("pagehide", hideLoading);

    const prefetched = new Set();
    function prefetch(href) {
        if (!href || prefetched.has(href)) return;
        prefetched.add(href);
        const hint = document.createElement("link");
        hint.rel = "prefetch";
        hint.href = href;
        hint.as = "document";
        document.head.appendChild(hint);
    }

    sidebar.addEventListener("pointerenter", (event) => {
        const link = event.target.closest?.("a[href]");
        if (!link || link.classList.contains("sidebar__link--disabled")) return;
        const href = link.getAttribute("href");
        if (!href || href === "#" || href.startsWith("javascript:")) return;
        prefetch(new URL(href, window.location.href).href);
        const page = new URL(href, window.location.href);
        if (page.pathname.endsWith("/")) {
            prefetch(new URL("table", page).href);
        }
    }, true);

    sidebar.addEventListener("click", (event) => {
        const link = event.target.closest("a[href]");
        if (!link || link.classList.contains("sidebar__link--disabled")) return;
        if (event.defaultPrevented) return;
        if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;

        const href = link.getAttribute("href");
        if (!href || href === "#" || href.startsWith("javascript:")) return;

        const next = new URL(href, window.location.href);
        if (next.origin !== window.location.origin) return;
        if (
            next.pathname === window.location.pathname &&
            next.search === window.location.search
        ) {
            return;
        }

        const label =
            link.querySelector("span:not(.sidebar__badge)")?.textContent?.trim() ||
            "Загрузка";
        document.body.classList.add("is-page-loading");
        sidebar.querySelectorAll(".sidebar__link.active").forEach((item) => {
            item.classList.remove("active");
        });
        link.classList.add("active");
        if (loadingTitle) loadingTitle.textContent = label;
        loading.hidden = false;
        closeSidebar();
        window.setTimeout(hideLoading, 8000);
    });
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
    let lastTotal = null;
    const intervalMs = Number(
        document.body?.dataset?.messengerUnreadInterval || 15000
    );
    const onMessengerPage = Boolean(document.getElementById("messengerApp"));
    // messenger.js owns unread polling on its page; do not start a second loop.
    if (onMessengerPage) return;

    const abort = new AbortController();
    window.addEventListener("pagehide", () => abort.abort(), { once: true });

    function applyTotal(total, preview) {
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

        if (
            !onMessengerPage &&
            lastTotal !== null &&
            total > lastTotal &&
            window.OporaMessengerNotify
        ) {
            window.OporaMessengerNotify.onUnreadIncrease(total, preview || null);
        }
        lastTotal = total;
    }

    async function refresh() {
        if (document.hidden) return;
        try {
            const headers = {};
            if (etag) headers["If-None-Match"] = etag;
            const res = await fetch("/messenger/api/unread-count", {
                headers,
                signal: abort.signal,
                priority: "low",
            });
            if (res.status === 304) return;
            if (!res.ok) return;
            etag = res.headers.get("ETag") || etag;
            const data = await res.json();
            applyTotal(data.total || 0, data.preview || null);
        } catch {
            /* ignore abort / network */
        }
    }

    document.addEventListener(
        "click",
        () => window.OporaMessengerNotify?.requestPermission(),
        { once: true }
    );

    document.addEventListener("visibilitychange", () => {
        if (!document.hidden) refresh();
    });

    // Не конкурировать с CSS/JS на первом кадре страницы.
    window.setTimeout(refresh, 2500);
    window.setInterval(() => {
        if (!document.hidden) refresh();
    }, intervalMs);
}
