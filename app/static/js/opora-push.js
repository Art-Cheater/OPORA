(() => {
  const root = document.getElementById("messengerApp");
  if (!root || !("serviceWorker" in navigator) || !("PushManager" in window)) return;
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const control = document.getElementById("pushEnableButton");
  const status = document.getElementById("pushStatus");
  const setStatus = (text) => { if (status) status.textContent = text; };
  const bytes = (base64) => {
    const padding = "=".repeat((4 - base64.length % 4) % 4);
    const data = atob((base64 + padding).replace(/-/g, "+").replace(/_/g, "/"));
    return Uint8Array.from(data, (char) => char.charCodeAt(0));
  };
  async function setup() {
    if (Notification.permission === "denied") { setStatus("Уведомления заблокированы в настройках браузера."); return; }
    const config = await fetch("/notifications/push/config", {credentials: "same-origin"}).then(r => r.json());
    if (!config.configured) { setStatus("Системные push-уведомления не настроены на сервере."); return; }
    const registration = await navigator.serviceWorker.register("/service-worker.js");
    const permission = await Notification.requestPermission();
    if (permission !== "granted") { setStatus("Уведомления не включены."); return; }
    const subscription = await registration.pushManager.subscribe({userVisibleOnly: true, applicationServerKey: bytes(config.public_key)});
    const result = await fetch("/notifications/push/subscribe", {method: "POST", credentials: "same-origin", headers: {"Content-Type": "application/json", ...(csrf ? {"X-CSRFToken": csrf} : {})}, body: JSON.stringify(subscription)}).then(r => r.json());
    setStatus(result.ok ? "Системные уведомления включены." : (result.message || "Не удалось включить уведомления."));
  }
  control?.addEventListener("click", () => setup().catch(() => setStatus("Не удалось включить уведомления.")));
})();
