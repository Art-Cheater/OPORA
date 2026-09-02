(function () {
  const root = document.getElementById("planCreate");
  if (!root) return;
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const resultsBox = document.getElementById("planSearchResults");
  const basketBox = document.getElementById("planBasket");
  const countBox = document.getElementById("planCount");
  const relatedWrap = document.getElementById("planRelatedWrap");
  const relatedBox = document.getElementById("planRelated");
  const relatedTitle = document.getElementById("planRelatedTitle");
  const addSelectedBtn = document.getElementById("planAddSelected");
  const flashBox = document.getElementById("planFlash");
  const saveBtn = document.getElementById("planSave");
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
    flashBox.textContent = message || "";
    flashBox.style.color = ok === false ? "#DC3545" : "var(--opora-text-muted)";
  }

  function keyOf(type, id) {
    return `${type}:${id}`;
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
    countBox.textContent = String(items.length);
    if (!items.length) {
      basketBox.innerHTML = '<p class="plan-empty">Пока пусто. Добавьте заявки и дефекты слева или из рекомендаций.</p>';
      saveBtn.disabled = true;
      return;
    }
    saveBtn.disabled = false;
    basketBox.innerHTML = items
      .map(
        (item) => `<article class="plan-row">
          <div>
            <strong>№ ${escapeHtml(item.number)}</strong>
            <small>${escapeHtml(item.type_label)} · ${escapeHtml(item.address || "")}${item.pp ? ` · ПП ${escapeHtml(item.pp)}` : ""}</small>
          </div>
          <button type="button" class="is-remove js-remove" data-type="${escapeHtml(item.entity_type)}" data-id="${escapeHtml(item.entity_id)}">Убрать</button>
        </article>`
      )
      .join("");
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
    });
    lastAdded = { entity_type: type, entity_id: id };
    renderBasket();
    loadRelated();
    return true;
  }

  function resultRow(item, actionLabel) {
    const type = item.entity_type || item.type;
    const id = item.entity_id || item.id;
    const already = hasItem(type, id);
    return `<article class="plan-row">
      <div>
        <strong>№ ${escapeHtml(item.number)}</strong>
        <small>${escapeHtml(item.type_label || (type === "defect" ? "Дефект" : "Заявка"))} · ${escapeHtml(item.address || "")}${item.pp ? ` · ПП ${escapeHtml(item.pp)}` : ""}</small>
      </div>
      ${already ? "<small>В плане</small>" : `<button type="button" class="js-add" data-type="${escapeHtml(type)}" data-id="${escapeHtml(id)}" data-number="${escapeHtml(item.number)}" data-address="${escapeHtml(item.address || "")}" data-pp="${escapeHtml(item.pp || "")}" data-label="${escapeHtml(item.type_label || "")}">${escapeHtml(actionLabel)}</button>`}
    </article>`;
  }

  function search(q) {
    const params = new URLSearchParams({ journal: "all", preset: "all", open_only: "1", q: q || "" });
    fetch(`${root.dataset.searchUrl}?${params}`, { headers: headers() })
      .then((res) => res.json())
      .then((data) => {
        const rows = data.items || [];
        if (!rows.length) {
          resultsBox.innerHTML = '<p class="plan-empty">Ничего не найдено среди открытых заявок и дефектов.</p>';
          return;
        }
        resultsBox.innerHTML = rows.map((item) => resultRow(item, "Добавить")).join("");
      })
      .catch(() => toast("Не удалось выполнить поиск.", false));
  }

  function loadRelated() {
    if (!lastAdded) {
      relatedWrap.hidden = true;
      return;
    }
    const params = skipParams();
    params.set("entity_type", lastAdded.entity_type);
    params.set("entity_id", lastAdded.entity_id);
    fetch(`${root.dataset.relatedUrl}?${params}`, { headers: headers() })
      .then((res) => res.json())
      .then((data) => {
        const groups = [
          { key: "by_pp", title: data.pp ? `Ещё работы по ПП ${data.pp}` : "Ещё работы по ПП" },
          { key: "by_address", title: "Другие работы по этому адресу/улице" },
          { key: "by_district", title: "Другие работы по району" },
        ];
        const html = groups
          .map((group) => {
            const rows = (data[group.key] || []).filter((row) => !hasItem(row.entity_type, row.entity_id));
            if (!rows.length) return "";
            return `<h3>${escapeHtml(group.title)}</h3>${rows
              .map(
                (row) => `<label>
                  <input type="checkbox" class="js-pick" data-type="${escapeHtml(row.entity_type)}" data-id="${escapeHtml(row.entity_id)}" data-number="${escapeHtml(row.number)}" data-address="${escapeHtml(row.address || "")}" data-pp="${escapeHtml(row.pp || "")}" data-label="${escapeHtml(row.type_label)}">
                  <span><strong>№ ${escapeHtml(row.number)}</strong> — ${escapeHtml(row.type_label)}<br><small>${escapeHtml(row.address || "")}${row.pp ? ` · ПП ${escapeHtml(row.pp)}` : ""}</small></span>
                </label>`
              )
              .join("")}`;
          })
          .filter(Boolean)
          .join("");
        if (!html) {
          relatedWrap.hidden = true;
          return;
        }
        relatedTitle.textContent = data.pp ? `Ещё работы по ПП ${data.pp}` : "Рекомендации";
        relatedBox.innerHTML = html;
        relatedWrap.hidden = false;
        addSelectedBtn.hidden = false;
      })
      .catch(() => {});
  }

  document.getElementById("planSearch").addEventListener("submit", (event) => {
    event.preventDefault();
    search(event.target.q.value.trim());
  });

  resultsBox.addEventListener("click", (event) => {
    const btn = event.target.closest(".js-add");
    if (!btn) return;
    addItem({
      entity_type: btn.dataset.type,
      entity_id: btn.dataset.id,
      type_label: btn.dataset.label,
      number: btn.dataset.number,
      address: btn.dataset.address,
      pp: btn.dataset.pp,
    });
    search(document.querySelector("#planSearch [name=q]").value.trim());
  });

  basketBox.addEventListener("click", (event) => {
    const btn = event.target.closest(".js-remove");
    if (!btn) return;
    const index = items.findIndex((item) => item.entity_type === btn.dataset.type && item.entity_id === btn.dataset.id);
    if (index >= 0) items.splice(index, 1);
    lastAdded = items[items.length - 1] || null;
    renderBasket();
    loadRelated();
  });

  addSelectedBtn.addEventListener("click", () => {
    relatedBox.querySelectorAll(".js-pick:checked").forEach((input) => {
      addItem({
        entity_type: input.dataset.type,
        entity_id: input.dataset.id,
        type_label: input.dataset.label,
        number: input.dataset.number,
        address: input.dataset.address,
        pp: input.dataset.pp,
      });
    });
  });

  saveBtn.addEventListener("click", () => {
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
        window.location.href = body.redirect;
      })
      .catch(() => {
        saveBtn.disabled = false;
        toast("Не удалось сохранить план.", false);
      });
  });

  renderBasket();
})();
