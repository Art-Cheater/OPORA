(function () {
  const root = document.getElementById("planDetail");
  if (!root) return;
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
  let pendingId = "";

  function headers(json) {
    const result = { "X-Requested-With": "XMLHttpRequest", Accept: "application/json" };
    if (csrf) result["X-CSRFToken"] = csrf;
    if (json) result["Content-Type"] = "application/json";
    return result;
  }

  function withItem(template, itemId) {
    return String(template || "").replace("11111111-1111-1111-1111-111111111111", itemId);
  }

  function toast(message, ok) {
    const box = document.getElementById("planFlash");
    if (!box) return;
    box.textContent = message || "";
    box.style.color = ok === false ? "#DC3545" : "var(--opora-text-muted)";
  }

  function closeModals() {
    document.getElementById("deskCompleteModal").hidden = true;
    document.getElementById("deskExcludeModal").hidden = true;
    pendingId = "";
  }

  root.addEventListener("click", (event) => {
    const photo = event.target.closest(".js-plan-photo");
    if (photo) {
      event.preventDefault();
      const overlay = document.createElement("div");
      overlay.className = "desk-lightbox";
      overlay.innerHTML = `<img src="${photo.dataset.src || photo.getAttribute("href")}" alt="">`;
      overlay.addEventListener("click", () => overlay.remove());
      document.body.appendChild(overlay);
      return;
    }
    const completeBtn = event.target.closest(".js-plan-complete");
    if (completeBtn) {
      pendingId = completeBtn.dataset.itemId;
      document.getElementById("deskCompleteComment").value = "";
      document.getElementById("deskCompleteFiles").value = "";
      document.getElementById("deskCompleteModal").hidden = false;
      return;
    }
    const excludeBtn = event.target.closest(".js-plan-exclude");
    if (excludeBtn) {
      pendingId = excludeBtn.dataset.itemId;
      document.getElementById("deskExcludeReason").value = "";
      document.getElementById("deskExcludeComment").value = "";
      document.getElementById("deskExcludeModal").hidden = false;
    }
  });

  document.getElementById("deskCompleteSubmit")?.addEventListener("click", () => {
    if (!pendingId) return;
    const data = new FormData();
    data.append("comment", document.getElementById("deskCompleteComment").value.trim());
    Array.from(document.getElementById("deskCompleteFiles").files || []).forEach((file) => data.append("files", file));
    fetch(withItem(root.dataset.completeUrl, pendingId), { method: "POST", headers: headers(), body: data })
      .then((res) => res.json())
      .then((body) => {
        if (!body.ok) {
          toast(body.message || "Не удалось выполнить.", false);
          return;
        }
        window.location.reload();
      })
      .catch(() => toast("Не удалось выполнить работу.", false));
  });

  document.getElementById("deskExcludeSubmit")?.addEventListener("click", () => {
    if (!pendingId) return;
    fetch(withItem(root.dataset.excludeUrl, pendingId), {
      method: "POST",
      headers: headers(true),
      body: JSON.stringify({
        reason: document.getElementById("deskExcludeReason").value,
        comment: document.getElementById("deskExcludeComment").value,
      }),
    })
      .then((res) => res.json())
      .then((body) => {
        if (!body.ok) {
          toast(body.message || "Не удалось исключить.", false);
          return;
        }
        window.location.reload();
      })
      .catch(() => toast("Не удалось исключить работу.", false));
  });

  document.querySelectorAll("[data-close-modal]").forEach((btn) => btn.addEventListener("click", closeModals));
})();
