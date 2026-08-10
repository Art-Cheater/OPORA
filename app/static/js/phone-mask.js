/** Маска телефона: +7 (999) 999-99-99 */
window.OporaPhoneMask = (() => {
  const PLACEHOLDER = "+7 (___) ___-__-__";

  function digitsOnly(value) {
    return (value || "").replace(/\D/g, "");
  }

  function formatPhone(raw) {
    let d = digitsOnly(raw);
    if (d.startsWith("8")) d = "7" + d.slice(1);
    if (d.startsWith("7")) d = d.slice(1);
    d = d.slice(0, 10);

    let out = "+7";
    if (!d.length) return out;

    out += " (" + d.slice(0, 3);
    if (d.length < 3) return out;

    out += ") " + d.slice(3, 6);
    if (d.length < 6) return out;

    out += "-" + d.slice(6, 8);
    if (d.length < 8) return out;

    out += "-" + d.slice(8, 10);
    return out;
  }

  function apply(input) {
    if (!input || input.dataset.phoneMaskBound === "1") return;
    input.dataset.phoneMaskBound = "1";
    input.classList.add("opora-phone-mask");
    if (!input.placeholder) input.placeholder = PLACEHOLDER;
    input.autocomplete = "tel";

    const refresh = () => {
      const formatted = formatPhone(input.value);
      input.value = formatted;
    };

    input.addEventListener("input", refresh);
    input.addEventListener("focus", () => {
      if (!digitsOnly(input.value)) input.value = "+7 (";
    });
    input.addEventListener("blur", () => {
      if (input.value === "+7 (" || input.value === "+7") input.value = "";
    });
    refresh();
  }

  function init(root = document) {
    root.querySelectorAll('input[type="tel"], .opora-phone-mask, input[name="phone"]').forEach(apply);
  }

  return { init, apply, formatPhone };
})();

document.addEventListener("DOMContentLoaded", () => OporaPhoneMask.init());
