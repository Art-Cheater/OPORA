/**
 * Форма заявок: шлагбаум, проверка адреса, повторные обращения.
 */
(() => {
  const csrfToken = () =>
    document.querySelector('meta[name="csrf-token"]')?.content ||
    document.querySelector('input[name="csrf_token"]')?.value ||
    "";

  function isCreateForm(form) {
    if (form.dataset.requestId) return false;
    const action = (form.getAttribute("action") || "").toLowerCase();
    return action.endsWith("/new") || action.includes("/new");
  }

  function toggleBarrier(form) {
    const toggle = form.querySelector("[data-barrier-toggle], #hasBarrier, input[name='has_barrier']");
    const wrap = form.querySelector("[data-barrier-phone-wrap]");
    if (!toggle || !wrap) return;
    const sync = () => {
      wrap.classList.toggle("d-none", !toggle.checked);
      if (!toggle.checked) {
        const phone = wrap.querySelector("input");
        if (phone) phone.value = "";
      }
    };
    toggle.addEventListener("change", sync);
    sync();
  }

  function addressInput(form) {
    return form.querySelector("[name='address']");
  }

  function setAddressWarning(form, match) {
    const input = addressInput(form);
    const hint =
      form.querySelector("[data-address-hint]") ||
      form.querySelector("[data-address-hint-wrap] [data-address-hint]");
    const hintWrap = form.querySelector("[data-address-hint-wrap]");
    if (input) {
      input.classList.toggle("is-invalid", !!match);
      input.classList.toggle("border-danger", !!match);
      input.classList.toggle("request-address--repeat", !!match);
    }
    if (hint) {
      if (match) {
        hint.innerHTML =
          `Уже есть открытая заявка <strong>№${escapeHtml(match.number)}</strong>` +
          (match.received_at ? ` от ${escapeHtml(match.received_at)}` : "") +
          `. При сохранении спросят, это повтор.`;
        hint.classList.remove("d-none");
        if (hintWrap) hintWrap.classList.remove("d-none");
      } else {
        hint.textContent = "";
        hint.classList.add("d-none");
        if (hintWrap) hintWrap.classList.add("d-none");
      }
    }
    form.dataset.openMatchId = match?.id || "";
    form.dataset.openMatchNumber = match?.number || "";
    form.dataset.openMatchUrl = match?.url || "";
    form.dataset.openMatchReceived = match?.received_at || "";
    form.dataset.openMatchRepeat = match ? String(match.repeat_count || 0) : "";
  }

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text || "";
    return div.innerHTML;
  }

  let checkTimer = null;
  async function checkAddress(form) {
    const input = addressInput(form);
    if (!input) return null;
    const address = input.value.trim();
    if (address.length < 3) {
      setAddressWarning(form, null);
      return null;
    }
    const params = new URLSearchParams({ address });
    if (form.dataset.requestId) params.set("exclude_id", form.dataset.requestId);
    try {
      const res = await fetch(`/requests/api/open-by-address?${params.toString()}`, {
        headers: { "X-Requested-With": "XMLHttpRequest" },
      });
      if (!res.ok) return null;
      const data = await res.json();
      if (data.found) {
        setAddressWarning(form, data);
        return data;
      }
      setAddressWarning(form, null);
      return null;
    } catch {
      return null;
    }
  }

  function bindAddressCheck(form) {
    const input = addressInput(form);
    if (!input || input.dataset.repeatBound) return;
    input.dataset.repeatBound = "1";
    const schedule = () => {
      clearTimeout(checkTimer);
      checkTimer = setTimeout(() => checkAddress(form), 350);
    };
    input.addEventListener("input", schedule);
    input.addEventListener("blur", () => checkAddress(form));
  }

  const ADDRESS_FIELDS = [
    "address_selection_token",
    "normalized_address",
    "region",
    "district",
    "settlement",
    "street",
    "house",
    "address_source",
    "address_external_id",
    "latitude",
    "longitude",
  ];

  function setField(form, name, value) {
    const field = form.querySelector(`[name="${name}"]`);
    if (field) field.value = value ?? "";
  }

  function clearAddressSelection(form) {
    ADDRESS_FIELDS.forEach((name) => setField(form, name, ""));
    const input = addressInput(form);
    if (input) delete input.dataset.selectedAddress;
  }

  function syncOriginalAddress(form) {
    const input = addressInput(form);
    if (!input) return;
    if (!input.dataset.selectedAddress) {
      setField(form, "original_address", input.value.trim());
    }
  }

  function applyAddressSuggestion(form, suggestion) {
    const input = addressInput(form);
    if (!input || !suggestion?.normalized_address) return;
    setField(form, "original_address", suggestion.original_address || input.value.trim());
    setField(form, "address_selection_token", suggestion.selection_token);
    ADDRESS_FIELDS.forEach((name) => setField(form, name, suggestion[name]));
    input.value = suggestion.normalized_address;
    input.dataset.selectedAddress = "1";
    input.setAttribute("aria-expanded", "false");
    const status = form.querySelector("[data-address-status]");
    if (status) {
      status.textContent = suggestion.other_settlement
        ? `Выбран другой населённый пункт: ${suggestion.settlement || "Кировская область"}`
        : "Адрес выбран, координаты сохранятся вместе с заявкой.";
      status.classList.toggle("text-warning", !!suggestion.other_settlement);
      status.classList.toggle("text-success", !suggestion.other_settlement);
    }
    const list = form.querySelector("[data-address-suggestions]");
    if (list) {
      list.replaceChildren();
      list.classList.add("d-none");
    }
    checkAddress(form);
  }

  function renderAddressSuggestions(form, suggestions) {
    const list = form.querySelector("[data-address-suggestions]");
    const input = addressInput(form);
    if (!list || !input) return;
    list.replaceChildren();
    suggestions.forEach((suggestion) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "list-group-item list-group-item-action";
      button.setAttribute("role", "option");

      const title = document.createElement("div");
      title.className = "fw-medium";
      title.textContent = suggestion.normalized_address;
      button.appendChild(title);

      const meta = document.createElement("small");
      meta.className = suggestion.other_settlement ? "text-warning-emphasis" : "text-muted";
      meta.textContent = suggestion.other_settlement
        ? `Другой населённый пункт: ${suggestion.settlement || "Кировская область"}`
        : [suggestion.street, suggestion.house ? `дом ${suggestion.house}` : ""]
            .filter(Boolean)
            .join(", ");
      if (meta.textContent) button.appendChild(meta);
      button.addEventListener("click", () => applyAddressSuggestion(form, suggestion));
      list.appendChild(button);
    });
    list.classList.toggle("d-none", suggestions.length === 0);
    input.setAttribute("aria-expanded", suggestions.length ? "true" : "false");
  }

  function bindAddressSuggestions(form) {
    const input = addressInput(form);
    if (!input || input.dataset.suggestionsBound) return;
    input.dataset.suggestionsBound = "1";
    if (form.querySelector("[name='normalized_address']")?.value) {
      input.dataset.selectedAddress = "1";
    } else {
      syncOriginalAddress(form);
    }

    let timer = null;
    let controller = null;
    let sequence = 0;
    const status = form.querySelector("[data-address-status]");
    const list = form.querySelector("[data-address-suggestions]");

    input.addEventListener("input", () => {
      clearTimeout(timer);
      controller?.abort();
      controller = null;
      sequence += 1;
      clearAddressSelection(form);
      syncOriginalAddress(form);
      if (list) {
        list.replaceChildren();
        list.classList.add("d-none");
      }
      input.setAttribute("aria-expanded", "false");
      if (status) {
        status.classList.remove("text-success", "text-warning");
        status.textContent =
          input.value.trim().length < 3
            ? "Введите не менее трёх символов."
            : "Ищем адрес… Сохранение формы не блокируется.";
      }
      if (input.value.trim().length < 3) return;

      const requestSequence = sequence;
      timer = setTimeout(async () => {
        controller = new AbortController();
        try {
          const params = new URLSearchParams({ q: input.value.trim() });
          const response = await fetch(`/requests/api/address-suggestions?${params}`, {
            headers: { "X-Requested-With": "XMLHttpRequest" },
            signal: controller.signal,
          });
          if (!response.ok) throw new Error("suggestions unavailable");
          const data = await response.json();
          if (requestSequence !== sequence) return;
          const suggestions = Array.isArray(data.suggestions) ? data.suggestions : [];
          renderAddressSuggestions(form, suggestions);
          if (status) {
            status.textContent = suggestions.length
              ? "Выберите точный адрес. Другие населённые пункты отмечены отдельно."
              : "Подсказок нет — введённый адрес всё равно можно сохранить.";
          }
        } catch (error) {
          if (error?.name === "AbortError" || requestSequence !== sequence) return;
          if (status) {
            status.textContent =
              "Сервис подсказок недоступен — введённый адрес можно сохранить.";
          }
        }
      }, 400);
    });

    input.addEventListener("blur", () => {
      window.setTimeout(() => {
        list?.classList.add("d-none");
        input.setAttribute("aria-expanded", "false");
      }, 150);
    });
    input.addEventListener("focus", () => {
      if (list?.children.length) {
        list.classList.remove("d-none");
        input.setAttribute("aria-expanded", "true");
      }
    });
  }

  async function markRepeat(form, match) {
    const body = new FormData();
    const csrf = csrfToken();
    if (csrf) body.append("csrf_token", csrf);
    ["phone", "applicant_name", "description", "received_at", "barrier_phone"].forEach((name) => {
      const el = form.querySelector(`[name="${name}"]`);
      if (el && el.value) body.append(name, el.value);
    });
    const barrier = form.querySelector("[name='has_barrier']");
    if (barrier) body.append("has_barrier", barrier.checked ? "true" : "false");

    const res = await fetch(`/requests/${match.id}/mark-repeat`, {
      method: "POST",
      headers: {
        "X-Requested-With": "XMLHttpRequest",
        ...(csrf ? { "X-CSRFToken": csrf } : {}),
      },
      body,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data.success) {
      throw new Error(data.message || "Не удалось зафиксировать повтор");
    }
    return data;
  }

  async function handleCreateSubmit(form, nativeSubmit) {
    syncOriginalAddress(form);
    if (!isCreateForm(form)) {
      return nativeSubmit();
    }
    let match = null;
    if (form.dataset.openMatchId) {
      match = {
        id: form.dataset.openMatchId,
        number: form.dataset.openMatchNumber,
        url: form.dataset.openMatchUrl,
        received_at: form.dataset.openMatchReceived,
        repeat_count: Number(form.dataset.openMatchRepeat || 0),
      };
    } else {
      match = await checkAddress(form);
    }
    if (!match) {
      return nativeSubmit();
    }

    const msg =
      `На адресе уже есть открытая заявка №${match.number}` +
      (match.received_at ? ` (получена ${match.received_at})` : "") +
      `.\n\nЭто повторное обращение?\n\nОК — дописать дату к старой заявке\nОтмена — создать новую заявку`;
    const isRepeat = window.confirm(msg);
    if (!isRepeat) {
      return nativeSubmit();
    }

    const data = await markRepeat(form, match);
    const modalEl = form.closest(".modal");
    if (modalEl && window.bootstrap) {
      bootstrap.Modal.getInstance(modalEl)?.hide();
    }
    if (window.OporaList?.showToast) {
      OporaList.showToast(data.message || "Повторное обращение зафиксировано");
    } else {
      alert(data.message || "Повторное обращение зафиксировано");
    }
    if (data.redirect_url) {
      window.location.href = data.redirect_url;
      return;
    }
    if (match.url) {
      window.location.href = match.url;
    }
  }

  function init(form) {
    if (!form || !form.matches("[data-requests-form]")) return;
    if (form.dataset.requestsInited === "1") return;
    form.dataset.requestsInited = "1";
    toggleBarrier(form);
    bindAddressCheck(form);
    bindAddressSuggestions(form);
    form.addEventListener("submit", () => syncOriginalAddress(form));
  }

  window.OporaRequestsForm = {
    init,
    handleCreateSubmit,
    checkAddress,
  };

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-requests-form]").forEach(init);
  });
})();
