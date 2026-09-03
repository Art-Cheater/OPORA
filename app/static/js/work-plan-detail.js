window.OporaWorkPlanDetail = {
  init() {
    const root = document.getElementById("planDetail");
    if (!root) return;
    if (root.dataset.planDetailInited === "1") return;
    root.dataset.planDetailInited = "1";

    const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
    const planList = root.querySelector(".plan-detail-list");
    const addPanel = document.getElementById("planAddPanel");
    const addForm = document.getElementById("planAddSearch");
    const addResults = document.getElementById("planAddResults");
    const addRelatedWrap = document.getElementById("planAddRelatedWrap");
    const addRelated = document.getElementById("planAddRelated");
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

    function escapeHtml(value) {
      return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
    }

    function workMarkup(item) {
      const number = item.entity_type === "defect" ? escapeHtml(item.number) : `№ ${escapeHtml(item.number)}`;
      const actions = item.can_complete
        ? `<div class="plan-work__actions">
            <button type="button" class="desk-btn desk-btn--done js-plan-complete" data-item-id="${escapeHtml(item.id)}">Выполнить</button>
            <button type="button" class="desk-btn desk-btn--danger js-plan-exclude" data-item-id="${escapeHtml(item.id)}">Убрать из плана</button>
          </div>`
        : "";
      return `<article class="plan-work" data-result="${escapeHtml(item.result)}" data-item-id="${escapeHtml(item.id)}">
        <div class="plan-work__top"><div><span class="plan-work__kind">${escapeHtml(item.type_label)}</span><h2>${number}</h2></div>
        <span class="desk-item__status" data-code="${escapeHtml(item.result)}">${escapeHtml(item.result_label)}</span></div>
        <p class="plan-work__addr">${escapeHtml(item.address || "Адрес не указан")}</p>
        <p class="plan-work__meta">${item.pp ? `ПП ${escapeHtml(item.pp)}` : "ПП не указан"}${item.status ? ` · ${escapeHtml(item.status)}` : ""}</p>
        ${item.description ? `<p class="plan-work__desc">${escapeHtml(item.description)}</p>` : ""}
        ${actions}</article>`;
    }

    function choiceMarkup(item) {
      const type = item.entity_type || item.type;
      const id = item.entity_id || item.id;
      const label = item.type_label || (type === "defect" ? "Дефект" : "Заявка");
      return `<article class="plan-row">
        <div><strong>${type === "defect" ? "" : "№ "}${escapeHtml(item.number)}</strong>
        <small>${escapeHtml(label)} · ${escapeHtml(item.address || "")}${item.pp ? ` · ПП ${escapeHtml(item.pp)}` : ""}</small></div>
        <button type="button" class="js-plan-add" data-type="${escapeHtml(type)}" data-id="${escapeHtml(id)}">Добавить</button>
      </article>`;
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
      (plan.items || []).forEach((item) => {
        if (planList && !root.querySelector(`[data-item-id="${item.id}"]`)) {
          planList.insertAdjacentHTML("beforeend", workMarkup(item));
        }
      });
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
      const reportButton = document.getElementById("planReportOpen");
      if (reportButton) reportButton.hidden = plan.status !== "completed";
      if (plan.status === "completed") {
        const addButton = document.getElementById("planAddOpen");
        if (addButton) addButton.hidden = true;
        if (addPanel) addPanel.hidden = true;
      }
    }

    function searchAvailable() {
      if (!root.dataset.searchUrl || !addResults) return Promise.resolve();
      const params = new URLSearchParams({ active_only: "1" });
      const pp = addForm?.pp?.value?.trim();
      const district = addForm?.district?.value || "";
      const kind = addForm?.kind?.value || "all";
      if (pp) params.set("pp", pp);
      if (district) params.set("district", district);
      if (kind !== "all") params.set("kind", kind);
      addResults.innerHTML = '<p class="plan-empty">Загрузка работ…</p>';
      return fetch(`${root.dataset.searchUrl}?${params}`, { headers: headers() })
        .then((res) => res.json())
        .then((body) => {
          const rows = body.items || [];
          addResults.innerHTML = rows.length
            ? rows.map(choiceMarkup).join("")
            : '<p class="plan-empty">Доступных работ по текущему фильтру нет.</p>';
        })
        .catch(() => {
          addResults.innerHTML = '<p class="plan-empty">Не удалось загрузить доступные работы.</p>';
        });
    }

    function renderRelated(related) {
      if (!addRelated || !addRelatedWrap) return;
      const seen = new Set();
      const rows = ["by_pp", "by_address", "by_district"].flatMap((key) => related?.[key] || []).filter((item) => {
        const identity = `${item.entity_type}:${item.entity_id}`;
        if (seen.has(identity)) return false;
        seen.add(identity);
        return true;
      });
      addRelatedWrap.hidden = !rows.length;
      addRelated.innerHTML = rows.map(choiceMarkup).join("");
    }

    function addWork(type, id, button) {
      if (!root.dataset.addUrl) return;
      if (button) button.disabled = true;
      fetch(root.dataset.addUrl, {
        method: "POST",
        headers: headers(true),
        body: JSON.stringify({ entity_type: type, entity_id: id }),
      })
        .then((res) => res.json())
        .then((body) => {
          if (!body.ok) {
            toast(body.message || "Не удалось добавить работу.", false);
            return;
          }
          applyPlan(body.plan);
          renderRelated(body.related || {});
          toast(body.message || "Работа добавлена в план.");
          searchAvailable();
        })
        .catch(() => toast("Не удалось добавить работу.", false))
        .finally(() => {
          if (button?.isConnected) button.disabled = false;
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

    document.getElementById("planAddOpen")?.addEventListener("click", () => {
      addPanel.hidden = false;
      searchAvailable();
      addPanel.scrollIntoView({ behavior: "smooth", block: "start" });
    });
    document.getElementById("planAddClose")?.addEventListener("click", () => {
      addPanel.hidden = true;
    });
    addForm?.addEventListener("submit", (event) => {
      event.preventDefault();
      searchAvailable();
    });
    [addResults, addRelated].forEach((box) => box?.addEventListener("click", (event) => {
      const button = event.target.closest(".js-plan-add");
      if (button) addWork(button.dataset.type, button.dataset.id, button);
    }));

    document.getElementById("planReportOpen")?.addEventListener("click", () => {
      const modal = document.getElementById("planReportModal");
      if (modal) modal.hidden = false;
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
