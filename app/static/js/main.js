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
    const shell = document.getElementById("appShell");
    if (!loading || !shell) return;

    const CACHE_TTL = 45000;
    const OVERLAY_MS = 400;
    const pageCache = new Map();
    const SHELL_ASSET = /bootstrap|main\.css|main\.js|opora-list|phone-mask|search\.js|search\.css|requests-form/;
    const SKELETON =
        '<div class="opora-loading" role="status"><div class="spinner-border text-primary"></div><div class="opora-loading__text">Загрузка…</div></div>';

    let navAbort = null;
    let navToken = 0;
    let overlayTimer = 0;

    function cacheKey(href) {
        const url = new URL(href, window.location.href);
        url.hash = "";
        return url.pathname + url.search;
    }

    function cacheGet(href) {
        const item = pageCache.get(cacheKey(href));
        if (!item || Date.now() - item.t > CACHE_TTL) {
            if (item) pageCache.delete(cacheKey(href));
            return null;
        }
        return item.html;
    }

    function cacheSet(href, html) {
        pageCache.set(cacheKey(href), { html, t: Date.now() });
        if (pageCache.size > 24) {
            pageCache.delete(pageCache.keys().next().value);
        }
    }

    function mustFullReload(url) {
        const path = url.pathname;
        return (
            path.startsWith("/messenger") ||
            path.startsWith("/auth/") ||
            path.includes("/download") ||
            path.includes("/export") ||
            path.includes("/file/")
        );
    }

    function spaTarget(link, event) {
        if (!link || link.classList.contains("sidebar__link--disabled")) return null;
        if (event.defaultPrevented) return null;
        if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return null;
        if (link.target && link.target !== "_self") return null;
        if (link.hasAttribute("download")) return null;
        if (link.dataset.bsToggle || link.getAttribute("data-bs-toggle")) return null;
        const href = link.getAttribute("href");
        if (!href || href === "#" || href.startsWith("javascript:") || href.startsWith("mailto:") || href.startsWith("tel:")) {
            return null;
        }
        const next = new URL(href, window.location.href);
        if (next.origin !== window.location.origin) return null;
        if (mustFullReload(next)) return null;
        return next;
    }

    const hideLoading = () => {
        window.clearTimeout(overlayTimer);
        document.body.classList.remove("is-page-loading");
        loading.hidden = true;
    };

    const showSkeleton = (label) => {
        const content = document.getElementById("appContent") || document.querySelector(".app-content");
        if (content) content.innerHTML = SKELETON;
        closeSidebar();
        window.clearTimeout(overlayTimer);
        overlayTimer = window.setTimeout(() => {
            document.body.classList.add("is-page-loading");
            if (loadingTitle) loadingTitle.textContent = label || "Загрузка";
            loading.hidden = false;
        }, OVERLAY_MS);
    };

    const markSidebar = (href) => {
        const next = new URL(href, window.location.href);
        sidebar.querySelectorAll(".sidebar__link").forEach((item) => {
            const itemHref = item.getAttribute("href");
            if (!itemHref || itemHref === "#") {
                item.classList.remove("active");
                return;
            }
            const url = new URL(itemHref, window.location.href);
            const base = url.pathname.replace(/\/$/, "") || "/";
            const active =
                base === "/"
                    ? next.pathname === "/"
                    : next.pathname === url.pathname ||
                      next.pathname === base ||
                      next.pathname.startsWith(`${base}/`);
            item.classList.toggle("active", active);
        });
    };

    function assetName(url) {
        return (url || "").split("/").pop().split("?")[0];
    }

    function hasScript(src) {
        const name = assetName(src);
        return [...document.scripts].some((item) => (item.src || "").includes(name));
    }

    function hasCss(href) {
        const abs = new URL(href, window.location.href).href;
        return [...document.querySelectorAll("link[rel='stylesheet']")].some((item) => item.href === abs);
    }

    function injectCss(href) {
        return new Promise((resolve) => {
            if (hasCss(href)) {
                resolve();
                return;
            }
            const link = document.createElement("link");
            link.rel = "stylesheet";
            link.href = href;
            link.onload = () => resolve();
            link.onerror = () => resolve();
            document.head.appendChild(link);
        });
    }

    function injectScript(src) {
        return new Promise((resolve) => {
            if (hasScript(src)) {
                resolve();
                return;
            }
            const script = document.createElement("script");
            script.src = src;
            script.onload = () => resolve();
            script.onerror = () => resolve();
            document.body.appendChild(script);
        });
    }

    async function ensureAssets(doc) {
        const css = [...doc.querySelectorAll("link[rel='stylesheet']")]
            .map((el) => el.getAttribute("href"))
            .filter((href) => href && !SHELL_ASSET.test(href));
        const scripts = [...doc.querySelectorAll("script[src]")]
            .map((el) => el.getAttribute("src"))
            .filter((src) => src && !SHELL_ASSET.test(src));
        await Promise.all(css.map(injectCss));
        for (const src of scripts) {
            await injectScript(src);
        }
    }

    function bootPageModules() {
        window.OporaList?.reset?.();
        window.OporaList?.bootPage?.();
        if (window.OporaRequestsForm?.init) {
            document.querySelectorAll("[data-requests-form]").forEach((form) => {
                delete form.dataset.requestsInited;
                window.OporaRequestsForm.init(form);
            });
        }
        if (document.getElementById("agreementMap")) {
            window.OporaAgreementMap?.init?.();
        }
        if (document.getElementById("auditFilterForm")) {
            window.OporaAudit?.init?.();
        }
        if (document.getElementById("requestMap")) {
            window.OporaRequestDetail?.init?.();
        }
        initFlashMessages();
    }

    async function applyHtml(html) {
        const doc = new DOMParser().parseFromString(html, "text/html");
        const nextContent = doc.querySelector("#appContent, .app-content");
        const currentContent = document.querySelector("#appContent, .app-content");
        if (!nextContent || !currentContent) return false;
        document.title = doc.title;
        nextContent.querySelectorAll("script").forEach((node) => node.remove());
        currentContent.replaceWith(nextContent);
        await ensureAssets(doc);
        bootPageModules();
        return true;
    }

    function isHtmlNavResponse(response) {
        const ct = (response.headers.get("content-type") || "").toLowerCase();
        if (!ct.includes("text/html")) return false;
        const disp = (response.headers.get("content-disposition") || "").toLowerCase();
        return !disp.includes("attachment");
    }

    function fetchPage(href, signal) {
        return fetch(href, {
            credentials: "same-origin",
            headers: {
                "X-Opora-Nav": "1",
                "X-Requested-With": "OporaNav",
                Accept: "text/html",
            },
            signal,
        });
    }

    async function navigateTo(href, label, { push = true } = {}) {
        const token = ++navToken;
        navAbort?.abort();
        navAbort = new AbortController();
        markSidebar(href);
        closeSidebar();

        const cached = cacheGet(href);
        if (cached) {
            hideLoading();
            const ok = await applyHtml(cached);
            if (token !== navToken) return;
            if (!ok) {
                window.location.href = href;
                return;
            }
            if (push) history.pushState({ oporaNav: true }, "", href);
            return;
        }

        showSkeleton(label);
        try {
            const response = await fetchPage(href, navAbort.signal);
            if (token !== navToken) return;
            const finalUrl = response.url || href;
            if (
                !response.ok ||
                (response.redirected && /\/auth\/login/.test(finalUrl)) ||
                !isHtmlNavResponse(response)
            ) {
                window.location.href = href;
                return;
            }
            const html = await response.text();
            if (token !== navToken) return;
            const ok = await applyHtml(html);
            if (token !== navToken) return;
            if (!ok) {
                window.location.href = href;
                return;
            }
            cacheSet(href, html);
            if (push) history.pushState({ oporaNav: true }, "", href);
            hideLoading();
        } catch (err) {
            if (err?.name === "AbortError" || token !== navToken) return;
            window.location.href = href;
        }
    }

    window.OporaNav = {
        go(href, label) {
            const next = new URL(href, window.location.href);
            if (next.origin !== window.location.origin || mustFullReload(next)) {
                window.location.href = next.href;
                return;
            }
            navigateTo(next.href, label || "Загрузка");
        },
    };

    function prefetch(href) {
        if (cacheGet(href)) return;
        const url = new URL(href, window.location.href);
        if (url.origin !== window.location.origin || mustFullReload(url)) return;
        fetchPage(href).then(async (response) => {
            if (!response.ok || !isHtmlNavResponse(response)) return;
            const html = await response.text();
            if (html.includes("app-content")) cacheSet(href, html);
        }).catch(() => {});
    }

    window.addEventListener("pageshow", hideLoading);
    window.addEventListener("pagehide", () => {
        navAbort?.abort();
        hideLoading();
    });
    window.addEventListener("popstate", () => {
        navigateTo(window.location.href, "Загрузка", { push: false });
    });
    history.replaceState({ oporaNav: true }, "", window.location.href);

    shell.addEventListener("click", (event) => {
        const link = event.target.closest("a[href]");
        const next = spaTarget(link, event);
        if (!next) return;
        if (next.pathname === window.location.pathname && next.search === window.location.search) {
            event.preventDefault();
            return;
        }
        event.preventDefault();
        const label =
            link.querySelector("span:not(.sidebar__badge)")?.textContent?.trim() ||
            link.textContent?.trim() ||
            "Загрузка";
        navigateTo(next.href, label);
    });

    sidebar.addEventListener("pointerover", (event) => {
        const link = event.target.closest("a[href]");
        if (!link || !sidebar.contains(link)) return;
        const href = link.getAttribute("href");
        if (!href || href === "#") return;
        prefetch(href);
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
