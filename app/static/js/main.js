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
        try {
            const headers = {};
            if (etag) headers["If-None-Match"] = etag;
            const res = await fetch("/messenger/api/unread-count", { headers });
            if (res.status === 304) return;
            if (!res.ok) return;
            etag = res.headers.get("ETag") || etag;
            const data = await res.json();
            applyTotal(data.total || 0, data.preview || null);
        } catch {
            /* ignore */
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

    refresh();
    setInterval(refresh, intervalMs);
}
