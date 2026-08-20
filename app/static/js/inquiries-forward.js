(() => {
  const card = document.getElementById("inquiryForwardCard");
  if (!card) return;

  const search = document.getElementById("forwardSearch");
  const results = document.getElementById("forwardResults");
  const errorBox = document.getElementById("forwardError");
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const forwardUrl = card.dataset.forwardUrl;
  let timer = null;
  let sending = false;

  function showError(text) {
    if (!errorBox) return;
    errorBox.textContent = text || "";
    errorBox.classList.toggle("d-none", !text);
  }

  function renderUsers(users) {
    results.innerHTML = "";
    if (!users.length) {
      results.innerHTML = '<div class="text-muted small">Сотрудники не найдены</div>';
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
      btn.addEventListener("click", () => forwardTo(user));
      results.appendChild(btn);
    });
  }

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  async function lookup(query) {
    const res = await fetch(`/messenger/api/users?q=${encodeURIComponent(query)}`, {
      headers: { Accept: "application/json" },
    });
    if (!res.ok) {
      showError("Не удалось загрузить контакты.");
      return;
    }
    const data = await res.json();
    renderUsers(data.users || []);
  }

  async function forwardTo(user) {
    if (sending) return;
    sending = true;
    showError("");
    try {
      const res = await fetch(forwardUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
          "X-CSRFToken": csrfToken,
        },
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
    } finally {
      sending = false;
    }
  }

  search.addEventListener("input", () => {
    clearTimeout(timer);
    const q = search.value.trim();
    timer = setTimeout(() => lookup(q), 250);
  });
  search.addEventListener("focus", () => {
    if (!results.children.length) lookup(search.value.trim());
  });
})();
