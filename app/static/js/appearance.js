/**
 * Панель «Внешний вид»: тема + фон интерфейса.
 */
(function () {
    function csrf() {
        return document.querySelector('meta[name="csrf-token"]')?.content || "";
    }

    function applyBg(url, id) {
        const body = document.body;
        let style = document.getElementById("oporaUiBgStyle");
        if (url) {
            if (!style) {
                style = document.createElement("style");
                style.id = "oporaUiBgStyle";
                document.head.appendChild(style);
            }
            style.textContent = `:root{--opora-ui-bg-image:url("${url}");}`;
            body.classList.add("has-ui-bg");
        } else {
            if (style) style.remove();
            body.classList.remove("has-ui-bg");
        }
        body.dataset.uiBg = id || "none";
        document.querySelectorAll("[data-appearance-bg]").forEach((btn) => {
            btn.classList.toggle("is-selected", btn.dataset.appearanceBg === id);
        });
        const clearBtn = document.getElementById("appearanceBgClear");
        if (clearBtn) clearBtn.classList.toggle("d-none", id !== "custom");
    }

    async function postJson(url, payload) {
        const res = await fetch(url, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-CSRFToken": csrf(),
                "X-Requested-With": "XMLHttpRequest",
            },
            body: JSON.stringify(payload),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || data.ok === false) {
            throw new Error(data.error || "Не удалось сохранить настройки");
        }
        return data;
    }

    function showError(msg) {
        const el = document.getElementById("appearanceBgError");
        if (!el) return;
        el.textContent = msg || "";
        el.classList.toggle("d-none", !msg);
    }

    function syncThemeButtons() {
        const current = window.OporaTheme ? window.OporaTheme.current() : document.documentElement.getAttribute("data-theme");
        document.querySelectorAll("[data-appearance-theme]").forEach((btn) => {
            btn.classList.toggle("is-active", btn.dataset.appearanceTheme === current);
        });
    }

    function bind() {
        const appearanceUrl = document.body.dataset.appearanceUrl;
        const bgUrl = document.body.dataset.appearanceBgUrl;
        if (!appearanceUrl) return;

        document.querySelectorAll("[data-appearance-theme]").forEach((btn) => {
            btn.addEventListener("click", async () => {
                const theme = btn.dataset.appearanceTheme;
                if (window.OporaTheme) window.OporaTheme.apply(theme);
                syncThemeButtons();
                try {
                    await postJson(appearanceUrl, { theme });
                } catch (e) {
                    showError(e.message);
                }
            });
        });

        document.querySelectorAll("[data-appearance-bg]").forEach((btn) => {
            btn.addEventListener("click", async () => {
                const id = btn.dataset.appearanceBg;
                showError("");
                try {
                    await postJson(appearanceUrl, { background: id });
                    if (id === "none") {
                        applyBg(null, "none");
                    } else if (id === "custom") {
                        const preview = btn.querySelector(".appearance-bg-card__preview");
                        const bg = preview && preview.style.backgroundImage
                            ? preview.style.backgroundImage.replace(/^url\(["']?/, "").replace(/["']?\)$/, "")
                            : "";
                        applyBg(bg || null, "custom");
                    } else {
                        const preview = btn.querySelector(".appearance-bg-card__preview");
                        const bg = preview && preview.style.backgroundImage
                            ? preview.style.backgroundImage.replace(/^url\(["']?/, "").replace(/["']?\)$/, "")
                            : "";
                        applyBg(bg || null, id);
                    }
                } catch (e) {
                    showError(e.message);
                }
            });
        });

        const fileInput = document.getElementById("appearanceBgFile");
        if (fileInput && bgUrl) {
            fileInput.addEventListener("change", async () => {
                const file = fileInput.files && fileInput.files[0];
                if (!file) return;
                showError("");
                const fd = new FormData();
                fd.append("background", file);
                try {
                    const res = await fetch(bgUrl, {
                        method: "POST",
                        headers: {
                            "X-CSRFToken": csrf(),
                            "X-Requested-With": "XMLHttpRequest",
                        },
                        body: fd,
                    });
                    const data = await res.json().catch(() => ({}));
                    if (!res.ok || data.ok === false) {
                        throw new Error(data.error || "Ошибка загрузки");
                    }
                    applyBg(data.url, "custom");
                    let customBtn = document.querySelector('[data-appearance-bg="custom"]');
                    if (!customBtn) {
                        const grid = document.getElementById("appearanceBgGrid");
                        customBtn = document.createElement("button");
                        customBtn.type = "button";
                        customBtn.className = "appearance-bg-card is-selected";
                        customBtn.dataset.appearanceBg = "custom";
                        customBtn.title = "Свой фон";
                        customBtn.innerHTML =
                            '<span class="appearance-bg-card__preview"></span>' +
                            '<span class="appearance-bg-card__title">Свой фон</span>' +
                            '<span class="appearance-bg-card__check"><i class="bi bi-check-lg"></i></span>';
                        grid.appendChild(customBtn);
                        customBtn.addEventListener("click", async () => {
                            try {
                                await postJson(appearanceUrl, { background: "custom" });
                                applyBg(data.url, "custom");
                            } catch (err) {
                                showError(err.message);
                            }
                        });
                    }
                    const preview = customBtn.querySelector(".appearance-bg-card__preview");
                    if (preview) preview.style.backgroundImage = `url("${data.url}")`;
                    document.querySelectorAll("[data-appearance-bg]").forEach((b) => {
                        b.classList.toggle("is-selected", b.dataset.appearanceBg === "custom");
                    });
                    document.getElementById("appearanceBgClear")?.classList.remove("d-none");
                } catch (e) {
                    showError(e.message);
                } finally {
                    fileInput.value = "";
                }
            });
        }

        const clearBtn = document.getElementById("appearanceBgClear");
        if (clearBtn && bgUrl) {
            clearBtn.addEventListener("click", async () => {
                showError("");
                try {
                    const res = await fetch(bgUrl, {
                        method: "DELETE",
                        headers: {
                            "X-CSRFToken": csrf(),
                            "X-Requested-With": "XMLHttpRequest",
                        },
                    });
                    const data = await res.json().catch(() => ({}));
                    if (!res.ok || data.ok === false) {
                        throw new Error(data.error || "Не удалось удалить фон");
                    }
                    applyBg(null, data.background || "none");
                    const customBtn = document.querySelector('[data-appearance-bg="custom"]');
                    if (customBtn) customBtn.remove();
                } catch (e) {
                    showError(e.message);
                }
            });
        }

        syncThemeButtons();
        document.addEventListener("click", (e) => {
            if (!e.target.closest("[data-theme-toggle]")) return;
            setTimeout(async () => {
                syncThemeButtons();
                try {
                    const theme = window.OporaTheme ? window.OporaTheme.current() : null;
                    if (theme) await postJson(appearanceUrl, { theme });
                } catch (_) {
                    /* ignore offline save errors for quick toggle */
                }
            }, 0);
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", bind);
    } else {
        bind();
    }
})();
