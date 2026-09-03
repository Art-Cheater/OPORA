/**
 * Опора — основной JavaScript
 */

document.addEventListener("DOMContentLoaded", () => {
    initFlashMessages();
    initSidebar();
    initSearchShortcut();
    initMessengerUnreadBadge();
    initNotificationsBell();
    initOporaTourLazy();
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
    let toastHost = null;
    let toastTimer = null;

    function ensureAudio() {
        if (audioCtx) return audioCtx;
        const Ctx = window.AudioContext || window.webkitAudioContext;
        if (!Ctx) return null;
        audioCtx = new Ctx();
        return audioCtx;
    }

    function unlockAudio() {
        try {
            const ctx = ensureAudio();
            if (!ctx) return;
            if (ctx.state === "suspended") ctx.resume();
        } catch {
            /* ignore */
        }
    }

    /** Громкий трёхкратный сигнал (не тихий «пип»). */
    function playSound() {
        try {
            unlockAudio();
            const ctx = ensureAudio();
            if (!ctx) return;
            const now = ctx.currentTime;
            const master = ctx.createGain();
            master.gain.setValueAtTime(0.55, now);
            master.connect(ctx.destination);

            [0, 0.22, 0.44].forEach((offset, index) => {
                const osc = ctx.createOscillator();
                const gain = ctx.createGain();
                osc.type = "square";
                osc.frequency.value = index === 1 ? 1320 : 980;
                const t0 = now + offset;
                gain.gain.setValueAtTime(0.0001, t0);
                gain.gain.exponentialRampToValueAtTime(0.45, t0 + 0.02);
                gain.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.16);
                osc.connect(gain);
                gain.connect(master);
                osc.start(t0);
                osc.stop(t0 + 0.18);
            });
        } catch {
            /* ignore */
        }
    }

    function requestPermission() {
        unlockAudio();
        if (!("Notification" in window)) return;
        if (Notification.permission !== "default" || permissionAsked) return;
        permissionAsked = true;
        Notification.requestPermission().catch(() => {});
    }

    function ensureToastHost() {
        if (toastHost && document.body.contains(toastHost)) return toastHost;
        toastHost = document.createElement("div");
        toastHost.id = "oporaMsgToasts";
        toastHost.className = "opora-msg-toasts";
        toastHost.setAttribute("aria-live", "polite");
        document.body.appendChild(toastHost);
        return toastHost;
    }

    function showToast({ title, body, url }) {
        const host = ensureToastHost();
        const el = document.createElement("button");
        el.type = "button";
        el.className = "opora-msg-toast";
        el.innerHTML = `
            <div class="opora-msg-toast__icon"><i class="bi bi-chat-dots-fill"></i></div>
            <div class="opora-msg-toast__body">
                <div class="opora-msg-toast__title"></div>
                <div class="opora-msg-toast__text"></div>
            </div>
            <span class="opora-msg-toast__close" aria-hidden="true">&times;</span>
        `;
        el.querySelector(".opora-msg-toast__title").textContent = title || "Новое сообщение";
        el.querySelector(".opora-msg-toast__text").textContent = body || "";
        const go = () => {
            el.remove();
            if (url) window.location.href = url;
        };
        el.addEventListener("click", (event) => {
            if (event.target.closest(".opora-msg-toast__close")) {
                el.remove();
                return;
            }
            go();
        });
        host.appendChild(el);
        window.clearTimeout(toastTimer);
        toastTimer = window.setTimeout(() => el.remove(), 10000);
    }

    function showBrowserNotification({ title, body, url, tag }) {
        if (!("Notification" in window)) return;
        if (Notification.permission !== "granted") return;
        try {
            const n = new Notification(title || "Новое сообщение", {
                body: body || "",
                tag: tag || "opora-messenger",
                renotify: true,
                requireInteraction: true,
                silent: true,
            });
            n.onclick = () => {
                window.focus();
                if (url) window.location.href = url;
                n.close();
            };
            setTimeout(() => n.close(), 15000);
        } catch {
            /* ignore */
        }
    }

    /**
     * Звук + всплывающий тост + браузерное уведомление.
     * skip* — если пользователь уже смотрит этот чат во вкладке.
     */
    function notifyNewMessage({
        title,
        body,
        url,
        messageId,
        conversationId,
        skipSound,
        skipBrowser,
        skipToast,
    }) {
        if (messageId && messageId === lastNotifiedMessageId) return;
        if (messageId) lastNotifiedMessageId = messageId;

        const payload = {
            title: title || "Новое сообщение",
            body: body || "",
            url: url || "/messenger/",
            tag: conversationId ? `msg-${conversationId}` : "opora-messenger",
        };

        if (!skipSound) playSound();
        if (!skipToast) showToast(payload);
        if (!skipBrowser) showBrowserNotification(payload);
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
            url: preview?.conversation_id
                ? `/messenger/?c=${encodeURIComponent(preview.conversation_id)}`
                : "/messenger/",
            messageId: preview?.message_id || null,
            conversationId: preview?.conversation_id || null,
            skipSound: viewingChat,
            skipBrowser: viewingChat,
            skipToast: viewingChat,
        });
    }

    ["pointerdown", "keydown", "touchstart"].forEach((eventName) => {
        document.addEventListener(
            eventName,
            () => {
                unlockAudio();
                requestPermission();
            },
            { once: true, capture: true }
        );
    });

    return {
        playSound,
        unlockAudio,
        requestPermission,
        notifyNewMessage,
        onUnreadIncrease,
        showToast,
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
    const ASSET_TIMEOUT_MS = 8000;
    const NAV_TIMEOUT_MS = 20000;
    const pageCache = new Map();
    const SHELL_ASSET = /bootstrap|main\.css|main\.js|opora-list|phone-mask|search\.js|search\.css|requests-form|tour\.js|tour\.css/;
    const LIST_SHELLS = {
        "/waybills/": {
            title: "Путевые листы",
            subtitle: "Маршрут выезда: заявки и дефекты за один день",
            icon: "signpost-2",
            placeholder: "Номер…",
            loading: "Загрузка путевых листов…",
            baseUrl: "/waybills",
            filterFormId: "waybillFilterForm",
            tableContainerId: "waybillsTableContainer",
            paginationContainerId: "waybillsPaginationContainer",
            resetBtnId: "waybillFilterReset",
            pageLinkClass: "waybill-page-link",
            viewMode: "page",
            createTitle: "Новый путевой лист",
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

    function samePath(a, b) {
        const pathA = (a.pathname || "/").replace(/\/+$/, "") || "/";
        const pathB = (b.pathname || "/").replace(/\/+$/, "") || "/";
        return pathA === pathB && (a.search || "") === (b.search || "");
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
            let settled = false;
            const finish = () => {
                if (settled) return;
                settled = true;
                window.clearTimeout(timer);
                resolve();
            };
            const timer = window.setTimeout(finish, ASSET_TIMEOUT_MS);
            link.onload = finish;
            link.onerror = finish;
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
            script.async = false;
            script.src = src;
            let settled = false;
            const finish = () => {
                if (settled) return;
                settled = true;
                window.clearTimeout(timer);
                resolve();
            };
            const timer = window.setTimeout(finish, ASSET_TIMEOUT_MS);
            script.onload = finish;
            script.onerror = finish;
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

    window.OporaObjectForm = {
        init() {
            document.querySelectorAll("[data-object-kind-form]").forEach((root) => {
                const select = root.querySelector('[name="object_kind"]');
                if (!select || select.dataset.kindBound === "1") return;
                select.dataset.kindBound = "1";
                const sync = () => {
                    const kind = select.value;
                    root.querySelectorAll(".js-kind-comment").forEach((node) => {
                        node.hidden = kind !== "other";
                    });
                    root.querySelectorAll(".js-kind-court").forEach((node) => {
                        node.hidden = kind !== "court";
                    });
                    const commentField = root.querySelector('[name="kind_comment"]');
                    const commentWrap = commentField?.closest(".col-12, [class*='col-']");
                    if (commentWrap && !commentWrap.classList.contains("js-kind-comment")) {
                        commentWrap.hidden = kind !== "other";
                    }
                    const courtField = root.querySelector('[name="court_decision_number"]');
                    const courtWrap = courtField?.closest(".col-12, [class*='col-']");
                    if (courtWrap && !courtWrap.classList.contains("js-kind-court")) {
                        courtWrap.hidden = kind !== "court";
                    }
                };
                select.addEventListener("change", sync);
                sync();
            });
        },
    };

    function bootPageModules() {
        window.OporaList?.reset?.();
        window.OporaList?.bootPage?.();
        window.OporaRolesAdmin?.init?.();
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
        window.OporaOpsMap?.init?.();
        window.OporaRequestsJournal?.init?.();
        window.OporaWorkOrders?.init?.();
        window.OporaWorkPlanNew?.init?.();
        window.OporaWorkPlanDetail?.init?.();
        window.OporaObjectForm?.init?.();
        if (document.getElementById("inquiryForwardCard")) {
            const card = document.getElementById("inquiryForwardCard");
            if (card) delete card.dataset.bound;
            window.OporaInquiryForward?.init?.(card);
        }
        window.OporaProjectDocuments?.init?.();
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
        const controller = new AbortController();
        const timer = window.setTimeout(() => controller.abort(), NAV_TIMEOUT_MS);
        return fetch(href, {
            credentials: "same-origin",
            cache: "no-store",
            signal: controller.signal,
            headers: {
                "X-Opora-Nav": "1",
                "X-Requested-With": "OporaNav",
                Accept: "text/html",
            },
        }).finally(() => window.clearTimeout(timer));
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
        if (path === "/requests/" || path === "/defects/") return null;
        return LIST_SHELLS[path] || null;
    }

    function paintListShell(spec) {
        const current = document.getElementById("appContent") || document.querySelector(".app-content");
        if (!current) return false;
        document.title = `${spec.title} — Опора`;
        current.outerHTML = `<main class="app-content" id="appContent">
            <div class="page-header" data-tour="page-header">
                <div class="page-header__content">
                    <div class="page-header__icon"><i class="bi bi-${spec.icon}"></i></div>
                    <div>
                        <h1 class="page-header__title">${spec.title}</h1>
                        <p class="page-header__subtitle">${spec.subtitle}</p>
                    </div>
                </div>
            </div>
            <div class="card mb-4 list-filters" data-tour="filters">
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
            <div id="${spec.tableContainerId}" data-tour="list-table">
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
        const nextConfig = doc.querySelector("#oporaListConfig");
        const curConfig = content.querySelector("#oporaListConfig");
        const nextTableId = nextConfig?.getAttribute("data-table-container-id") || "";
        const curTableId = curConfig?.getAttribute("data-table-container-id") || "";
        if (nextTableId && curTableId && nextTableId !== curTableId) {
            return false;
        }
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
        if (nextTableId) {
            const nextTable = doc.querySelector(`#${nextTableId}`);
            const curTable = content.querySelector(`#${nextTableId}`);
            if (nextTable && curTable) curTable.replaceWith(nextTable);
        }
        if (nextConfig && curConfig) curConfig.replaceWith(nextConfig);
        else if (nextConfig && !curConfig) content.append(nextConfig);
        window.OporaList?.reset?.();
        window.OporaList?.bootPage?.();
        window.OporaOpsMap?.init?.();
        window.OporaRequestsJournal?.init?.();
        return true;
    }

    function emitNavigated(href) {
        try {
            window.dispatchEvent(
                new CustomEvent("opora:navigated", {
                    detail: { href: href || window.location.href },
                })
            );
        } catch {
            /* ignore */
        }
    }

    async function navigateTo(href, label, { push = true } = {}) {
        const token = ++navToken;
        markSidebar(href);
        closeSidebar();

        const spec = listShellFor(href);
        const dest = new URL(href, window.location.href);
        const destPath = (dest.pathname.replace(/\/+$/, "") || "/");
        const skipCache = destPath === "/requests" || destPath === "/defects";
        const cached = spec || skipCache ? null : cacheGet(href);

        if (cached) {
            hideLoading();
            if (push) history.pushState({ oporaNav: true }, "", href);
            const ok = await applyHtml(cached);
            if (token !== navToken) return;
            if (!ok) {
                window.location.href = href;
                return;
            }
            emitNavigated(href);
            return;
        }

        if (spec) {
            hideLoading();
            window.OporaList?.reset?.();
            paintListShell(spec);
            if (push) history.pushState({ oporaNav: true }, "", href);
            window.OporaList?.bootPage?.();
            emitNavigated(href);
            loadPageHtml(href).then(async (html) => {
                if (token !== navToken || !html) return;
                if (!mergeListChrome(html)) {
                    await applyHtml(html);
                }
                emitNavigated(href);
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
            if (push) history.pushState({ oporaNav: true }, "", href);
            const ok = await applyHtml(html);
            if (token !== navToken) return;
            if (!ok) {
                window.location.href = href;
                return;
            }
            hideLoading();
            emitNavigated(href);
        } catch (err) {
            if (token !== navToken) return;
            hideLoading();
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
        const journalKind = link.getAttribute("data-opora-journal");
        if (journalKind === "defects") {
            next.searchParams.set("tab", "defects");
            next.searchParams.delete("journal_id");
        } else if (journalKind === "requests") {
            next.searchParams.delete("tab");
        }
        if (window.OporaBusy?.isBusy()) {
            event.preventDefault();
            return;
        }
        if (samePath(next, window.location)) {
            event.preventDefault();
            window.OporaList?.reset?.();
            window.OporaList?.bootPage?.();
            window.OporaRolesAdmin?.init?.();
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

function initNotificationsBell() {
    const listEl = document.getElementById("topbarNotifyList");
    const dot = document.getElementById("topbarNotifyDot");
    const readAllBtn = document.getElementById("topbarNotifyReadAll");
    if (!listEl) return;

    const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";

    function render(items, total) {
        if (dot) dot.classList.toggle("d-none", !(total > 0));
        if (!items.length) {
            listEl.innerHTML = '<div class="text-muted small px-3 py-2">Пока нет уведомлений</div>';
            return;
        }
        listEl.innerHTML = items
            .map(
                (item) => `
            <a href="${item.link || "#"}" class="topbar__notify-item" data-notify-id="${item.id}">
                <strong>${escapeHtml(item.title || "Уведомление")}</strong>
                <span>${escapeHtml(item.message || "")}</span>
                <small>${escapeHtml(item.created_at || "")}</small>
            </a>`
            )
            .join("");
        listEl.querySelectorAll("[data-notify-id]").forEach((link) => {
            link.addEventListener("click", () => {
                const id = link.getAttribute("data-notify-id");
                if (!id) return;
                fetch(`/notifications/api/${id}/read`, {
                    method: "POST",
                    headers: { "X-CSRFToken": csrf, "X-Requested-With": "XMLHttpRequest" },
                }).catch(() => {});
            });
        });
    }

    function escapeHtml(value) {
        return String(value || "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    async function refresh() {
        try {
            const res = await fetch("/notifications/api/unread", {
                credentials: "same-origin",
                headers: { Accept: "application/json", "X-Requested-With": "XMLHttpRequest" },
                cache: "no-store",
                priority: "low",
            });
            if (!res.ok) return;
            const data = await res.json();
            render(data.items || [], data.total || 0);
        } catch {
            /* ignore */
        }
    }

    readAllBtn?.addEventListener("click", async (event) => {
        event.preventDefault();
        try {
            await fetch("/notifications/api/read-all", {
                method: "POST",
                headers: { "X-CSRFToken": csrf, "X-Requested-With": "XMLHttpRequest" },
            });
            await refresh();
        } catch {
            /* ignore */
        }
    });

    window.setTimeout(refresh, 1200);
    window.setInterval(refresh, 45000);
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

    document.addEventListener("visibilitychange", () => {
        refresh();
    });

    // Не конкурировать с CSS/JS на первом кадре страницы.
    window.setTimeout(refresh, 1500);
    window.setInterval(refresh, intervalMs);
}

function initOporaTourLazy() {
    const cfgNode = document.getElementById("oporaTourConfig");
    if (!cfgNode) return;

    let loadPromise = null;

    function tourSeenKey() {
        try {
            const parsed = JSON.parse(cfgNode.textContent || "{}");
            return `opora_tour_seen_v1_${parsed.userId || "anon"}`;
        } catch {
            return "opora_tour_seen_v1_anon";
        }
    }

    function ensureTourLoaded() {
        if (loadPromise) return loadPromise;
        if (window.OporaTour?.open) {
            window.OporaTour.init?.();
            return Promise.resolve(window.OporaTour);
        }
        const cssHref = cfgNode.dataset.tourCss;
        const jsSrc = cfgNode.dataset.tourJs;
        if (!jsSrc) return Promise.reject(new Error("tour.js missing"));

        loadPromise = new Promise((resolve, reject) => {
            if (cssHref && !document.querySelector('link[data-opora-tour="1"]')) {
                const link = document.createElement("link");
                link.rel = "stylesheet";
                link.href = cssHref;
                link.dataset.oporaTour = "1";
                document.head.appendChild(link);
            }
            const script = document.createElement("script");
            script.src = jsSrc;
            script.async = true;
            script.onload = () => {
                try {
                    window.OporaTour?.init?.();
                    resolve(window.OporaTour);
                } catch (err) {
                    reject(err);
                }
            };
            script.onerror = () => reject(new Error("tour.js load failed"));
            document.body.appendChild(script);
        }).finally(() => {
            /* оставляем loadPromise, чтобы повторно не вешать script */
        });
        return loadPromise;
    }

    function openTour(event) {
        event?.preventDefault();
        event?.stopPropagation();
        ensureTourLoaded()
            .then((tour) => {
                if (!tour?.open) throw new Error("OporaTour.open недоступен");
                tour.init?.();
                tour.open();
            })
            .catch((err) => {
                console.error("Обучение:", err);
                window.alert("Не удалось загрузить обучение. Обновите страницу (Ctrl+F5).");
            });
    }

    document.getElementById("oporaTourBtn")?.addEventListener("click", openTour);
    document.getElementById("oporaTourMenuStart")?.addEventListener("click", openTour);

    try {
        if (localStorage.getItem(tourSeenKey()) === "1") return;
        if (!document.getElementById("appShell") || document.getElementById("messengerApp")) return;
        localStorage.setItem(tourSeenKey(), "1");
        window.setTimeout(() => {
            ensureTourLoaded()
                .then((tour) => {
                    tour?.init?.();
                    tour?.open?.();
                })
                .catch(() => {});
        }, 700);
    } catch {
        /* ignore */
    }
}
