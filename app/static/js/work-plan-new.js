window.OporaWorkPlanNew = {
  init() {
    const root = document.getElementById("planCreate");
    if (!root) return;
    if (root.dataset.planNewInited === "1") return;
    root.dataset.planNewInited = "1";

    const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
    const resultsBox = document.getElementById("planSearchResults");
    const basketBox = document.getElementById("planBasket");
    const countBox = document.getElementById("planCount");
    const relatedWrap = document.getElementById("planRelatedWrap");
    const relatedBox = document.getElementById("planRelated");
    const relatedTitle = document.getElementById("planRelatedTitle");
    const nearbyToggle = document.getElementById("planNearbyToggle");
    const flashBox = document.getElementById("planFlash");
    const saveBtn = document.getElementById("planSave");
    const mapToggle = document.getElementById("planMapEnabled");
    const mapWrap = document.getElementById("planMapWrap");
    const searchForm = document.getElementById("planSearch");
    const items = [];
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

    function hasItem(type, id) {
      return items.some((item) => item.entity_type === type && item.entity_id === id);
    }

    function skipParams() {
      const params = new URLSearchParams();
      items.forEach((item) => {
        if (item.entity_type === "request") params.append("skip_request", item.entity_id);
        else params.append("skip_defect", item.entity_id);
      });
      return params;
    }

    function renderBasket() {
      if (countBox) countBox.textContent = String(items.length);
      if (!basketBox) return;
      if (!items.length) {
        basketBox.innerHTML = '<p class="plan-empty">Пока пусто. Добавьте заявки и дефекты слева или из рекомендаций.</p>';
        if (saveBtn) saveBtn.disabled = true;
        paintMap();
        return;
      }
      if (saveBtn) saveBtn.disabled = false;
      basketBox.innerHTML = items
        .map(
          (item) => `<article class="plan-row">
            <div>
              <strong>${item.entity_type === "defect" ? "" : "№ "}${escapeHtml(item.number)}</strong>
              <small>${escapeHtml(item.type_label)} · ${escapeHtml(item.address || "")}${item.pp ? ` · ПП ${escapeHtml(item.pp)}` : ""}</small>
            </div>
            <button type="button" class="is-remove js-remove" data-type="${escapeHtml(item.entity_type)}" data-id="${escapeHtml(item.entity_id)}">×</button>
          </article>`
        )
        .join("");
      paintMap();
    }

    function paintMap() {
      if (!mapToggle?.checked || !mapWrap || mapWrap.hidden) return;
      window.OporaOpsMap?.init?.();
      window.OporaOpsMap?.setPoints?.(items.filter((item) => item.lat != null && item.lng != null).map((item) => ({
        id: item.entity_id, type: item.entity_type, number: item.number, address: item.address, lat: item.lat, lng: item.lng, color: item.entity_type === "defect" ? "red" : "blue", in_plan: true,
      })));
    }

    function addItem(row) {
      const type = row.entity_type || row.type;
      const id = row.entity_id || row.id;
      if (!type || !id || hasItem(type, id)) return false;
      items.push({
        entity_type: type,
        entity_id: id,
        type_label: row.type_label || (type === "defect" ? "Дефект" : "Заявка"),
        number: row.number,
        address: row.address || "",
        pp: row.pp || "",
        lat: row.lat,
        lng: row.lng,
      });
      lastAdded = { entity_type: type, entity_id: id };
      renderBasket();
      loadRelated();
      return true;
    }

    function resultRow(item) {
      const type = item.entity_type || item.type;
      const id = item.entity_id || item.id;
      const already = hasItem(type, id) || item.in_plan;
      return `<article class="plan-row">
        <div>
          <strong>${type === "defect" ? "" : "№ "}${escapeHtml(item.number)}</strong>
          <small>${escapeHtml(item.type_label || (type === "defect" ? "Дефект" : "Заявка"))} · ${escapeHtml(item.address || "")}${item.pp ? ` · ПП ${escapeHtml(item.pp)}` : ""}</small>
        </div>
        ${already ? '<button type="button" disabled>В плане</button>' : `<button type="button" class="js-add" data-type="${escapeHtml(type)}" data-id="${escapeHtml(id)}" data-number="${escapeHtml(item.number)}" data-address="${escapeHtml(item.address || "")}" data-pp="${escapeHtml(item.pp || "")}" data-lat="${escapeHtml(item.lat ?? "")}" data-lng="${escapeHtml(item.lng ?? "")}" data-label="${escapeHtml(item.type_label || "")}">Добавить</button>`}
      </article>`;
    }

    function search() {
      const params = new URLSearchParams({ open_only: "1" });
      const pp = searchForm?.pp?.value?.trim();
      const district = searchForm?.district?.value || "";
      const kind = searchForm?.kind?.value || "all";
      if (pp) params.set("pp", pp);
      if (district) params.set("district", district);
      if (kind && kind !== "all") params.set("kind", kind);
      fetch(`${root.dataset.searchUrl}?${params}`, { headers: headers() })
        .then((res) => res.json())
        .then((data) => {
          const rows = data.items || [];
          if (!rows.length) {
            resultsBox.innerHTML = '<p class="plan-empty">Ничего не найдено среди открытых заявок и дефектов.</p>';
            return;
          }
          resultsBox.innerHTML = rows.map((item) => resultRow(item)).join("");
        })
        .catch(() => toast("Не удалось выполнить поиск.", false));
    }

    function loadRelated() {
      if (!lastAdded) {
        if (relatedWrap) relatedWrap.hidden = true;
        if (nearbyToggle) nearbyToggle.hidden = true;
        return;
      }
      const params = skipParams();
      params.set("entity_type", lastAdded.entity_type);
      params.set("entity_id", lastAdded.entity_id);
      fetch(`${root.dataset.relatedUrl}?${params}`, { headers: headers() })
        .then((res) => res.json())
        .then((data) => {
          const rows = (data.hits || []).filter((row) => !hasItem(row.entity_type, row.entity_id));
          if (!rows.length) {
            if (relatedWrap) relatedWrap.hidden = true;
            if (nearbyToggle) nearbyToggle.hidden = true;
            relatedBox.innerHTML = "";
            return;
          }
          if (relatedTitle) relatedTitle.textContent = "Рядом обнаружены другие работы";
          relatedBox.innerHTML = rows
            .map((row) => {
              const already = hasItem(row.entity_type, row.entity_id);
              return `<article class="plan-row">
                <div>
                  <strong>${row.entity_type === "defect" ? "" : "№ "}${escapeHtml(row.number)}</strong>
              <small>${escapeHtml(row.type_label || (row.entity_type === "defect" ? "Дефект" : "Заявка"))} · ${escapeHtml(row.address || "")}${row.nearby_reason ? ` · ${escapeHtml(row.nearby_reason)}` : ""}${row.distance_m ? ` · ${row.distance_m >= 1000 ? `${(row.distance_m / 1000).toFixed(1).replace('.', ',')} км` : `${row.distance_m} м`}` : ""}</small>
                </div>
                ${already ? '<button type="button" disabled>В плане</button>' : `<button type="button" class="js-add" data-type="${escapeHtml(row.entity_type)}" data-id="${escapeHtml(row.entity_id)}" data-number="${escapeHtml(row.number)}" data-address="${escapeHtml(row.address || "")}" data-pp="${escapeHtml(row.pp || "")}" data-lat="${escapeHtml(row.lat ?? "")}" data-lng="${escapeHtml(row.lng ?? "")}" data-label="${escapeHtml(row.type_label)}">Добавить</button>`}
              </article>`;
            })
            .join("");
          if (nearbyToggle) nearbyToggle.hidden = false;
        })
        .catch(() => {});
    }

    searchForm?.addEventListener("submit", (event) => {
      event.preventDefault();
      search();
    });

    resultsBox?.addEventListener("click", (event) => {
      const btn = event.target.closest(".js-add");
      if (!btn) return;
      addItem({
        entity_type: btn.dataset.type,
        entity_id: btn.dataset.id,
        type_label: btn.dataset.label,
        number: btn.dataset.number,
        address: btn.dataset.address,
        pp: btn.dataset.pp,
        lat: btn.dataset.lat || null,
        lng: btn.dataset.lng || null,
      });
      search();
    });

    relatedBox?.addEventListener("click", (event) => {
      const btn = event.target.closest(".js-add");
      if (!btn) return;
      addItem({
        entity_type: btn.dataset.type,
        entity_id: btn.dataset.id,
        type_label: btn.dataset.label,
        number: btn.dataset.number,
        address: btn.dataset.address,
        pp: btn.dataset.pp,
        lat: btn.dataset.lat || null,
        lng: btn.dataset.lng || null,
      });
      search();
    });

    nearbyToggle?.addEventListener("click", () => {
      if (relatedWrap) relatedWrap.hidden = false;
      relatedWrap?.scrollIntoView({ behavior: "smooth", block: "start" });
      nearbyToggle.hidden = true;
    });

    mapToggle?.addEventListener("change", () => {
      if (mapWrap) mapWrap.hidden = !mapToggle.checked;
      paintMap();
    });

    basketBox?.addEventListener("click", (event) => {
      const btn = event.target.closest(".js-remove");
      if (!btn) return;
      const index = items.findIndex((item) => item.entity_type === btn.dataset.type && item.entity_id === btn.dataset.id);
      const removed = index >= 0 ? items[index] : null;
      if (index >= 0) items.splice(index, 1);
      if (removed && lastAdded && removed.entity_type === lastAdded.entity_type && removed.entity_id === lastAdded.entity_id) {
        lastAdded = null;
        if (relatedWrap) relatedWrap.hidden = true;
        if (nearbyToggle) nearbyToggle.hidden = true;
        if (relatedBox) relatedBox.innerHTML = "";
      } else {
        lastAdded = items[items.length - 1] || null;
      }
      renderBasket();
      loadRelated();
      search();
    });

    saveBtn?.addEventListener("click", () => {
      if (!items.length) {
        toast("Добавьте хотя бы одну работу.", false);
        return;
      }
      saveBtn.disabled = true;
      fetch(root.dataset.saveUrl, {
        method: "POST",
        headers: headers(true),
        body: JSON.stringify({
          items: items.map((item) => ({ entity_type: item.entity_type, entity_id: item.entity_id })),
        }),
      })
        .then((res) => res.json())
        .then((body) => {
          if (!body.ok) {
            saveBtn.disabled = false;
            toast(body.message || "Не удалось сохранить план.", false);
            return;
          }
          const href = body.redirect;
          if (href && window.OporaNav?.go) window.OporaNav.go(href);
          else if (href) window.location.href = href;
        })
        .catch(() => {
          saveBtn.disabled = false;
          toast("Не удалось сохранить план.", false);
        });
    });

    renderBasket();
    search();
  },
};

(function bindWorkPlanNew() {
  const boot = () => window.OporaWorkPlanNew.init();
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
  window.addEventListener("opora:navigated", boot);
})();
