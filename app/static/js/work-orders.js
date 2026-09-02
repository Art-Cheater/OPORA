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
    const flashBox = document.getElementById("deskFlash");
    const canCompleteDesk = root.dataset.canComplete === "true";
    const canCompleteDefect = root.dataset.canCompleteDefect === "true";
    let preset = "all";
    let journal = "all";
    let page = 1;
    let selectedId = "";
    let selectedType = "request";
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

    function withId(template, id) {
      return String(template || "").replace("00000000-0000-0000-0000-000000000000", id);
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
          const kind = item.entity_type || item.type || "request";
          const canDone = kind === "defect" ? canCompleteDefect : canCompleteDesk;
          const complete =
            canDone && item.can_complete
              ? `<button type="button" class="desk-btn desk-btn--done js-desk-complete" data-id="${escapeHtml(item.id)}" data-type="${escapeHtml(kind)}">Выполнено</button>`
              : "";
          const active = item.id === selectedId ? " is-active" : "";
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
              ${complete}
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
      return `<div class="desk-card__block"><p class="desk-card__label">${escapeHtml(label)}</p><p class="desk-card__value">${escapeHtml(text)}</p></div>`;
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
        canDone && card.can_complete
          ? `<div class="desk-card__actions"><button type="button" class="desk-btn desk-btn--done js-desk-complete" data-id="${escapeHtml(card.id)}" data-type="${escapeHtml(kind)}">Выполнено</button></div>`
          : "";
      const photos = (card.photos || [])
        .map(
          (file) =>
            `<a class="js-desk-photo" href="${escapeHtml(file.preview_url || file.download_url)}" data-src="${escapeHtml(file.preview_url || file.download_url)}"><img src="${escapeHtml(file.preview_url || file.download_url)}" alt=""></a>`
        )
        .join("");
      const history = (card.history || [])
        .map(
          (entry) =>
            `<li><strong>${escapeHtml(entry.comment || entry.action || "Событие")}</strong><span>${escapeHtml(entry.user || "")} · ${escapeHtml(entry.created_at || "")}</span></li>`
        )
        .join("");
      panelHead.innerHTML = `<h2 class="desk__panel-title">№ ${escapeHtml(card.number)}</h2>
        <span class="desk-item__status" data-code="${escapeHtml(card.status_code || "")}">${escapeHtml(card.status || "—")}</span>`;
      panelBody.innerHTML = `${field("Тип", card.type_label)}
        ${field("Адрес", card.address)}
        ${field("ПП", card.pp ? `ПП ${card.pp}` : "")}
        ${field("Район", card.district)}
        ${field("Описание", card.description)}
        ${photos ? `<div class="desk-card__block"><p class="desk-card__label">Фотографии</p><div class="desk-photos">${photos}</div></div>` : ""}
        ${history ? `<div class="desk-card__block"><p class="desk-card__label">История</p><ul class="desk-history">${history}</ul></div>` : ""}
        ${complete}`;
    }

    function loadQueue() {
      if (queueAbort) queueAbort.abort();
      queueAbort = new AbortController();
      fetch(`${root.dataset.queueUrl}?${query()}`, { headers: headers(), signal: queueAbort.signal })
        .then((res) => res.json())
        .then(renderQueue)
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
          root.querySelectorAll("#deskQueue .desk-item").forEach((el) => el.classList.toggle("is-active", el.dataset.id === id));
        })
        .catch((err) => {
          if (err.name !== "AbortError") toast("Не удалось открыть карточку.", false);
        });
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

    function openLightbox(src) {
      const overlay = document.createElement("div");
      overlay.className = "desk-lightbox";
      overlay.innerHTML = `<img src="${escapeHtml(src)}" alt="">`;
      overlay.addEventListener("click", () => overlay.remove());
      document.body.appendChild(overlay);
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
    queueBox.addEventListener("click", (event) => {
      const completeBtn = event.target.closest(".js-desk-complete");
      if (completeBtn) {
        event.preventDefault();
        event.stopPropagation();
        completeQueue(completeBtn.dataset.id, completeBtn.dataset.type);
        return;
      }
      const openBtn = event.target.closest(".js-desk-open");
      const item = event.target.closest(".desk-item");
      const id = openBtn?.dataset.id || item?.dataset.id;
      const type = openBtn?.dataset.type || item?.dataset.type;
      if (id) loadCard(id, type);
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
        return;
      }
      const completeBtn = event.target.closest(".js-desk-complete");
      if (completeBtn) completeQueue(completeBtn.dataset.id, completeBtn.dataset.type);
    });
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
