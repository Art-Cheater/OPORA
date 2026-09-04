window.OporaWorkOrders = {
  _abort: null,
  destroy() {
    this._abort?.abort();
    this._abort = null;
  },
  init() {
    const root = document.getElementById("workOrderRoot");
    if (!root) return;
    if (root.dataset.woInited === "1") return;
    root.dataset.woInited = "1";
    this.destroy();
    const abort = new AbortController();
    this._abort = abort;

    const csrf = document.querySelector("meta[name='csrf-token']")?.content || "";
    const itemsBox = document.getElementById("workItems");
    const detailBox = document.getElementById("workDetail");
    const planBox = document.getElementById("workPlan");
    const nearbyBox = document.getElementById("workNearby");
    const nearbyWrap = document.getElementById("workNearbyWrap");
    const nearbyToggle = document.getElementById("workNearbyToggle");
    const nearbySummary = document.getElementById("workNearbySummary");
    const flashBox = document.getElementById("workFlash");
    const filterForm = document.getElementById("workFilters");
    const saveBtn = document.getElementById("workSaveBtn");
    const routeBtn = document.getElementById("workRouteBtn");
    const canEdit = root.dataset.canEdit === "true";
    let plan = { stops: [], editable: true, status: null };
    let nearbyHits = [];
    let lastAdded = null;

    function headers(json) {
      const result = { "X-Requested-With": "XMLHttpRequest", Accept: "application/json" };
      if (csrf) result["X-CSRFToken"] = csrf;
      if (json) result["Content-Type"] = "application/json";
      return result;
    }

    function escapeHtml(value) {
      return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
    }

    function toast(message, ok) {
      if (!flashBox) return;
      flashBox.textContent = message || "";
      flashBox.style.color = ok === false ? "#DC3545" : "var(--opora-text-muted)";
    }

    function filterParams() {
      const params = new URLSearchParams();
      const pp = filterForm?.pp?.value?.trim();
      const district = filterForm?.district?.value || "";
      const kind = filterForm?.kind?.value || "all";
      if (pp) params.set("pp", pp);
      if (district) params.set("district", district);
      if (kind && kind !== "all") params.set("kind", kind);
      return params;
    }

    function typeDot(type) {
      return type === "defect"
        ? '<span class="workbench-dot workbench-dot--defect" aria-hidden="true">●</span>'
        : '<span class="workbench-dot workbench-dot--request" aria-hidden="true">●</span>';
    }

    function typeLabel(type, number) {
      return type === "defect" ? escapeHtml(number || "") : `№ ${escapeHtml(number || "")}`;
    }

    function inPlan(type, id) {
      return (plan.stops || []).some((stop) => stop.entity_type === type && stop.entity_id === id);
    }

    function addButton(type, id, already) {
      if (!canEdit) return "";
      if (already) return '<button type="button" class="is-in-plan" disabled>В плане</button>';
      return `<button type="button" class="js-add" data-type="${escapeHtml(type)}" data-id="${escapeHtml(id)}">Добавить</button>`;
    }

    function renderItems(items) {
      if (!itemsBox) return;
      if (!items.length) {
        itemsBox.innerHTML = '<p class="workbench-empty">По текущему фильтру работ нет.</p>';
        return;
      }
      itemsBox.innerHTML = items
        .map((item) => {
          const type = item.type || item.entity_type;
          const already = item.in_plan || inPlan(type, item.id);
          return `<article class="workbench-hit">
            <div class="workbench-hit__body">
              <strong>${typeDot(type)} ${typeLabel(type, item.number)}</strong>
              <small>${escapeHtml(item.address || "")}${item.pp ? ` · ПП ${escapeHtml(item.pp)}` : ""}</small>
            </div>
            ${addButton(type, item.id, already)}
          </article>`;
        })
        .join("");
    }

    function renderDetail(item) {
      if (!detailBox || !item) return;
      const type = item.type || item.entity_type;
      const id = item.id || item.entity_id;
      detailBox.innerHTML = `<article class="workbench-hit workbench-hit--detail"><div class="workbench-hit__body"><strong>${typeDot(type)} ${typeLabel(type, item.number)}</strong><small>${escapeHtml(item.address || "Адрес не указан")}</small><small>ПП: ${escapeHtml(item.pp || "не указан")} · Район: ${escapeHtml(item.district || "не указан")} · Статус: ${escapeHtml(item.status || "не указан")}</small>${item.description ? `<p>${escapeHtml(item.description)}</p>` : ""}</div><div class="workbench-detail__actions"><a class="btn btn-outline-secondary btn-sm" href="${escapeHtml(item.url || "#")}">Открыть ${type === "defect" ? "дефект" : "заявку"}</a>${addButton(type, id, item.in_plan || inPlan(type, id))}</div></article>`;
    }

    function renderNearby(hits, summary) {
      nearbyHits = hits || [];
      const hasHits = nearbyHits.length > 0;
      if (nearbyToggle) nearbyToggle.hidden = !hasHits;
      if (nearbySummary) nearbySummary.textContent = summary || "";
      if (!nearbyBox) return;
      if (!hasHits) {
        nearbyBox.innerHTML = '<p class="workbench-empty">Рядом других открытых работ нет.</p>';
        return;
      }
      nearbyBox.innerHTML = nearbyHits
        .map((item) => {
          const type = item.entity_type || item.type;
          const id = item.entity_id || item.id;
          const already = inPlan(type, id);
          const dist = item.distance_m ? (item.distance_m >= 1000 ? `${(item.distance_m / 1000).toFixed(1).replace('.', ',')} км` : `${item.distance_m} м`) : "";
          const reason = item.nearby_reason || "";
          const badges = `${reason ? `<span class="workbench-nearby-badge">${escapeHtml(reason)}</span>` : ""}${dist ? `<span class="workbench-distance-badge" title="${reason.includes("≈") ? "Приблизительное расстояние по прямой" : "Расстояние до выбранной работы"}">${escapeHtml(dist)}</span>` : ""}`;
          return `<article class="workbench-hit">
            <div class="workbench-hit__body">
              <strong>${typeDot(type)} ${typeLabel(type, item.number)}</strong>
              <small>${escapeHtml(item.address || "")}</small>
            </div>
            <div class="workbench-nearby-actions">${badges}${addButton(type, id, already)}</div>
          </article>`;
        })
        .join("");
    }

    function renderPlan() {
      const stops = plan.stops || [];
      if (planBox) {
        if (!stops.length) {
          planBox.innerHTML = '<p class="workbench-empty">Пока пусто. Добавьте заявки и дефекты сверху.</p>';
        } else {
          planBox.innerHTML = stops
            .map(
              (stop) => `<article class="workbench-plan__item" data-stop-id="${escapeHtml(stop.id)}" draggable="${plan.editable && canEdit ? "true" : "false"}">
                <span class="workbench-plan__order">${escapeHtml(stop.order)}</span>
                <div class="workbench-plan__body">
                  <strong>${typeDot(stop.entity_type)} ${typeLabel(stop.entity_type, stop.number)}</strong>
                  <small>${escapeHtml(stop.address || "")}</small>
                </div>
                ${plan.editable && canEdit ? `<button type="button" class="workbench-plan__remove js-remove" data-stop-id="${escapeHtml(stop.id)}" title="Удалить">×</button>` : ""}
              </article>`
            )
            .join("");
        }
      }
      if (saveBtn) saveBtn.disabled = !canEdit || !stops.length || !plan.editable;
      if (routeBtn) routeBtn.disabled = stops.length < 1;
    }

    function applyPlan(nextPlan) {
      plan = nextPlan || { stops: [], editable: true, status: null };
      renderPlan();
      refreshMap();
    }

    function refreshMap() {
      const mapNode = document.getElementById("opsMap");
      if (!mapNode || !window.OporaOpsMap) return;
      const url = `${root.dataset.mapUrl}?${filterParams()}`;
      mapNode.setAttribute("data-src", url);
      window.OporaOpsMap.init();
      window.OporaOpsMap.reload?.(url);
    }

    function loadItems() {
      return fetch(`${root.dataset.itemsUrl}?${filterParams()}`, { headers: headers() })
        .then((res) => res.json())
        .then((data) => {
          renderItems(data.items || []);
          refreshMap();
        })
        .catch(() => {
          if (itemsBox) itemsBox.innerHTML = '<p class="workbench-empty">Не удалось загрузить список.</p>';
          toast("Не удалось загрузить работы.", false);
        });
    }

    function loadPlan() {
      return fetch(root.dataset.planUrl, { headers: headers() })
        .then((res) => res.json())
        .then((data) => applyPlan(data))
        .catch(() => toast("Не удалось загрузить план.", false));
    }

    function loadNearby(type, id) {
      lastAdded = { type, id };
      const params = new URLSearchParams({ entity_type: type, entity_id: id });
      return fetch(`${root.dataset.nearbyUrl}?${params}`, { headers: headers() })
        .then((res) => res.json())
        .then((data) => {
          renderNearby(data.hits || [], data.summary || "");
          if (nearbyToggle) nearbyToggle.hidden = !(data.hits || []).length;
        })
        .catch(() => {});
    }

    function addToPlan(type, id) {
      return fetch(root.dataset.addUrl, {
        method: "POST",
        headers: headers(true),
        body: JSON.stringify({ entity_type: type, entity_id: id }),
      })
        .then((res) => res.json())
        .then((body) => {
          if (!body.ok) {
            toast(body.message || "Не удалось добавить.", false);
            return;
          }
          applyPlan(body.plan);
          if (body.nearby) renderNearby(body.nearby.hits || [], body.nearby.summary || "");
          lastAdded = { type, id };
          toast(body.message || "Добавлено в подборку. Нажмите «Создать план».");
          loadItems();
        })
        .catch(() => toast("Не удалось добавить в план.", false));
    }

    filterForm?.addEventListener("submit", (event) => {
      event.preventDefault();
      loadItems();
    });

    itemsBox?.addEventListener("click", (event) => {
      const btn = event.target.closest(".js-add");
      if (!btn || btn.disabled) return;
      addToPlan(btn.dataset.type, btn.dataset.id);
    });

    nearbyBox?.addEventListener("click", (event) => {
      const btn = event.target.closest(".js-add");
      if (!btn || btn.disabled) return;
      addToPlan(btn.dataset.type, btn.dataset.id);
    });

    nearbyToggle?.addEventListener("click", () => {
      if (nearbyWrap) nearbyWrap.hidden = false;
      nearbyWrap?.scrollIntoView({ behavior: "smooth", block: "start" });
      nearbyToggle.hidden = true;
    });

    planBox?.addEventListener("click", (event) => {
      const btn = event.target.closest(".js-remove");
      if (!btn) return;
      const removed = (plan.stops || []).find((stop) => stop.id === btn.dataset.stopId);
      fetch(root.dataset.removeUrl, {
        method: "POST",
        headers: headers(true),
        body: JSON.stringify({ stop_id: btn.dataset.stopId }),
      })
        .then((res) => res.json())
        .then((body) => {
          if (!body.ok) {
            toast(body.message || "Не удалось удалить.", false);
            return;
          }
          applyPlan(body.plan);
          toast(body.message || "Удалено из плана.");
          loadItems();
          if (removed && lastAdded && removed.entity_type === lastAdded.type && removed.entity_id === lastAdded.id) {
            lastAdded = null;
            renderNearby([], "");
            if (nearbyWrap) nearbyWrap.hidden = true;
          } else if (lastAdded) loadNearby(lastAdded.type, lastAdded.id);
        })
        .catch(() => toast("Не удалось удалить из плана.", false));
    });

    saveBtn?.addEventListener("click", () => {
      fetch(root.dataset.saveUrl, { method: "POST", headers: headers(true), body: "{}" })
        .then((res) => res.json())
        .then((body) => {
          if (!body.ok) {
            toast(body.message || "Не удалось сохранить.", false);
            return;
          }
          if (body.redirect && window.OporaNav?.go) {
            window.OporaNav.go(body.redirect, "Открываем план…");
            return;
          }
          if (body.redirect) {
            window.location.href = body.redirect;
            return;
          }
          toast(body.message || "План создан.");
        })
        .catch(() => toast("Не удалось сохранить план.", false));
    });

    routeBtn?.addEventListener("click", () => {
      fetch(root.dataset.routeUrl, { headers: headers() })
        .then((res) => res.json())
        .then((data) => {
          window.OporaOpsMap?.init?.();
          const count = window.OporaOpsMap?.setRoute?.(data.points || [], data.route?.geometry || null) || 0;
          const missing = Number(data.missing || 0);
          if (count < 2 || !data.route?.geometry?.length) {
            toast(count < 2 ? "Маршрут не построен: у выбранных работ пока нет координат." : "Не удалось построить дорожный маршрут. Проверьте подключение сервиса маршрутизации.", false);
          } else if (count === 1) {
            toast(missing ? "Показана одна точка. У остальных работ пока нет координат." : "Показана точка выбранной работы.");
          } else {
            toast(missing ? `Маршрут построен по ${count} точкам. Без координат: ${missing}.` : `Маршрут построен по ${count} точкам.`);
          }
        })
        .catch(() => toast("Не удалось построить маршрут.", false));
    });

    root.addEventListener("opora:add-to-plan", (event) => {
      const type = event.detail?.type;
      const id = event.detail?.id;
      if (type && id) addToPlan(type, id);
    }, { signal: abort.signal });

    root.addEventListener("opora:select-work", (event) => renderDetail(event.detail?.point), { signal: abort.signal });
    detailBox?.addEventListener("click", (event) => {
      const btn = event.target.closest(".js-add");
      if (btn && !btn.disabled) addToPlan(btn.dataset.type, btn.dataset.id);
    });

    let dragId = "";
    planBox?.addEventListener("dragstart", (event) => {
      const row = event.target.closest("[data-stop-id]");
      if (!row || !plan.editable) return;
      dragId = row.dataset.stopId;
    });
    planBox?.addEventListener("dragover", (event) => event.preventDefault());
    planBox?.addEventListener("drop", (event) => {
      event.preventDefault();
      const row = event.target.closest("[data-stop-id]");
      if (!row || !dragId || dragId === row.dataset.stopId) return;
      const ids = Array.from(planBox.querySelectorAll("[data-stop-id]")).map((node) => node.dataset.stopId);
      const from = ids.indexOf(dragId);
      const to = ids.indexOf(row.dataset.stopId);
      if (from < 0 || to < 0) return;
      ids.splice(to, 0, ids.splice(from, 1)[0]);
      fetch(root.dataset.reorderUrl, {
        method: "POST",
        headers: headers(true),
        body: JSON.stringify({ stop_ids: ids }),
      })
        .then((res) => res.json())
        .then((body) => {
          if (!body.ok) {
            toast(body.message || "Не удалось изменить порядок.", false);
            return;
          }
          applyPlan(body.plan);
        })
        .catch(() => toast("Не удалось изменить порядок.", false));
    });

    Promise.all([loadPlan(), loadItems()]).then(() => {
      window.OporaOpsMap?.init?.();
    });
  },
};

(function bindWorkOrdersLifecycle() {
  const boot = () => window.OporaWorkOrders.init();
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
  window.addEventListener("opora:navigated", boot);
})();
