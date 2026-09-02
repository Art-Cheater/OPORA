window.OporaWorkOrders = {
  _bound: false,
  init() {
  const root = document.getElementById("workOrderRoot");
  if (!root || root.dataset.woInited === "1") return;
  root.dataset.woInited = "1";

  const canEdit = root.dataset.canEdit === "true";
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const nearbyBox = document.getElementById("workOrderNearby");
  const planBox = document.getElementById("workOrderPlan");
  const planNumber = document.getElementById("workOrderPlanNumber");
  const filterForm = document.getElementById("workOrderFilters");
  let plan = { id: null, number: null, stops: [] };
  let routeOn = false;
  let dragId = null;

  function headers(json) {
    const result = { "X-Requested-With": "XMLHttpRequest" };
    if (csrf) result["X-CSRFToken"] = csrf;
    if (json) result["Content-Type"] = "application/json";
    result.Accept = "application/json";
    return result;
  }

  function query() {
    const params = new URLSearchParams();
    const kind = document.querySelector('input[name="woKind"]:checked')?.value || "all";
    params.set("kind", kind);
    if (!filterForm) return params;
    const data = new FormData(filterForm);
    for (const [key, value] of data.entries()) {
      if (value) params.set(key, value);
    }
    return params;
  }

  function mapUrl() {
    return `${root.dataset.mapUrl}?${query().toString()}`;
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

  function toast(message, ok) {
    const box = document.getElementById("workOrderFlash");
    if (!box || !message) return;
    box.className = `small mb-0 ${ok ? "text-success" : "text-danger"}`;
    box.textContent = message;
  }

  function renderNearby(payload) {
    if (!nearbyBox) return;
    const hits = payload?.hits || [];
    if (!hits.length) {
      nearbyBox.innerHTML = `<p class="text-muted small mb-0">${escapeHtml(payload?.summary || "Рядом открытых работ не найдено.")}</p>`;
      return;
    }
    const rows = hits
      .map((hit) => {
        const dist = hit.distance_m != null ? `~${hit.distance_m} м` : "";
        const add = canEdit
          ? `<button type="button" class="btn btn-sm btn-outline-primary js-add-to-plan" data-type="${escapeHtml(hit.entity_type)}" data-id="${escapeHtml(hit.entity_id)}">Добавить в план</button>`
          : "";
        return `<div class="workbench-hit">
          <div>
            ${typeMark(hit.entity_type)}
            <strong>${escapeHtml(hit.entity_type === "defect" ? hit.number : "Заявка №" + hit.number)}</strong>
            <div class="small">${escapeHtml(hit.address || "")}</div>
            <div class="small text-muted">${escapeHtml(dist)}</div>
          </div>
          ${add}
        </div>`;
      })
      .join("");
    nearbyBox.innerHTML = `<p class="small fw-semibold mb-2">Рядом обнаружены другие работы</p>${rows}`;
  }

  function renderPlan() {
    if (!planBox) return;
    if (planNumber) planNumber.textContent = plan.number ? plan.number : "";
    const stops = plan.stops || [];
    if (!stops.length) {
      planBox.innerHTML = '<p class="text-muted small p-3 mb-0">План пуст. Выберите дефект или заявку на карте.</p>';
      return;
    }
    planBox.innerHTML = stops
      .map((stop) => {
        const label = stop.entity_type === "defect" ? stop.number : `Заявка №${stop.number}`;
        const remove = canEdit
          ? `<button type="button" class="btn btn-sm btn-outline-secondary js-remove-stop" data-stop-id="${escapeHtml(stop.id)}" title="Убрать">×</button>`
          : "";
        return `<div class="workbench-plan__item" draggable="${canEdit ? "true" : "false"}" data-stop-id="${escapeHtml(stop.id)}">
          <span class="workbench-plan__order">${escapeHtml(stop.order)}</span>
          ${typeMark(stop.entity_type)}
          <div class="workbench-plan__body">
            <a href="${escapeHtml(stop.url)}">${escapeHtml(label)}</a>
            <div class="small">${escapeHtml(stop.address || "")}</div>
            <div class="small text-muted">${escapeHtml(stop.status || "")}${stop.description ? " · " + escapeHtml(stop.description) : ""}</div>
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

  function applyRoute() {
    if (!routeOn || !window.OporaOpsMap?.setRoute) return;
    window.OporaOpsMap.setRoute(plan.stops || []);
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
        renderPlan();
        reloadMap();
        applyRoute();
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

  document.querySelectorAll('input[name="woKind"]').forEach((input) => {
    input.addEventListener("change", reloadMap);
  });
  filterForm?.addEventListener("change", reloadMap);
  filterForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    reloadMap();
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
    if (routeOn) {
      applyRoute();
    } else if (window.OporaOpsMap?.clearRoute) {
      window.OporaOpsMap.clearRoute();
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

  renderNearby({});
  loadPlan().then(reloadMap);
  },
};

document.addEventListener("DOMContentLoaded", () => window.OporaWorkOrders.init());
