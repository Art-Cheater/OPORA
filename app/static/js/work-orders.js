window.OporaWorkOrders = {
  init() {
    const root = document.getElementById("workDesk");
    if (!root) return;
    if (root.dataset.woInited === "1") return;
    root.dataset.woInited = "1";

    const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
    const queueBox = document.getElementById("deskQueue");
    const pagerBox = document.getElementById("deskPager");
    const metaBox = document.getElementById("deskQueueMeta");
    const panelEmpty = document.getElementById("deskPanelEmpty");
    const panelBody = document.getElementById("deskPanelBody");
    const panelHead = document.getElementById("deskPanelHead");
    const searchForm = document.getElementById("deskSearch");
    const workspace = document.getElementById("deskWorkspace");
    const plansView = document.getElementById("deskPlans");
    const planView = document.getElementById("deskPlanView");
    const draftTray = document.getElementById("deskDraftTray");
    const draftMeta = document.getElementById("deskDraftMeta");
    const flashBox = document.getElementById("deskFlash");
    const canCompleteDesk = root.dataset.canComplete === "true";
    const canCompleteDefect = root.dataset.canCompleteDefect === "true";
    const canManage = root.dataset.canManage === "true";

    let preset = "all";
    let journal = "all";
    let page = 1;
    let selectedId = "";
    let selectedType = "request";
    let mode = "desk";
    let draft = null;
    let openPlan = null;
    let selectedPlanItemId = "";
    let related = null;
    let pendingAction = null;
    let queueAbort = null;
    let cardAbort = null;

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

    function withId(template, id, secondId) {
      let url = String(template || "").replace("00000000-0000-0000-0000-000000000000", id);
      if (secondId) url = url.replace("11111111-1111-1111-1111-111111111111", secondId);
      return url;
    }

    function toast(message, ok) {
      if (!flashBox) return;
      flashBox.textContent = message || "";
      flashBox.style.color = ok === false ? "#DC3545" : "var(--opora-text-muted)";
    }

    function query() {
      const params = new URLSearchParams();
      params.set("preset", preset);
      params.set("journal", journal);
      params.set("page", String(page));
      const q = searchForm?.querySelector('[name="q"]')?.value?.trim();
      if (q) params.set("q", q);
      return params;
    }

    function showMode(next) {
      mode = next;
      root.classList.toggle("is-compose", next === "compose");
      workspace.hidden = next !== "desk" && next !== "compose";
      plansView.hidden = next !== "plans";
      planView.hidden = next !== "plan";
      const title = document.getElementById("deskTitle");
      if (title) {
        title.textContent =
          next === "compose" ? "Формирование плана работ" : next === "plans" ? "Мои планы" : next === "plan" ? "План работ" : "Работа с заявками";
      }
    }

    function inDraft(entityType, entityId) {
      return Boolean((draft?.items || []).find((item) => item.entity_type === entityType && item.entity_id === entityId));
    }

    function renderDraftTray() {
      if (!draftTray || !draftMeta) return;
      if (mode !== "compose" || !draft) {
        draftTray.hidden = true;
        draftMeta.hidden = true;
        return;
      }
      const items = draft.items || [];
      draftMeta.hidden = false;
      draftMeta.textContent = items.length ? `Черновик: ${items.length} работ` : "Черновик пуст — добавьте работы из очереди";
      draftTray.hidden = false;
      const chips = items
        .map(
          (item) => `<span class="desk-chip-item">№ ${escapeHtml(item.number)}
            <button type="button" class="js-draft-remove" data-item-id="${escapeHtml(item.id)}" aria-label="Убрать">×</button></span>`
        )
        .join("");
      const save = items.length
        ? `<button type="button" class="desk-btn desk-btn--accent" id="deskSavePlan">Сохранить план</button>`
        : "";
      draftTray.innerHTML = `${chips}${save}`;
    }

    function renderQueue(data) {
      const items = data.items || [];
      if (metaBox) metaBox.textContent = data.total ? `${data.total}` : "";
      if (!items.length) {
        queueBox.innerHTML = '<p class="desk__empty">По текущему фильтру работ нет.</p>';
        if (pagerBox) pagerBox.hidden = true;
        return;
      }
      queueBox.innerHTML = items
        .map((item) => {
          const active = item.id === selectedId ? " is-active" : "";
          const kind = item.entity_type || item.type || "request";
          const canDone = kind === "defect" ? canCompleteDefect : canCompleteDesk;
          const complete =
            mode !== "compose" && canDone && item.can_complete
              ? `<button type="button" class="desk-btn desk-btn--done js-desk-complete" data-id="${escapeHtml(item.id)}" data-type="${escapeHtml(kind)}">Выполнено</button>`
              : "";
          const add =
            mode === "compose" && canManage && !inDraft(kind, item.id)
              ? `<button type="button" class="desk-btn desk-btn--accent js-desk-add" data-id="${escapeHtml(item.id)}" data-type="${escapeHtml(kind)}">В план</button>`
              : mode === "compose" && inDraft(kind, item.id)
                ? `<span class="desk-item__kind">В плане</span>`
                : "";
          return `<article class="desk-item${active}" data-id="${escapeHtml(item.id)}" data-type="${escapeHtml(kind)}" tabindex="0">
            <div class="desk-item__top">
              <div>
                <div class="desk-item__kind">${escapeHtml(item.type_label || (kind === "defect" ? "Дефект" : "Заявка"))}</div>
                <div class="desk-item__number">№ ${escapeHtml(item.number)}</div>
              </div>
              <span class="desk-item__status" data-code="${escapeHtml(item.status_code || "")}">${escapeHtml(item.status || "—")}</span>
            </div>
            <p class="desk-item__address">${escapeHtml(item.address || "Адрес не указан")}</p>
            <p class="desk-item__district">${escapeHtml(item.pp ? `ПП ${item.pp}` : "ПП не указан")} · ${escapeHtml(item.district || "Район не указан")}</p>
            <div class="desk-item__actions">
              <button type="button" class="desk-btn js-desk-open" data-id="${escapeHtml(item.id)}" data-type="${escapeHtml(kind)}">Открыть</button>
              ${add}${complete}
            </div>
          </article>`;
        })
        .join("");
      const pages = Number(data.pages || 1);
      if (!pagerBox) return;
      if (pages <= 1) {
        pagerBox.hidden = true;
        pagerBox.innerHTML = "";
        return;
      }
      pagerBox.hidden = false;
      const buttons = [];
      for (let i = 1; i <= pages && i <= 12; i += 1) {
        buttons.push(`<button type="button" class="desk__pager-btn${i === data.page ? " is-active" : ""}" data-page="${i}">${i}</button>`);
      }
      pagerBox.innerHTML = buttons.join("");
    }

    function field(label, value) {
      const text = (value || "").toString().trim();
      if (!text) return "";
      return `<div class="desk-card__block">
        <p class="desk-card__label">${escapeHtml(label)}</p>
        <p class="desk-card__value">${escapeHtml(text)}</p>
      </div>`;
    }

    function relatedBlock(data) {
      if (!data) return "";
      const groups = [
        { key: "by_pp", title: data.pp ? `Другие работы по ПП ${data.pp}` : "Другие работы по ПП" },
        { key: "by_address", title: "Другие работы по этому адресу/улице" },
        { key: "by_district", title: "Другие работы по району" },
      ];
      const parts = groups
        .map((group) => {
          const rows = data[group.key] || [];
          if (!rows.length) return "";
          const list = rows
            .map((row) => {
              const already = inDraft(row.entity_type, row.entity_id);
              const action =
                mode === "compose" && canManage && !already
                  ? `<button type="button" class="desk-btn desk-btn--accent js-desk-add" data-id="${escapeHtml(row.entity_id)}" data-type="${escapeHtml(row.entity_type)}">В план</button>`
                  : already
                    ? `<small>Уже в плане</small>`
                    : "";
              return `<label class="desk-related__row">
                <div>
                  <strong>№ ${escapeHtml(row.number)}</strong> — ${escapeHtml(row.type_label)}
                  <br><small>${escapeHtml(row.address || "")}${row.pp ? ` · ПП ${escapeHtml(row.pp)}` : ""}</small>
                </div>
                ${action}
              </label>`;
            })
            .join("");
          return `<div class="desk-related"><h3>${escapeHtml(group.title)}</h3><div class="desk-related__list">${list}</div></div>`;
        })
        .filter(Boolean);
      return parts.join("");
    }

    function cardHtml(card, extraActions) {
      const photos = (card.photos || [])
        .map(
          (file) =>
            `<a class="js-desk-photo" href="${escapeHtml(file.preview_url || file.download_url)}" data-src="${escapeHtml(file.preview_url || file.download_url)}"><img src="${escapeHtml(file.preview_url || file.download_url)}" alt="${escapeHtml(file.name || "")}"></a>`
        )
        .join("");
      const docs = (card.documents || [])
        .map((file) => `<a href="${escapeHtml(file.download_url)}">${escapeHtml(file.name)}</a>`)
        .join("");
      const history = (card.history || [])
        .map(
          (entry) =>
            `<li><strong>${escapeHtml(entry.comment || entry.action || "Событие")}</strong><span>${escapeHtml(entry.user || "")} · ${escapeHtml(entry.created_at || "")}${entry.status ? ` · ${escapeHtml(entry.status)}` : ""}</span></li>`
        )
        .join("");
      return `${field("Тип", card.type_label)}
        ${field("Адрес", card.address)}
        ${field("ПП", card.pp ? `ПП ${card.pp}` : "")}
        ${field("Район", card.district)}
        ${field("Описание", card.description)}
        ${field("Журнал", card.journal)}
        ${field("Заявитель", card.applicant_name)}
        ${field("Диспетчер", card.dispatcher_name)}
        ${photos ? `<div class="desk-card__block"><p class="desk-card__label">Фотографии</p><div class="desk-photos">${photos}</div></div>` : ""}
        ${docs ? `<div class="desk-card__block"><p class="desk-card__label">Файлы</p><div class="desk-docs">${docs}</div></div>` : ""}
        ${history ? `<div class="desk-card__block"><p class="desk-card__label">История</p><ul class="desk-history">${history}</ul></div>` : ""}
        ${extraActions || ""}
        ${relatedBlock(related)}`;
    }

    function renderCard(card) {
      if (!card) {
        panelBody.hidden = true;
        panelHead.hidden = true;
        panelEmpty.hidden = false;
        return;
      }
      panelEmpty.hidden = true;
      panelHead.hidden = false;
      panelBody.hidden = false;
      const kind = card.entity_type || card.type || "request";
      const canDone = kind === "defect" ? canCompleteDefect : canCompleteDesk;
      const complete =
        mode !== "compose" && canDone && card.can_complete
          ? `<button type="button" class="desk-btn desk-btn--done js-desk-complete" data-id="${escapeHtml(card.id)}" data-type="${escapeHtml(kind)}">Выполнено</button>`
          : "";
      const add =
        mode === "compose" && canManage && !inDraft(kind, card.id)
          ? `<button type="button" class="desk-btn desk-btn--accent js-desk-add" data-id="${escapeHtml(card.id)}" data-type="${escapeHtml(kind)}">Добавить в план</button>`
          : "";
      panelHead.innerHTML = `<div>
          <h2 class="desk__panel-title">№ ${escapeHtml(card.number)}</h2>
        </div>
        <span class="desk-item__status" data-code="${escapeHtml(card.status_code || "")}">${escapeHtml(card.status || "—")}</span>`;
      panelBody.innerHTML = cardHtml(card, complete || add ? `<div class="desk-card__actions">${add}${complete}</div>` : "");
    }

    function loadQueue() {
      if (queueAbort) queueAbort.abort();
      queueAbort = new AbortController();
      fetch(`${root.dataset.queueUrl}?${query()}`, { headers: headers(), signal: queueAbort.signal })
        .then((res) => res.json())
        .then((data) => {
          renderDraftTray();
          renderQueue(data);
        })
        .catch((err) => {
          if (err.name !== "AbortError") toast("Не удалось загрузить очередь.", false);
        });
    }

    function loadCard(id, type) {
      selectedId = id;
      selectedType = type || "request";
      const url = selectedType === "defect" ? withId(root.dataset.defectCardUrl, id) : withId(root.dataset.requestCardUrl, id);
      if (cardAbort) cardAbort.abort();
      cardAbort = new AbortController();
      fetch(url, { headers: headers(), signal: cardAbort.signal })
        .then((res) => res.json())
        .then((card) => {
          if (card.message && card.ok === false) {
            toast(card.message, false);
            return;
          }
          renderCard(card);
          if (mode === "compose") loadRelated(selectedType, id);
          root.querySelectorAll("#deskQueue .desk-item").forEach((el) => el.classList.toggle("is-active", el.dataset.id === id));
        })
        .catch((err) => {
          if (err.name !== "AbortError") toast("Не удалось открыть карточку.", false);
        });
    }

    function loadRelated(entityType, entityId) {
      const params = new URLSearchParams({ entity_type: entityType, entity_id: entityId });
      if (draft?.id) params.set("plan_id", draft.id);
      fetch(`${root.dataset.relatedUrl}?${params}`, { headers: headers() })
        .then((res) => res.json())
        .then((data) => {
          related = data;
          const url = entityType === "defect" ? withId(root.dataset.defectCardUrl, entityId) : withId(root.dataset.requestCardUrl, entityId);
          return fetch(url, { headers: headers() });
        })
        .then((res) => (res ? res.json() : null))
        .then((card) => {
          if (card && !card.message) renderCard(card);
        })
        .catch(() => {});
    }

    function completeQueue(id, type) {
      const url = type === "defect" ? withId(root.dataset.defectCompleteUrl, id) : withId(root.dataset.requestCompleteUrl, id);
      fetch(url, { method: "POST", headers: headers(true), body: "{}" })
        .then((res) => res.json())
        .then((body) => {
          if (!body.ok) {
            toast(body.message || "Не удалось выполнить.", false);
            return;
          }
          toast(body.message || "Выполнено.", true);
          if (body.card) renderCard(body.card);
          loadQueue();
        })
        .catch(() => toast("Не удалось отметить работу.", false));
    }

    function addToPlan(entityType, entityId) {
      if (!draft?.id) return;
      fetch(withId(root.dataset.planAddUrl, draft.id), {
        method: "POST",
        headers: headers(true),
        body: JSON.stringify({ entity_type: entityType, entity_id: entityId }),
      })
        .then((res) => res.json())
        .then((body) => {
          if (!body.ok) {
            toast(body.message || "Не удалось добавить.", false);
            return;
          }
          draft = body.plan;
          related = body.related || related;
          toast(body.message, true);
          renderDraftTray();
          loadQueue();
          loadCard(entityId, entityType);
        })
        .catch(() => toast("Не удалось добавить в план.", false));
    }

    function removeDraftItem(itemId) {
      if (!draft?.id) return;
      fetch(withId(root.dataset.planRemoveUrl, draft.id, itemId), {
        method: "POST",
        headers: headers(true),
        body: JSON.stringify({ action: "remove" }),
      })
        .then((res) => res.json())
        .then((body) => {
          if (!body.ok) {
            toast(body.message || "Не удалось убрать.", false);
            return;
          }
          draft = body.plan;
          toast(body.message, true);
          renderDraftTray();
          loadQueue();
        })
        .catch(() => toast("Не удалось убрать из черновика.", false));
    }

    function saveDraft() {
      if (!draft?.id) return;
      fetch(withId(root.dataset.planSaveUrl, draft.id), { method: "POST", headers: headers(true), body: "{}" })
        .then((res) => res.json())
        .then((body) => {
          if (!body.ok) {
            toast(body.message || "Не удалось сохранить план.", false);
            return;
          }
          toast(body.message, true);
          draft = null;
          related = null;
          openPlan = body.plan;
          showMode("plan");
          renderOpenPlan();
        })
        .catch(() => toast("Не удалось сохранить план.", false));
    }

    function startCompose() {
      fetch(root.dataset.draftUrl, { method: "POST", headers: headers(true), body: "{}" })
        .then((res) => res.json())
        .then((body) => {
          if (!body.ok) {
            toast(body.message || "Нельзя создать план.", false);
            return;
          }
          draft = body.plan;
          showMode("compose");
          renderDraftTray();
          loadQueue();
        })
        .catch(() => toast("Не удалось открыть черновик.", false));
    }

    function renderPlans(plans) {
      const grid = document.getElementById("deskPlansGrid");
      if (!grid) return;
      if (!plans.length) {
        grid.innerHTML = '<p class="desk__empty">Планов пока нет.</p>';
        return;
      }
      grid.innerHTML = plans
        .map(
          (plan) => `<button type="button" class="desk-plan-card js-open-plan" data-id="${escapeHtml(plan.id)}">
            <div class="desk-plan-card__num">${escapeHtml(plan.number)}</div>
            <span class="desk-item__status" data-code="${escapeHtml(plan.status)}">${escapeHtml(plan.status_label)}</span>
            <p class="desk-plan-card__meta">${escapeHtml(plan.created_date || plan.created_at)} · ${escapeHtml(plan.master)}</p>
            <p class="desk-plan-card__meta">${plan.total} работ · ${plan.done} выполнено · ${plan.excluded} исключено</p>
            ${plan.completed_at ? `<p class="desk-plan-card__meta">Завершён: ${escapeHtml(plan.completed_at)}</p>` : ""}
          </button>`
        )
        .join("");
    }

    function loadPlans() {
      fetch(root.dataset.plansUrl, { headers: headers() })
        .then((res) => res.json())
        .then((data) => {
          showMode("plans");
          renderPlans(data.plans || []);
        })
        .catch(() => toast("Не удалось загрузить планы.", false));
    }

    function planItemCard(item) {
      const actions = [];
      if (item.can_complete) {
        actions.push(`<button type="button" class="desk-btn desk-btn--done js-plan-complete" data-item-id="${escapeHtml(item.id)}">Выполнить</button>`);
      }
      if (item.can_exclude) {
        actions.push(`<button type="button" class="desk-btn desk-btn--danger js-plan-exclude" data-item-id="${escapeHtml(item.id)}">Убрать из плана</button>`);
      }
      const extra = [];
      if (item.complete_comment) extra.push(field("Комментарий о выполнении", item.complete_comment));
      if (item.exclude_reason_label) extra.push(field("Причина исключения", item.exclude_reason_label));
      if (item.exclude_comment) extra.push(field("Комментарий исключения", item.exclude_comment));
      const photos = (item.photos || [])
        .map(
          (file) =>
            `<a class="js-desk-photo" href="${escapeHtml(file.preview_url)}" data-src="${escapeHtml(file.preview_url)}"><img src="${escapeHtml(file.preview_url)}" alt=""></a>`
        )
        .join("");
      return `${field("Тип", item.type_label)}
        ${field("Адрес", item.address)}
        ${field("ПП", item.pp ? `ПП ${item.pp}` : "")}
        ${field("Описание", item.description)}
        ${field("Статус работы", item.status)}
        ${field("Состояние в плане", item.result_label)}
        ${extra.join("")}
        ${photos ? `<div class="desk-card__block"><p class="desk-card__label">Фотографии</p><div class="desk-photos">${photos}</div></div>` : ""}
        ${actions.length ? `<div class="desk-card__actions">${actions.join("")}</div>` : ""}`;
    }

    function renderOpenPlan() {
      if (!openPlan) return;
      const head = document.getElementById("deskPlanHead");
      const itemsBox = document.getElementById("deskPlanItems");
      const meta = document.getElementById("deskPlanMeta");
      const title = document.getElementById("deskTitle");
      if (title) title.textContent = `План работ №${openPlan.number}`;
      head.innerHTML = `<button type="button" class="desk-btn js-desk-back">← К очереди</button>
        <div>
          <h2>ПЛАН РАБОТ №${escapeHtml(openPlan.number)}</h2>
          <p class="desk-plan-card__meta">Мастер: ${escapeHtml(openPlan.master)} · Создан: ${escapeHtml(openPlan.created_at)} · Статус: ${escapeHtml(openPlan.status_label)}</p>
        </div>
        <div class="desk__plan-progress">${openPlan.done} / ${openPlan.total}</div>`;
      if (meta) meta.textContent = `${openPlan.done} выполнено · ${openPlan.excluded} исключено`;
      const items = openPlan.items || [];
      itemsBox.innerHTML = items
        .map((item) => {
          const active = item.id === selectedPlanItemId ? " is-active" : "";
          return `<article class="desk-item${active}" data-item-id="${escapeHtml(item.id)}" tabindex="0">
            <div class="desk-item__top">
              <div>
                <div class="desk-item__kind">${escapeHtml(item.type_label)}</div>
                <div class="desk-item__number">№ ${escapeHtml(item.number)}</div>
              </div>
              <span class="desk-item__status" data-code="${escapeHtml(item.result)}">${escapeHtml(item.result_label)}</span>
            </div>
            <p class="desk-item__address">${escapeHtml(item.address || "")}</p>
            <p class="desk-item__district">${item.pp ? `ПП ${escapeHtml(item.pp)}` : "ПП не указан"}</p>
          </article>`;
        })
        .join("");
      const selected = items.find((item) => item.id === selectedPlanItemId) || items[0];
      selectedPlanItemId = selected ? selected.id : "";
      renderPlanItem(selected);
    }

    function renderPlanItem(item) {
      const empty = document.getElementById("deskPlanPanelEmpty");
      const body = document.getElementById("deskPlanPanelBody");
      const head = document.getElementById("deskPlanPanelHead");
      if (!item) {
        empty.hidden = false;
        body.hidden = true;
        head.hidden = true;
        return;
      }
      empty.hidden = true;
      body.hidden = false;
      head.hidden = false;
      head.innerHTML = `<h2 class="desk__panel-title">№ ${escapeHtml(item.number)}</h2>
        <span class="desk-item__status" data-code="${escapeHtml(item.result)}">${escapeHtml(item.result_label)}</span>`;
      body.innerHTML = planItemCard(item);
      document.querySelectorAll("#deskPlanItems .desk-item").forEach((el) => el.classList.toggle("is-active", el.dataset.itemId === item.id));
    }

    function fetchPlan(planId) {
      fetch(withId(root.dataset.planUrl, planId), { headers: headers() })
        .then((res) => res.json())
        .then((plan) => {
          if (plan.message && !plan.id) {
            toast(plan.message, false);
            return;
          }
          openPlan = plan;
          selectedPlanItemId = "";
          showMode("plan");
          renderOpenPlan();
        })
        .catch(() => toast("Не удалось открыть план.", false));
    }

    function openLightbox(src) {
      const overlay = document.createElement("div");
      overlay.className = "desk-lightbox";
      overlay.innerHTML = `<img src="${escapeHtml(src)}" alt="">`;
      overlay.addEventListener("click", () => overlay.remove());
      document.body.appendChild(overlay);
    }

    function closeModals() {
      document.getElementById("deskCompleteModal").hidden = true;
      document.getElementById("deskExcludeModal").hidden = true;
      pendingAction = null;
    }

    function submitComplete() {
      if (!pendingAction || !openPlan) return;
      const comment = document.getElementById("deskCompleteComment").value.trim();
      const files = document.getElementById("deskCompleteFiles").files;
      const data = new FormData();
      data.append("comment", comment);
      Array.from(files || []).forEach((file) => data.append("files", file));
      fetch(withId(root.dataset.planCompleteUrl, openPlan.id, pendingAction.itemId), {
        method: "POST",
        headers: headers(),
        body: data,
      })
        .then((res) => res.json())
        .then((body) => {
          if (!body.ok) {
            toast(body.message || "Не удалось выполнить.", false);
            return;
          }
          openPlan = body.plan;
          toast(body.message, true);
          closeModals();
          renderOpenPlan();
        })
        .catch(() => toast("Не удалось выполнить работу.", false));
    }

    function submitExclude() {
      if (!pendingAction || !openPlan) return;
      fetch(withId(root.dataset.planExcludeUrl, openPlan.id, pendingAction.itemId), {
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
          openPlan = body.plan;
          toast(body.message, true);
          closeModals();
          renderOpenPlan();
        })
        .catch(() => toast("Не удалось исключить работу.", false));
    }

    function backToDesk() {
      draft = null;
      related = null;
      openPlan = null;
      showMode("desk");
      renderDraftTray();
      loadQueue();
    }

    searchForm?.addEventListener("submit", (event) => {
      event.preventDefault();
      page = 1;
      loadQueue();
    });

    root.querySelectorAll("[data-preset]").forEach((btn) => {
      btn.addEventListener("click", () => {
        preset = btn.dataset.preset || "all";
        root.querySelectorAll("[data-preset]").forEach((el) => el.classList.toggle("is-active", el === btn));
        page = 1;
        loadQueue();
      });
    });

    root.querySelectorAll("[data-journal]").forEach((btn) => {
      btn.addEventListener("click", () => {
        journal = btn.dataset.journal || "all";
        root.querySelectorAll("[data-journal]").forEach((el) => el.classList.toggle("is-active", el === btn));
        page = 1;
        loadQueue();
      });
    });

    document.getElementById("deskCreatePlan")?.addEventListener("click", startCompose);
    document.getElementById("deskMyPlans")?.addEventListener("click", loadPlans);

    root.addEventListener("click", (event) => {
      if (event.target.closest(".js-desk-back")) {
        backToDesk();
        return;
      }
      const saveBtn = event.target.closest("#deskSavePlan");
      if (saveBtn) {
        saveDraft();
        return;
      }
      const removeChip = event.target.closest(".js-draft-remove");
      if (removeChip) {
        removeDraftItem(removeChip.dataset.itemId);
        return;
      }
      const addBtn = event.target.closest(".js-desk-add");
      if (addBtn) {
        event.preventDefault();
        event.stopPropagation();
        addToPlan(addBtn.dataset.type, addBtn.dataset.id);
        return;
      }
      const completeBtn = event.target.closest(".js-desk-complete");
      if (completeBtn) {
        event.preventDefault();
        event.stopPropagation();
        completeQueue(completeBtn.dataset.id, completeBtn.dataset.type);
        return;
      }
      const openBtn = event.target.closest(".js-desk-open");
      const item = event.target.closest("#deskQueue .desk-item");
      const id = openBtn?.dataset.id || item?.dataset.id;
      const type = openBtn?.dataset.type || item?.dataset.type;
      if (id && (openBtn || item) && workspace.contains(event.target)) {
        loadCard(id, type);
        return;
      }
      const planCard = event.target.closest(".js-open-plan");
      if (planCard) {
        fetchPlan(planCard.dataset.id);
        return;
      }
      const planRow = event.target.closest("#deskPlanItems .desk-item");
      if (planRow?.dataset.itemId && openPlan) {
        selectedPlanItemId = planRow.dataset.itemId;
        renderPlanItem((openPlan.items || []).find((row) => row.id === selectedPlanItemId));
        return;
      }
      const planComplete = event.target.closest(".js-plan-complete");
      if (planComplete) {
        pendingAction = { type: "complete", itemId: planComplete.dataset.itemId };
        document.getElementById("deskCompleteComment").value = "";
        document.getElementById("deskCompleteFiles").value = "";
        document.getElementById("deskCompleteModal").hidden = false;
        return;
      }
      const planExclude = event.target.closest(".js-plan-exclude");
      if (planExclude) {
        pendingAction = { type: "exclude", itemId: planExclude.dataset.itemId };
        document.getElementById("deskExcludeReason").value = "";
        document.getElementById("deskExcludeComment").value = "";
        document.getElementById("deskExcludeModal").hidden = false;
      }
    });

    queueBox.addEventListener("keydown", (event) => {
      if (event.key !== "Enter") return;
      const item = event.target.closest(".desk-item");
      if (item?.dataset.id) loadCard(item.dataset.id, item.dataset.type);
    });

    pagerBox?.addEventListener("click", (event) => {
      const btn = event.target.closest("[data-page]");
      if (!btn) return;
      page = Number(btn.dataset.page || "1");
      loadQueue();
    });

    panelBody.addEventListener("click", (event) => {
      const photo = event.target.closest(".js-desk-photo");
      if (photo) {
        event.preventDefault();
        openLightbox(photo.dataset.src || photo.getAttribute("href"));
      }
    });
    document.getElementById("deskPlanPanelBody")?.addEventListener("click", (event) => {
      const photo = event.target.closest(".js-desk-photo");
      if (photo) {
        event.preventDefault();
        openLightbox(photo.dataset.src || photo.getAttribute("href"));
      }
    });

    document.getElementById("deskCompleteSubmit")?.addEventListener("click", submitComplete);
    document.getElementById("deskExcludeSubmit")?.addEventListener("click", submitExclude);
    document.querySelectorAll("[data-close-modal]").forEach((btn) => btn.addEventListener("click", closeModals));

    loadQueue();
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
