/* Один service worker для PWA shell и уже существующего Web Push. */
(() => {
  if (!('serviceWorker' in navigator) || window.__oporaPwaRegistered) return;
  window.__oporaPwaRegistered = true;
  const register = () => navigator.serviceWorker.register('/service-worker.js').catch(() => undefined);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', register, { once: true });
  else register();
})();
