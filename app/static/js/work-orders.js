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
    const searchForm = document.getElementById("deskSearch");
    const canCompleteDesk = root.dataset.canComplete === "true";
    let preset = "all";
    let page = 1;
    let selectedId = "";
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

    function query() {
      const params = new URLSearchParams();
      params.set("preset", preset);
      params.set("page", String(page));
      const q = searchForm?.querySelector('[name="q"]')?.value?.trim();
      if (q) params.set("q", q);
      return params;
    }

    function statusTone(code) {
      return escapeHtml(code || "");
    }

    function renderQueue(data) {
      const items = data.items || [];
      if (metaBox) {
        metaBox.textContent = data.total ? `${data.total} заявок` : "";
      }
      if (!items.length) {
        queueBox.innerHTML = '<p class="desk__empty">По текущему фильтру заявок нет.</p>';
        if (pagerBox) pagerBox.hidden = true;
        return;
      }
      queueBox.innerHTML = items
        .map((item) => {
          const active = item.id === selectedId ? " is-active" : "";
          const complete = canCompleteDesk && item.can_complete
            ? `<button type="button" class="desk-btn desk-btn--done js-desk-complete" data-id="${escapeHtml(item.id)}">Выполнено</button>`
            : "";
          return `<article class="desk-item${active}" data-id="${escapeHtml(item.id)}" tabindex="0">
            <div class="desk-item__top">
              <div class="desk-item__number">№ ${escapeHtml(item.number)}</div>
              <span class="desk-item__status" data-code="${statusTone(item.status_code)}">${escapeHtml(item.status || "—")}</span>
            </div>
            <p class="desk-item__address">${escapeHtml(item.address || "Адрес не указан")}</p>
            <p class="desk-item__district">${escapeHtml(item.district || "Район не указан")}</p>
            <p class="desk-item__meta">Поступила: ${escapeHtml(item.received_at || "—")}<br>Диспетчер: ${escapeHtml(item.dispatcher_name || "—")}</p>
            <div class="desk-item__actions">
              <button type="button" class="desk-btn js-desk-open" data-id="${escapeHtml(item.id)}">Открыть</button>
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
        buttons.push(
          `<button type="button" class="desk__pager-btn${i === data.page ? " is-active" : ""}" data-page="${i}">${i}</button>`
        );
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

    function renderCard(card) {
      if (!card) {
        panelBody.hidden = true;
        panelEmpty.hidden = false;
        return;
      }
      panelEmpty.hidden = true;
      panelBody.hidden = false;
      const photos = (card.photos || [])
        .map(
          (photo) =>
            `<a href="${escapeHtml(photo.preview_url)}" class="js-desk-photo" data-src="${escapeHtml(photo.preview_url)}" title="${escapeHtml(photo.name)}">
              <img src="${escapeHtml(photo.preview_url)}" alt="${escapeHtml(photo.name)}" loading="lazy">
            </a>`
        )
        .join("");
      const docs = (card.documents || [])
        .map((doc) => `<a href="${escapeHtml(doc.download_url)}" target="_blank" rel="noopener">${escapeHtml(doc.name)}</a>`)
        .join("");
      const history = (card.history || [])
        .map(
          (row) => `<li>
            <strong>${escapeHtml(row.comment || row.status || row.action)}</strong>
            <span>${escapeHtml(row.created_at)}${row.user ? " · " + escapeHtml(row.user) : ""}</span>
          </li>`
        )
        .join("");
      const complete = canCompleteDesk && card.can_complete
        ? `<button type="button" class="desk-btn desk-btn--done js-desk-complete" data-id="${escapeHtml(card.id)}">Выполнено</button>`
        : "";
      panelBody.innerHTML = `
        <div class="desk-card__top">
          <h2 class="desk-card__number">Заявка №${escapeHtml(card.number)}</h2>
          <span class="desk-item__status" data-code="${statusTone(card.status_code)}">${escapeHtml(card.status || "—")}</span>
        </div>
        <p class="desk-flash" id="deskFlash"></p>
        ${field("Адрес", card.address)}
        ${field("Район", card.district)}
        ${field("Пункт питания", card.pp)}
        ${field("Описание", card.description || card.title)}
        <div class="desk-card__grid">
          ${field("Журнал", card.journal)}
          ${field("Приоритет", card.priority)}
          ${field("Заявитель", card.applicant_name)}
          ${field("Телефон", card.phone)}
          ${field("Поступила", card.received_at)}
          ${field("Диспетчер", card.dispatcher_name)}
        </div>
        <div class="desk-card__block">
          <p class="desk-card__label">Фото</p>
          ${photos ? `<div class="desk-photos">${photos}</div>` : '<p class="desk-card__value">Нет фотографий</p>'}
        </div>
        ${docs ? `<div class="desk-card__block"><p class="desk-card__label">Файлы</p><div class="desk-docs">${docs}</div></div>` : ""}
        <div class="desk-card__block">
          <p class="desk-card__label">История</p>
          ${history ? `<ul class="desk-history">${history}</ul>` : '<p class="desk-card__value">Записей пока нет</p>'}
        </div>
        <div class="desk-card__block">
          <p class="desk-card__label">Действия</p>
          <div class="desk-card__actions">${complete || '<span class="text-muted">Нет доступных действий</span>'}</div>
        </div>`;
    }

    function toast(message, ok) {
      const box = document.getElementById("deskFlash");
      if (!box || !message) return;
      box.style.color = ok ? "var(--status-done, #2E7D32)" : "#DC3545";
      box.textContent = message;
    }

    function loadQueue() {
      queueAbort?.abort();
      queueAbort = new AbortController();
      return fetch(`${root.dataset.queueUrl}?${query().toString()}`, {
        headers: headers(false),
        cache: "no-store",
        signal: queueAbort.signal,
      })
        .then((r) => r.json())
        .then((data) => {
          renderQueue(data);
          if (selectedId && !(data.items || []).some((item) => item.id === selectedId)) {
            selectedId = "";
            renderCard(null);
          }
        })
        .catch((err) => {
          if (err?.name === "AbortError") return;
          queueBox.innerHTML = '<p class="desk__empty">Не удалось загрузить список заявок.</p>';
        });
    }

    function loadCard(id) {
      if (!id) return;
      selectedId = id;
      queueBox.querySelectorAll(".desk-item").forEach((el) => {
        el.classList.toggle("is-active", el.dataset.id === id);
      });
      cardAbort?.abort();
      cardAbort = new AbortController();
      panelEmpty.hidden = true;
      panelBody.hidden = false;
      panelBody.innerHTML = '<p class="desk__empty">Загрузка карточки…</p>';
      return fetch(withId(root.dataset.cardUrl, id), {
        headers: headers(false),
        cache: "no-store",
        signal: cardAbort.signal,
      })
        .then((r) => r.json())
        .then((data) => {
          if (data.success === false) {
            panelBody.innerHTML = `<p class="desk__empty">${escapeHtml(data.message || "Заявка не найдена.")}</p>`;
            return;
          }
          renderCard(data);
        })
        .catch((err) => {
          if (err?.name === "AbortError") return;
          panelBody.innerHTML = '<p class="desk__empty">Не удалось открыть заявку.</p>';
        });
    }

    function complete(id) {
      if (!id || !canCompleteDesk) return;
      if (!window.confirm("Отметить заявку как выполненную?")) return;
      fetch(withId(root.dataset.completeUrl, id), {
        method: "POST",
        headers: headers(true),
        body: "{}",
      })
        .then((r) => r.json().then((body) => ({ ok: r.ok, body })))
        .then(({ ok, body }) => {
          if (!ok || !body.ok) {
            toast(body.message || "Не удалось отметить заявку.", false);
            return;
          }
          if (body.card) renderCard(body.card);
          loadQueue().then(() => toast(body.message || "Заявка выполнена.", true));
        })
        .catch(() => toast("Не удалось отметить заявку.", false));
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

    queueBox.addEventListener("click", (event) => {
      const completeBtn = event.target.closest(".js-desk-complete");
      if (completeBtn) {
        event.preventDefault();
        event.stopPropagation();
        complete(completeBtn.dataset.id);
        return;
      }
      const openBtn = event.target.closest(".js-desk-open");
      const item = event.target.closest(".desk-item");
      const id = openBtn?.dataset.id || item?.dataset.id;
      if (id) loadCard(id);
    });

    queueBox.addEventListener("keydown", (event) => {
      if (event.key !== "Enter") return;
      const item = event.target.closest(".desk-item");
      if (item?.dataset.id) loadCard(item.dataset.id);
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
      if (completeBtn) complete(completeBtn.dataset.id);
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
