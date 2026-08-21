/**
 * Опора — основной JavaScript
 */

document.addEventListener("DOMContentLoaded", () => {
    initFlashMessages();
    initSidebar();
    initSearchShortcut();
    initMessengerUnreadBadge();
});

window.OporaBusy = (() => {
    let depth = 0;

    function overlay() {
        return document.getElementById("oporaBusy");
    }

    function begin(title, hint) {
        depth += 1;
        const el = overlay();
        const titleEl = document.getElementById("oporaBusyTitle");
        const hintEl = document.getElementById("oporaBusyHint");
        if (titleEl && title) titleEl.textContent = title;
        if (hintEl && hint) hintEl.textContent = hint;
        document.body.classList.add("is-opora-busy");
        if (el) el.hidden = false;
    }

    function end() {
        depth = Math.max(0, depth - 1);
        if (depth > 0) return;
        document.body.classList.remove("is-opora-busy");
        const el = overlay();
        if (el) el.hidden = true;
    }

    function isBusy() {
        return depth > 0;
    }

    window.addEventListener(
        "click",
        (event) => {
            if (!isBusy()) return;
            if (event.target.closest("#oporaBusy")) return;
            event.preventDefault();
            event.stopPropagation();
        },
        true
    );
    window.addEventListener(
        "submit",
        (event) => {
            const form = event.target instanceof HTMLFormElement ? event.target : null;
            if (isBusy()) {
                event.preventDefault();
                event.stopPropagation();
                return;
            }
            if (form?.hasAttribute("data-opora-heavy")) {
                begin(
                    form.dataset.oporaHeavyTitle || "Обработка…",
                    form.dataset.oporaHeavyHint || "Дождитесь окончания операции"
                );
            }
        },
        true
    );
    window.addEventListener("keydown", (event) => {
        if (!isBusy()) return;
        if (event.key === "F5" || ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "r")) {
            event.preventDefault();
        }
    });

    return { begin, end, isBusy };
})();

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
    const LIST_SHELLS = {
        "/requests/": {
            title: "Заявки",
            subtitle: "Диспетчеризация: АБ → мастер → исполнение",
            icon: "clipboard-check",
            placeholder: "№, адрес, ПП, диспетчер…",
            loading: "Загрузка заявок…",
            baseUrl: "/requests",
            filterFormId: "requestFilterForm",
            tableContainerId: "requestsTableContainer",
            paginationContainerId: "requestsPaginationContainer",
            resetBtnId: "requestFilterReset",
            pageLinkClass: "request-page-link",
            viewMode: "page",
            createTitle: "Новая заявка",
        },
        "/objects/": {
            title: "Объекты",
            subtitle: "Адресные лоты работ",
            icon: "geo-alt",
            placeholder: "Наименование, адрес…",
            loading: "Загрузка объектов…",
            baseUrl: "/objects",
            filterFormId: "objectFilterForm",
            tableContainerId: "objectsTableContainer",
            paginationContainerId: "objectsPaginationContainer",
            resetBtnId: "objectFilterReset",
            pageLinkClass: "object-page-link",
            viewMode: "modal",
            createTitle: "Новый объект",
        },
        "/projects/": {
            title: "Проекты",
            subtitle: "Управление проектами предприятия",
            icon: "folder2-open",
            placeholder: "Код, название, описание…",
            loading: "Загрузка проектов…",
            baseUrl: "/projects",
            filterFormId: "projectFilterForm",
            tableContainerId: "projectsTableContainer",
            paginationContainerId: "projectsPaginationContainer",
            resetBtnId: "projectFilterReset",
            pageLinkClass: "project-page-link",
            viewMode: "modal",
            createTitle: "Новый проект",
        },
        "/tenders/": {
            title: "Заявки на торги",
            subtitle: "Пакеты проектов для закупок",
            icon: "hammer",
            placeholder: "Номер, название…",
            loading: "Загрузка торгов…",
            baseUrl: "/tenders",
            filterFormId: "tenderFilterForm",
            tableContainerId: "tendersTableContainer",
            paginationContainerId: "tendersPaginationContainer",
            resetBtnId: "tenderFilterReset",
            pageLinkClass: "tender-page-link",
            viewMode: "page",
            createTitle: "Новая заявка на торги",
        },
        "/contracts/": {
            title: "Контракты",
            subtitle: "Управление договорами предприятия",
            icon: "file-earmark-text",
            placeholder: "Номер, название…",
            loading: "Загрузка контрактов…",
            baseUrl: "/contracts",
            filterFormId: "contractFilterForm",
            tableContainerId: "contractsTableContainer",
            paginationContainerId: "contractsPaginationContainer",
            resetBtnId: "contractFilterReset",
            pageLinkClass: "contract-page-link",
            viewMode: "modal",
            createTitle: "Новый контракт",
        },
        "/contractors/": {
            title: "Подрядчики",
            subtitle: "Организации из контрактов и ЕИС",
            icon: "building",
            placeholder: "Название, ИНН, адрес…",
            loading: "Загрузка подрядчиков…",
            baseUrl: "/contractors",
            filterFormId: "contractorFilterForm",
            tableContainerId: "contractorsTableContainer",
            paginationContainerId: "contractorsPaginationContainer",
            resetBtnId: "contractorFilterReset",
            pageLinkClass: "contractor-page-link",
            viewMode: "page",
            createTitle: "Новый подрядчик",
        },
        "/employees/": {
            title: "Сотрудники",
            subtitle: "Управление персоналом",
            icon: "people",
            placeholder: "ФИО, email, должность…",
            loading: "Загрузка сотрудников…",
            baseUrl: "/employees",
            filterFormId: "employeeFilterForm",
            tableContainerId: "employeesTableContainer",
            paginationContainerId: "employeesPaginationContainer",
            resetBtnId: "employeeFilterReset",
            pageLinkClass: "employee-page-link",
            viewMode: "modal",
            createTitle: "Новый сотрудник",
        },
        "/inquiries/": {
            title: "Обращения",
            subtitle: "Письма с корпоративной почты",
            icon: "envelope",
            placeholder: "Тема или отправитель…",
            loading: "Загрузка писем…",
            baseUrl: "/inquiries",
            filterFormId: "inquiryFilterForm",
            tableContainerId: "inquiriesTableContainer",
            paginationContainerId: "inquiriesPaginationContainer",
            resetBtnId: "inquiryFilterReset",
            pageLinkClass: "inquiry-page-link",
            viewMode: "page",
            createTitle: "",
        },
    };

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
            path.includes("/file/") ||
            path.includes("/files/")
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

    function fetchPage(href) {
        return fetch(href, {
            credentials: "same-origin",
            headers: {
                "X-Opora-Nav": "1",
                "X-Requested-With": "OporaNav",
                Accept: "text/html",
            },
        });
    }

    const inflightPages = new Map();

    function canPrefetch(url) {
        if (window.OporaBusy?.isBusy()) return false;
        const path = url.pathname;
        if (mustFullReload(url)) return false;
        if (
            path.startsWith("/eis") ||
            path.startsWith("/agreements") ||
            path.startsWith("/reports") ||
            path.startsWith("/audit")
        ) {
            return false;
        }
        return true;
    }

    function loadPageHtml(href) {
        const key = cacheKey(href);
        const cached = cacheGet(href);
        if (cached) return Promise.resolve(cached);
        const pending = inflightPages.get(key);
        if (pending) return pending;

        const promise = fetchPage(href)
            .then(async (response) => {
                const finalUrl = response.url || href;
                if (
                    !response.ok ||
                    (response.redirected && /\/auth\/login/.test(finalUrl)) ||
                    !isHtmlNavResponse(response)
                ) {
                    return null;
                }
                const html = await response.text();
                if (!html.includes("app-content")) return null;
                cacheSet(href, html);
                return html;
            })
            .catch(() => null)
            .finally(() => {
                if (inflightPages.get(key) === promise) inflightPages.delete(key);
            });

        inflightPages.set(key, promise);
        return promise;
    }

    function listShellFor(href) {
        const url = new URL(href, window.location.href);
        const path = url.pathname.endsWith("/") ? url.pathname : `${url.pathname}/`;
        return LIST_SHELLS[path] || null;
    }

    function paintListShell(spec) {
        const current = document.getElementById("appContent") || document.querySelector(".app-content");
        if (!current) return false;
        document.title = `${spec.title} — Опора`;
        current.outerHTML = `<main class="app-content" id="appContent">
            <div class="page-header">
                <div class="page-header__content">
                    <div class="page-header__icon"><i class="bi bi-${spec.icon}"></i></div>
                    <div>
                        <h1 class="page-header__title">${spec.title}</h1>
                        <p class="page-header__subtitle">${spec.subtitle}</p>
                    </div>
                </div>
            </div>
            <div class="card mb-4 list-filters">
                <div class="card-header"><i class="bi bi-search"></i>Поиск</div>
                <div class="card-body">
                    <form id="${spec.filterFormId}" class="row g-3">
                        <div class="col-lg-6">
                            <label class="form-label">Поиск</label>
                            <input type="search" name="q" class="form-control" placeholder="${spec.placeholder}" autocomplete="off">
                        </div>
                    </form>
                </div>
            </div>
            <div id="${spec.tableContainerId}">
                <div class="opora-loading" role="status">
                    <div class="spinner-border text-primary"></div>
                    <div class="opora-loading__text">${spec.loading}</div>
                </div>
            </div>
            <div id="${spec.paginationContainerId}" class="mt-3"></div>
            <div id="oporaListConfig" class="d-none"
                 data-base-url="${spec.baseUrl}"
                 data-filter-form-id="${spec.filterFormId}"
                 data-table-container-id="${spec.tableContainerId}"
                 data-pagination-container-id="${spec.paginationContainerId}"
                 data-reset-btn-id="${spec.resetBtnId}"
                 data-page-link-class="${spec.pageLinkClass}"
                 data-create-title="${spec.createTitle}"
                 data-view-mode="${spec.viewMode}"
                 data-load-on-start="true"></div>
        </main>`;
        return true;
    }

    function mergeListChrome(html) {
        const doc = new DOMParser().parseFromString(html, "text/html");
        const content = document.getElementById("appContent");
        if (!content || !content.querySelector("#oporaListConfig")) return false;
        document.title = doc.title || document.title;
        const nextHeader = doc.querySelector(".page-header");
        const curHeader = content.querySelector(".page-header");
        if (nextHeader && curHeader) curHeader.replaceWith(nextHeader);
        const nextFilters = doc.querySelector(".list-filters");
        const curFilters = content.querySelector(".list-filters");
        if (nextFilters && curFilters) curFilters.replaceWith(nextFilters);
        else if (nextFilters && curHeader) curHeader.after(nextFilters);
        const nextExtra = doc.querySelector("[data-list-extra]");
        const curExtra = content.querySelector("[data-list-extra]");
        if (nextExtra && curExtra) curExtra.replaceWith(nextExtra);
        else if (nextExtra && !curExtra) {
            const after = content.querySelector(".list-filters") || content.querySelector(".page-header");
            if (after) after.after(nextExtra);
        } else if (!nextExtra && curExtra) {
            curExtra.remove();
        }
        const nextConfig = doc.querySelector("#oporaListConfig");
        const curConfig = content.querySelector("#oporaListConfig");
        if (nextConfig && curConfig) curConfig.replaceWith(nextConfig);
        window.OporaList?.bindFilters?.();
        return true;
    }

    async function navigateTo(href, label, { push = true } = {}) {
        const token = ++navToken;
        markSidebar(href);
        closeSidebar();

        const spec = listShellFor(href);
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

        if (spec) {
            hideLoading();
            window.OporaList?.reset?.();
            paintListShell(spec);
            window.OporaList?.bootPage?.();
            if (push) history.pushState({ oporaNav: true }, "", href);
            loadPageHtml(href).then((html) => {
                if (token !== navToken || !html) return;
                mergeListChrome(html);
            });
            return;
        }

        showSkeleton(label);
        try {
            const html = await loadPageHtml(href);
            if (token !== navToken) return;
            if (!html) {
                window.location.href = href;
                return;
            }
            const ok = await applyHtml(html);
            if (token !== navToken) return;
            if (!ok) {
                window.location.href = href;
                return;
            }
            if (push) history.pushState({ oporaNav: true }, "", href);
            hideLoading();
        } catch (err) {
            if (token !== navToken) return;
            window.location.href = href;
        }
    }

    window.OporaNav = {
        go(href, label) {
            if (window.OporaBusy?.isBusy()) return;
            const next = new URL(href, window.location.href);
            if (next.origin !== window.location.origin || mustFullReload(next)) {
                window.location.href = next.href;
                return;
            }
            navigateTo(next.href, label || "Загрузка");
        },
    };

    let hoverTimer = 0;
    let pendingHoverKey = "";

    function schedulePrefetch(href) {
        const url = new URL(href, window.location.href);
        if (url.origin !== window.location.origin || !canPrefetch(url)) return;
        const key = cacheKey(href);
        if (cacheGet(href) || inflightPages.has(key) || key === pendingHoverKey) return;
        pendingHoverKey = key;
        window.clearTimeout(hoverTimer);
        hoverTimer = window.setTimeout(() => {
            pendingHoverKey = "";
            loadPageHtml(href);
        }, 220);
    }

    window.addEventListener("pageshow", hideLoading);
    window.addEventListener("pagehide", hideLoading);
    window.addEventListener("popstate", () => {
        navigateTo(window.location.href, "Загрузка", { push: false });
    });
    history.replaceState({ oporaNav: true }, "", window.location.href);

    shell.addEventListener("click", (event) => {
        const link = event.target.closest("a[href]");
        const next = spaTarget(link, event);
        if (!next) return;
        if (window.OporaBusy?.isBusy()) {
            event.preventDefault();
            return;
        }
        if (next.pathname === window.location.pathname && next.search === window.location.search) {
            event.preventDefault();
            return;
        }
        event.preventDefault();
        window.clearTimeout(hoverTimer);
        pendingHoverKey = "";
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
        schedulePrefetch(href);
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
