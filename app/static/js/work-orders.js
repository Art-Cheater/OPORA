window.OporaWorkOrders = {
  init() {
    const root = document.getElementById("workOrderRoot");
    if (!root) return;
    if (root.dataset.woInited === "1") return;
    root.dataset.woInited = "1";

    const canEdit = root.dataset.canEdit === "true";
    const canComplete = root.dataset.canComplete === "true";
    const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
    const nearbyBox = document.getElementById("workOrderNearby");
    const planBox = document.getElementById("workOrderPlan");
    const itemsBox = document.getElementById("workOrderItems");
    const planTitle = document.getElementById("workOrderPlanTitle");
    const planMeta = document.getElementById("workOrderPlanMeta");
    const filterForm = document.getElementById("workOrderFilters");
    const journalWrap = document.getElementById("woJournalWrap");
    let plan = { id: null, number: null, stops: [], editable: true };
    let routeOn = false;
    let dragId = null;

    function headers(json) {
      const result = { "X-Requested-With": "XMLHttpRequest" };
      if (csrf) result["X-CSRFToken"] = csrf;
      if (json) result["Content-Type"] = "application/json";
      result.Accept = "application/json";
      return result;
    }

    function kindValue() {
      return root.querySelector('input[name="woKind"]:checked')?.value || "all";
    }

    function syncJournalFilter() {
      if (!journalWrap) return;
      journalWrap.hidden = kindValue() !== "request";
    }

    function query() {
      const params = new URLSearchParams();
      const kind = kindValue();
      params.set("kind", kind);
      if (!filterForm) return params;
      const data = new FormData(filterForm);
      for (const [key, value] of data.entries()) {
        if (!value) continue;
        if (key === "journal_id" && kind !== "request") continue;
        params.set(key, value);
      }
      return params;
    }

    function mapUrl() {
      return `${root.dataset.mapUrl}?${query().toString()}`;
    }

    function itemsUrl() {
      return `${root.dataset.itemsUrl}?${query().toString()}`;
    }

    function escapeHtml(value) {
      return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
    }

    function typeMark(type) {
      return type === "defect"
        ? '<span class="workbench-dot workbench-dot--defect" title="Дефект">●</span>'
        : '<span class="workbench-dot workbench-dot--request" title="Заявка">●</span>';
    }

    function itemLabel(type, number) {
      return type === "defect" ? number : `Заявка №${number}`;
    }

    function toast(message, ok) {
      const box = document.getElementById("workOrderFlash");
      if (!box || !message) return;
      box.className = `small mb-0 ${ok ? "text-success" : "text-danger"}`;
      box.textContent = message;
    }

    function addButton(type, id, inPlan) {
      if (!canEdit || plan.editable === false) return "";
      if (inPlan) {
        return '<span class="badge text-bg-secondary">В плане</span>';
      }
      return `<button type="button" class="btn btn-sm btn-primary js-add-to-plan" data-type="${escapeHtml(type)}" data-id="${escapeHtml(id)}">Добавить</button>`;
    }

    function renderNearby(payload) {
      if (!nearbyBox) return;
      const hits = payload?.hits || [];
      if (!hits.length) {
        nearbyBox.innerHTML = `<p class="text-muted small mb-0">${escapeHtml(payload?.summary || "Добавьте работу в план — система предложит ближайшие заявки и дефекты.")}</p>`;
        return;
      }
      nearbyBox.innerHTML = hits
        .map((hit) => {
          const dist = hit.distance_m != null ? `${hit.distance_m} м` : "";
          return `<div class="workbench-hit">
          <div>
            ${typeMark(hit.entity_type)}
            <strong>${escapeHtml(itemLabel(hit.entity_type, hit.number))}</strong>
            <div class="small">${escapeHtml(hit.address || "")}${dist ? " — " + escapeHtml(dist) : ""}</div>
          </div>
          ${addButton(hit.entity_type, hit.entity_id, false)}
        </div>`;
        })
        .join("");
    }

    function renderItems(items) {
      if (!itemsBox) return;
      const rows = items || [];
      if (!rows.length) {
        itemsBox.innerHTML = '<p class="text-muted small p-3 mb-0">Нет доступных работ по текущим фильтрам.</p>';
        return;
      }
      itemsBox.innerHTML = rows
        .map((item) => {
          return `<div class="workbench-hit">
          <div>
            ${typeMark(item.type)}
            <strong>${escapeHtml(itemLabel(item.type, item.number))}</strong>
            <div class="fw-medium">${escapeHtml(item.address || "")}</div>
            <div class="small text-muted">${escapeHtml(item.description || "")}</div>
          </div>
          ${addButton(item.type, item.id, Boolean(item.in_plan))}
        </div>`;
        })
        .join("");
    }

    function renderPlan() {
      if (!planBox) return;
      if (planTitle) {
        planTitle.innerHTML = `<i class="bi bi-list-ol"></i> ${escapeHtml(plan.title || "Мой план работ")}`;
      }
      if (planMeta) {
        const bits = [plan.status_label].filter(Boolean);
        planMeta.textContent = bits.join(" · ");
      }
      const stops = plan.stops || [];
      if (!stops.length) {
        planBox.innerHTML = '<p class="text-muted small p-3 mb-0">План пуст. Добавьте работу из списка справа от карты.</p>';
        return;
      }
      planBox.innerHTML = stops
        .map((stop) => {
          const label = itemLabel(stop.entity_type, stop.number);
          const remove = canEdit && plan.editable !== false
            ? `<button type="button" class="btn btn-sm btn-outline-secondary js-remove-stop" data-stop-id="${escapeHtml(stop.id)}" title="Удалить из плана" aria-label="Удалить из плана">×</button>`
            : "";
          return `<div class="workbench-plan__item" draggable="${canEdit && plan.editable !== false ? "true" : "false"}" data-stop-id="${escapeHtml(stop.id)}">
          <span class="workbench-plan__order">${escapeHtml(stop.order)}</span>
          ${typeMark(stop.entity_type)}
          <div class="workbench-plan__body">
            <strong>${escapeHtml(label)}</strong>
            <div class="small">${escapeHtml(stop.address || "")}</div>
          </div>
          ${remove}
        </div>`;
        })
        .join("");
    }

    function reloadMap() {
      if (window.OporaOpsMap?.reload) {
        window.OporaOpsMap.reload(mapUrl());
      }
    }

    function reloadItems() {
      return fetch(itemsUrl(), { headers: headers(false) })
        .then((r) => r.json())
        .then((data) => renderItems(data.items || []))
        .catch(() => {
          if (itemsBox) itemsBox.innerHTML = '<p class="text-danger small p-3 mb-0">Не удалось загрузить список работ.</p>';
        });
    }

    function applyRoute() {
      if (!routeOn || !window.OporaOpsMap?.setRoute) return;
      window.OporaOpsMap.setRoute(plan.stops || []);
    }

    function refreshLists() {
      renderPlan();
      reloadMap();
      reloadItems();
      applyRoute();
    }

    function loadPlan() {
      return fetch(root.dataset.planUrl, { headers: headers(false) })
        .then((r) => r.json())
        .then((data) => {
          plan = data;
          renderPlan();
          applyRoute();
        });
    }

    function addToPlan(type, id) {
      if (!canEdit) return;
      fetch(root.dataset.addUrl, {
        method: "POST",
        headers: headers(true),
        body: JSON.stringify({ entity_type: type, entity_id: id }),
      })
        .then((r) => r.json().then((body) => ({ ok: r.ok, body })))
        .then(({ ok, body }) => {
          if (!ok || !body.ok) {
            toast(body.message || "Не удалось добавить.", false);
            return;
          }
          plan = body.plan;
          renderPlan();
          renderNearby(body.nearby);
          reloadMap();
          reloadItems();
          applyRoute();
        })
        .catch(() => toast("Не удалось добавить.", false));
    }

    function removeStop(stopId) {
      fetch(root.dataset.removeUrl, {
        method: "POST",
        headers: headers(true),
        body: JSON.stringify({ stop_id: stopId }),
      })
        .then((r) => r.json().then((body) => ({ ok: r.ok, body })))
        .then(({ ok, body }) => {
          if (!ok || !body.ok) {
            toast(body.message || "Не удалось удалить.", false);
            return;
          }
          plan = body.plan;
          refreshLists();
        });
    }

    function saveOrder() {
      const ids = [...planBox.querySelectorAll(".workbench-plan__item")].map((el) => el.dataset.stopId);
      fetch(root.dataset.reorderUrl, {
        method: "POST",
        headers: headers(true),
        body: JSON.stringify({ stop_ids: ids }),
      })
        .then((r) => r.json().then((body) => ({ ok: r.ok, body })))
        .then(({ ok, body }) => {
          if (!ok || !body.ok) {
            toast(body.message || "Не удалось сохранить порядок.", false);
            loadPlan();
            return;
          }
          plan = body.plan;
          renderPlan();
          applyRoute();
        });
    }

    root.addEventListener("opora:add-to-plan", (event) => {
      addToPlan(event.detail.type, event.detail.id);
    });

    root.addEventListener("change", (event) => {
      if (event.target.name === "woKind" || filterForm?.contains(event.target)) {
        syncJournalFilter();
        reloadMap();
        reloadItems();
      }
    });
    filterForm?.addEventListener("submit", (event) => {
      event.preventDefault();
      reloadMap();
      reloadItems();
    });

    itemsBox?.addEventListener("click", (event) => {
      const btn = event.target.closest(".js-add-to-plan");
      if (!btn) return;
      addToPlan(btn.dataset.type, btn.dataset.id);
    });

    nearbyBox?.addEventListener("click", (event) => {
      const btn = event.target.closest(".js-add-to-plan");
      if (!btn) return;
      addToPlan(btn.dataset.type, btn.dataset.id);
    });

    planBox?.addEventListener("click", (event) => {
      const btn = event.target.closest(".js-remove-stop");
      if (!btn) return;
      removeStop(btn.dataset.stopId);
    });

    planBox?.addEventListener("dragstart", (event) => {
      const item = event.target.closest(".workbench-plan__item");
      if (!item || !canEdit) return;
      dragId = item.dataset.stopId;
      event.dataTransfer.effectAllowed = "move";
    });
    planBox?.addEventListener("dragover", (event) => {
      event.preventDefault();
      const item = event.target.closest(".workbench-plan__item");
      if (!item || item.dataset.stopId === dragId) return;
      const rect = item.getBoundingClientRect();
      const before = event.clientY < rect.top + rect.height / 2;
      planBox.insertBefore(
        planBox.querySelector(`[data-stop-id="${dragId}"]`),
        before ? item : item.nextSibling
      );
    });
    planBox?.addEventListener("drop", (event) => {
      event.preventDefault();
      dragId = null;
      saveOrder();
    });
    planBox?.addEventListener("dragend", () => {
      dragId = null;
    });

    document.getElementById("workOrderRouteBtn")?.addEventListener("click", () => {
      routeOn = !routeOn;
      const btn = document.getElementById("workOrderRouteBtn");
      if (routeOn) {
        applyRoute();
        if (btn) btn.classList.add("active");
      } else if (window.OporaOpsMap?.clearRoute) {
        window.OporaOpsMap.clearRoute();
        if (btn) btn.classList.remove("active");
      }
    });

    document.getElementById("workOrderSaveBtn")?.addEventListener("click", () => {
      fetch(root.dataset.saveUrl, { method: "POST", headers: headers(true), body: "{}" })
        .then((r) => r.json().then((body) => ({ ok: r.ok, body })))
        .then(({ ok, body }) => {
          toast(body.message || (ok ? "Сохранено." : "Не удалось сохранить."), Boolean(ok && body.ok));
          if (body.plan) {
            plan = body.plan;
            renderPlan();
          }
        });
    });

    document.getElementById("workOrderCompleteBtn")?.addEventListener("click", () => {
      if (!canComplete) return;
      if (!window.confirm("Завершить путевой лист? Входящие дефекты будут отмечены как выполненные. Статусы заявок не изменятся.")) {
        return;
      }
      fetch(root.dataset.completeUrl, { method: "POST", headers: headers(true), body: "{}" })
        .then((r) => r.json().then((body) => ({ ok: r.ok, body })))
        .then(({ ok, body }) => {
          toast(body.message || (ok ? "Завершено." : "Не удалось завершить."), Boolean(ok && body.ok));
          if (body.plan) {
            plan = body.plan;
            renderNearby({});
            refreshLists();
          }
        });
    });

    syncJournalFilter();
    renderNearby({});
    loadPlan().then(() => {
      reloadMap();
      reloadItems();
    });
  },
};

(function bindWorkOrdersLifecycle() {
  const boot = () => window.OporaWorkOrders.init();
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  }
  window.addEventListener("opora:navigated", boot);
})();
