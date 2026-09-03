window.OporaWorkPlanDetail = {
  init() {
    const root = document.getElementById("planDetail");
    if (!root) return;
    if (root.dataset.planDetailInited === "1") return;
    root.dataset.planDetailInited = "1";

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
      const completeModal = document.getElementById("deskCompleteModal");
      const excludeModal = document.getElementById("deskExcludeModal");
      const reportModal = document.getElementById("planReportModal");
      if (completeModal) completeModal.hidden = true;
      if (excludeModal) excludeModal.hidden = true;
      if (reportModal) reportModal.hidden = true;
      pendingId = "";
    }

    function applyPlan(plan) {
      if (!plan) return;
      const meta = root.querySelector(".plan-page__meta");
      if (meta && plan.status_label) {
        const statusNode = meta.querySelector("strong:last-child");
        if (statusNode) statusNode.textContent = plan.status_label;
      }
      const bar = root.querySelector(".plan-progress__bar span");
      const caption = root.querySelector(".plan-progress p");
      const total = plan.total || 0;
      const percent = total ? Math.round(((plan.done + plan.excluded) * 100) / total) : 0;
      if (bar) bar.style.width = `${percent}%`;
      if (caption) {
        caption.textContent = `${plan.done} выполнено · ${plan.excluded} исключено · ${plan.remaining} осталось · ${plan.done + plan.excluded} / ${plan.total}`;
      }
      (plan.items || []).forEach((item) => {
        const article = root.querySelector(`[data-item-id="${item.id}"]`);
        if (!article) return;
        article.dataset.result = item.result;
        const status = article.querySelector(".desk-item__status");
        if (status) {
          status.dataset.code = item.result;
          status.textContent = item.result_label || item.result;
        }
        const actions = article.querySelector(".plan-work__actions");
        if (actions && !item.can_complete) actions.remove();
      });
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

    document.getElementById("planReportOpen")?.addEventListener("click", () => {
      document.getElementById("planReportModal").hidden = false;
    });

    document.getElementById("planReportSend")?.addEventListener("click", () => {
      const recipientId = document.getElementById("planReportRecipient")?.value || "";
      if (!recipientId) {
        toast("Выберите адресата отчёта.", false);
        return;
      }
      const button = document.getElementById("planReportSend");
      button.disabled = true;
      fetch(root.dataset.reportUrl, {
        method: "POST",
        headers: headers(true),
        body: JSON.stringify({ recipient_id: recipientId }),
      })
        .then((res) => res.json())
        .then((body) => {
          if (!body.ok) {
            toast(body.message || "Не удалось сформировать отчёт.", false);
            return;
          }
          closeModals();
          toast(body.message || "Отчёт отправлен в мессенджере.");
        })
        .catch(() => toast("Не удалось сформировать отчёт.", false))
        .finally(() => {
          button.disabled = false;
        });
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
          closeModals();
          applyPlan(body.plan);
          toast(body.message || "Работа выполнена.");
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
          closeModals();
          applyPlan(body.plan);
          toast(body.message || "Работа исключена из плана.");
        })
        .catch(() => toast("Не удалось исключить работу.", false));
    });

    document.querySelectorAll("[data-close-modal]").forEach((btn) => btn.addEventListener("click", closeModals));
  },
};

(function bindWorkPlanDetail() {
  const boot = () => window.OporaWorkPlanDetail.init();
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
  window.addEventListener("opora:navigated", boot);
})();
