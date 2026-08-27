/**
 * Опора — переключение светлой / тёмной темы.
 * Тема на html[data-theme] выставляется ранним скриптом в <head>;
 * здесь только UI-переключатель и синхронизация иконки.
 */
(function () {
    const STORAGE_KEY = "opora-theme";

    function currentTheme() {
        const attr = document.documentElement.getAttribute("data-theme");
        if (attr === "light" || attr === "dark") return attr;
        return "light";
    }

    function applyTheme(theme) {
        const next = theme === "dark" ? "dark" : "light";
        document.documentElement.setAttribute("data-theme", next);
        try {
            localStorage.setItem(STORAGE_KEY, next);
        } catch (_) {
            /* ignore quota / private mode */
        }
        document.querySelectorAll("[data-theme-toggle]").forEach((btn) => {
            const isDark = next === "dark";
            btn.setAttribute("aria-label", isDark ? "Включить светлую тему" : "Включить тёмную тему");
            btn.setAttribute("title", isDark ? "Светлая тема" : "Тёмная тема");
        });
    }

    function toggleTheme() {
        applyTheme(currentTheme() === "dark" ? "light" : "dark");
    }

    window.OporaTheme = { apply: applyTheme, toggle: toggleTheme, current: currentTheme };

    function bind() {
        document.querySelectorAll("[data-theme-toggle]").forEach((btn) => {
            if (btn.dataset.themeBound === "1") return;
            btn.dataset.themeBound = "1";
            btn.addEventListener("click", (e) => {
                e.preventDefault();
                toggleTheme();
            });
        });
        applyTheme(currentTheme());
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", bind);
    } else {
        bind();
    }
})();
