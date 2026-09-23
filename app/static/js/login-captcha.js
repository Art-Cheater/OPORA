/* Ошибка загрузки Turnstile видна пользователю. Обход проверки отсюда не включается. */
(function () {
  function show(message) {
    const node = document.getElementById("captchaStatus");
    if (!node) return;
    node.textContent = message;
    node.classList.remove("d-none");
  }
  window.oporaTurnstileError = function () {
    show("Не удалось загрузить проверку. Обновите страницу. Вход без проверки невозможен.");
  };
  window.oporaTurnstileTimeout = function () {
    show("Проверка не ответила. Повторите попытку. Вход без проверки невозможен.");
  };
  window.setTimeout(function () {
    const widget = document.querySelector(".cf-turnstile");
    if (!widget || widget.querySelector("iframe")) return;
    window.oporaTurnstileError();
  }, 8000);
})();
