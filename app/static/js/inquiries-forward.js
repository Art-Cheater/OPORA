(() => {
  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function init(root) {
    const card = root || document.getElementById("inquiryForwardCard");
    if (!card || card.dataset.bound === "1") return;
    card.dataset.bound = "1";

    const search = card.querySelector("#forwardSearch");
    const results = card.querySelector("#forwardResults");
    const errorBox = card.querySelector("#forwardError");
    const selectedBox = card.querySelector("#forwardSelected");
    const selectedName = card.querySelector("#forwardSelectedName");
    const selectedMeta = card.querySelector("#forwardSelectedMeta");
    const clearBtn = card.querySelector("#forwardClear");
    const sendBtn = card.querySelector("#forwardSend");
    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";
    const forwardUrl = card.dataset.forwardUrl;
    let timer = null;
    let sending = false;
    let selected = null;

    function showError(text) {
      if (!errorBox) return;
      errorBox.textContent = text || "";
      errorBox.classList.toggle("d-none", !text);
    }

    function updateSelected() {
      if (!selectedBox || !sendBtn) return;
      if (!selected) {
        selectedBox.classList.add("d-none");
        sendBtn.disabled = true;
        return;
      }
      selectedBox.classList.remove("d-none");
      if (selectedName) selectedName.textContent = selected.full_name || "";
      if (selectedMeta) {
        const meta = [selected.position, selected.department, selected.email]
          .filter(Boolean)
          .join(" · ");
        selectedMeta.textContent = meta;
      }
      sendBtn.disabled = false;
    }

    function chooseUser(user) {
      selected = user;
      showError("");
      if (search) search.value = user.full_name || "";
      if (results) results.innerHTML = "";
      updateSelected();
    }

    function clearSelected() {
      selected = null;
      if (search) search.value = "";
      if (results) results.innerHTML = "";
      showError("");
      updateSelected();
      search?.focus();
    }

    function renderUsers(users) {
      if (!results) return;
      results.innerHTML = "";
      if (!users.length) {
        results.innerHTML = '<div class="list-group-item text-muted small">Сотрудники не найдены</div>';
        return;
      }
      users.forEach((user) => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "list-group-item list-group-item-action";
        const meta = [user.position, user.department].filter(Boolean).join(" · ");
        btn.innerHTML = `<strong>${escapeHtml(user.full_name)}</strong>${
          meta ? `<div class="small text-muted">${escapeHtml(meta)}</div>` : ""
        }`;
        btn.addEventListener("click", () => chooseUser(user));
        results.appendChild(btn);
      });
    }

    async function lookup(query) {
      const res = await fetch(`/messenger/api/users?q=${encodeURIComponent(query || "")}`, {
        headers: { Accept: "application/json" },
        credentials: "same-origin",
      });
      if (!res.ok) {
        showError("Не удалось загрузить контакты. Проверьте доступ к мессенджеру.");
        return;
      }
      const data = await res.json();
      renderUsers(data.users || []);
    }

    async function forwardTo(user) {
      if (sending || !user) return;
      sending = true;
      showError("");
      if (sendBtn) {
        sendBtn.disabled = true;
        sendBtn.textContent = "Отправка…";
      }
      try {
        const res = await fetch(forwardUrl, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Accept: "application/json",
            "X-CSRFToken": csrfToken,
          },
          credentials: "same-origin",
          body: JSON.stringify({ user_id: user.id }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data.ok) {
          showError(data.error || "Не удалось переслать письмо.");
          return;
        }
        if (data.url) {
          window.location.href = data.url;
          return;
        }
        window.location.reload();
      } catch (_err) {
        showError("Сеть недоступна. Попробуйте ещё раз.");
      } finally {
        sending = false;
        if (sendBtn) {
          sendBtn.textContent = "Отправить";
          sendBtn.disabled = !selected;
        }
      }
    }

    search?.addEventListener("input", () => {
      clearTimeout(timer);
      selected = null;
      updateSelected();
      const q = search.value.trim();
      timer = setTimeout(() => lookup(q), 200);
    });
    search?.addEventListener("focus", () => {
      if (!results?.children.length) lookup(search.value.trim());
    });
    clearBtn?.addEventListener("click", clearSelected);
    sendBtn?.addEventListener("click", () => {
      if (!selected) {
        showError("Выберите сотрудника из списка.");
        return;
      }
      forwardTo(selected);
    });

    updateSelected();
    lookup("");
  }

  window.OporaInquiryForward = { init };
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => init());
  } else {
    init();
  }
})();
