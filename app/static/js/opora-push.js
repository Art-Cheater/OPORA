/* Web Push UI мессенджера. Подписка создаётся только после явного клика. */
(() => {
  if (window.OporaMessengerPush) return;
  const bytes = (base64) => {
    const padding = "=".repeat((4 - base64.length % 4) % 4);
    const data = atob((base64 + padding).replace(/-/g, "+").replace(/_/g, "/"));
    return Uint8Array.from(data, (char) => char.charCodeAt(0));
  };
  const boot = () => {
    const root = document.getElementById("messengerApp");
    if (!root || root.dataset.pushBound === "1") return;
    root.dataset.pushBound = "1";
    const button = root.querySelector("#pushEnableButton");
    const status = root.querySelector("#pushStatus");
    const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
    const setStatus = (text, state = "") => {
      if (status) { status.textContent = text; status.classList.toggle("is-visible", Boolean(text)); }
      if (!button) return;
      button.dataset.pushState = state;
      if (state === "enabled") {
        button.title = "Системные уведомления включены";
        button.innerHTML = '<i class="bi bi-bell-fill" aria-hidden="true"></i><span class="tg-push-button__label">Включены</span>';
      }
    };
    if (!button) return;
    if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) {
      button.disabled = true; button.title = "Push не поддерживается браузером";
      setStatus("Push не поддерживается браузером", "unsupported"); return;
    }
    if (Notification.permission === "denied") {
      button.title = "Уведомления заблокированы в настройках браузера";
      setStatus("Заблокированы браузером", "denied");
    }
    button.addEventListener("click", async () => {
      if (button.dataset.pushBusy === "1") return;
      if (Notification.permission === "denied") { setStatus("Заблокированы браузером", "denied"); return; }
      button.dataset.pushBusy = "1"; button.disabled = true;
      try {
        const response = await fetch("/notifications/push/config", { credentials: "same-origin" });
        const config = await response.json().catch(() => ({}));
        if (!response.ok || !config.configured || !config.public_key) {
          setStatus("Push не настроены на сервере", "unconfigured"); return;
        }
        const permission = await Notification.requestPermission();
        if (permission !== "granted") {
          setStatus(permission === "denied" ? "Заблокированы браузером" : "Уведомления не включены", permission); return;
        }
        const registration = await navigator.serviceWorker.register("/service-worker.js");
        const subscription = await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: bytes(config.public_key) });
        const result = await fetch("/notifications/push/subscribe", {
          method: "POST", credentials: "same-origin",
          headers: { "Content-Type": "application/json", ...(csrf ? { "X-CSRFToken": csrf } : {}) },
          body: JSON.stringify(subscription),
        }).then((res) => res.json().catch(() => ({})));
        setStatus(result.ok ? "Уведомления включены" : (result.message || "Не удалось включить"), result.ok ? "enabled" : "error");
      } catch (_) { setStatus("Не удалось включить уведомления", "error"); }
      finally { button.dataset.pushBusy = ""; button.disabled = button.dataset.pushState === "unsupported"; }
    });
  };
  window.OporaMessengerPush = { boot };
  document.addEventListener("DOMContentLoaded", boot);
  window.addEventListener("opora:navigated", boot);
  boot();
})();
