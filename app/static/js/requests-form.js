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

  async function formatAddressField(form) {
    const input = addressInput(form);
    if (!input) return;
    const raw = (input.value || "").trim();
    if (raw.length < 2) return;
    try {
      const res = await fetch(
        `/requests/api/format-address?address=${encodeURIComponent(raw)}`,
        { headers: { "X-Requested-With": "XMLHttpRequest" } }
      );
      if (!res.ok) return;
      const data = await res.json();
      if (data.address && data.address !== raw) {
        input.value = data.address;
      }
    } catch {
      /* ignore */
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
    input.addEventListener("blur", async () => {
      await formatAddressField(form);
      await checkAddress(form);
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
