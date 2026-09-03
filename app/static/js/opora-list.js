/**
 * Опора — единый модуль списков с AJAX-фильтрацией и CRUD-модалками.
 */
window.OporaList = (() => {
  const TABLE_LOADING_HTML =
    '<div class="opora-loading" role="status"><div class="spinner-border text-primary"></div><div class="opora-loading__text">Загрузка списка…</div></div>';
  const AJAX_HEADERS = { "X-Requested-With": "XMLHttpRequest" };

  let config = {};
  let currentPage = 1;
  let debounceTimer = null;
  let tableAbort = null;
  let tableInflight = new Map();
  let tableToken = 0;
  let pendingDeleteId = null;
  let pendingDeleteUrl = null;
  let pendingDeleteMessage = null;

  const formModal = () => document.getElementById("oporaFormModal");
  const formModalBody = () => document.getElementById("oporaFormModalBody");
  const formModalTitle = () => document.getElementById("oporaFormModalLabel");
  const detailModal = () => document.getElementById("oporaDetailModal");
  const detailModalBody = () => document.getElementById("oporaDetailModalBody");
  const detailModalTitle = () => document.getElementById("oporaDetailModalLabel");
  const detailModalBadge = () => document.getElementById("oporaDetailModalBadge");
  const detailEditBtn = () => document.getElementById("oporaDetailEditBtn");
  const detailOpenPageBtn = () => document.getElementById("oporaDetailOpenPageBtn");
  const confirmModal = () => document.getElementById("oporaConfirmModal");
  const confirmModalBody = () => document.getElementById("oporaConfirmModalBody");
  const confirmModalBtn = () => document.getElementById("oporaConfirmModalBtn");

  function showToast(message, type = "success") {
    const container = document.getElementById("oporaToastContainer");
    if (!container) return;
    const id = `toast-${Date.now()}`;
    const bg = type === "success" ? "text-bg-success" : type === "danger" ? "text-bg-danger" : "text-bg-warning";
    container.insertAdjacentHTML(
      "beforeend",
      `<div id="${id}" class="toast align-items-center ${bg} border-0" role="alert">
        <div class="d-flex"><div class="toast-body">${message}</div>
        <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button></div></div>`
    );
    const el = document.getElementById(id);
    bootstrap.Toast.getOrCreateInstance(el, { delay: 4000 }).show();
    el.addEventListener("hidden.bs.toast", () => el.remove());
  }

  async function parseJsonResponse(response, fallbackMessage) {
    const text = await response.text();
    let data = null;
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      data = null;
    }
    if (!data || typeof data !== "object") {
      const statusMessage =
        response.status === 400 || response.status === 403
          ? "Сессия формы устарела. Обновите страницу и повторите действие."
          : fallbackMessage;
      throw new Error(statusMessage);
    }
    if (!response.ok && data.success !== false) {
      throw new Error(data.message || fallbackMessage);
    }
    return data;
  }

  function listKindFromLocation() {
    try {
      const url = new URL(window.location.href);
      const path = (url.pathname || "").replace(/\/+$/, "");
      if (path === "/defects") return "defects";
      if (path === "/requests") {
        if ((url.searchParams.get("tab") || "").toLowerCase() === "defects") return "defects";
        return "requests";
      }
    } catch {
      /* ignore */
    }
    return "";
  }

  function queryParams() {
    const form = document.getElementById(config.filterFormId);
    const params = new URLSearchParams();
    if (form) {
      const data = new FormData(form);
      data.set("page", String(currentPage));
      for (const [k, v] of data.entries()) {
        if (v !== "") params.append(k, String(v));
      }
    } else {
      params.set("page", String(currentPage));
    }
    if (listKindFromLocation() === "defects") {
      params.delete("journal_id");
      if (!params.has("tab")) params.set("tab", "defects");
    }
    return params;
  }

  function fetchTable(url, signal) {
    return fetch(url, { headers: AJAX_HEADERS, cache: "no-store", signal }).then(async (response) => {
      const data = await parseJsonResponse(response, "Не удалось обновить список");
      if (!response.ok) throw new Error(data.message || "Не удалось обновить список");
      return data;
    });
  }

  function renderTableError(message) {
    const liveTable = document.getElementById(config.tableContainerId);
    if (!liveTable) return;
    const safe = String(message || "Не удалось обновить список")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
    liveTable.innerHTML = `<div class="alert alert-warning mb-0">${safe} <button type="button" class="btn btn-sm btn-outline-primary ms-2" data-opora-retry-list>Повторить</button></div>`;
    liveTable.querySelector("[data-opora-retry-list]")?.addEventListener("click", () => loadTable());
  }

  async function loadTable() {
    const defects = listKindFromLocation() === "defects" || config.listKind === "defects";
    const baseUrl = defects ? "/defects" : config.baseUrl;
    const tableContainerId =
      defects && document.getElementById("defectsTableContainer")
        ? "defectsTableContainer"
        : config.tableContainerId;
    const paginationContainerId =
      defects && document.getElementById("defectsPaginationContainer")
        ? "defectsPaginationContainer"
        : config.paginationContainerId;
    const tableContainer = document.getElementById(tableContainerId);
    const paginationContainer = document.getElementById(paginationContainerId);
    if (!tableContainer || !baseUrl) return;

    tableAbort?.abort();
    tableAbort = new AbortController();
    const token = ++tableToken;
    const url = `${baseUrl}/table?${queryParams().toString()}`;
    tableContainer.innerHTML = TABLE_LOADING_HTML;
    if (paginationContainer) paginationContainer.innerHTML = "";

    try {
      const data = await fetchTable(url, tableAbort.signal);
      if (token !== tableToken) return;
      const liveTable = document.getElementById(tableContainerId);
      const livePager = document.getElementById(paginationContainerId);
      if (!liveTable) return;
      liveTable.innerHTML = data.table_html;
      if (livePager) livePager.innerHTML = data.pagination_html;
      config.tableContainerId = tableContainerId;
      config.paginationContainerId = paginationContainerId;
      if (defects) {
        config.baseUrl = "/defects";
        config.pageLinkClass = "defect-page-link";
      }
      bindTableEvents();
      bindPagination();
      reloadListMap();
      syncListUrl();
    } catch (err) {
      if (err?.name === "AbortError" || token !== tableToken) return;
      renderTableError(err?.message || "Не удалось обновить список");
      showToast(err?.message || "Не удалось обновить список", "danger");
    }
  }

  function bindPagination() {
    const paginationContainer = document.getElementById(config.paginationContainerId);
    if (!paginationContainer) return;
    paginationContainer.querySelectorAll(`.${config.pageLinkClass}`).forEach((link) => {
      link.addEventListener("click", (e) => {
        e.preventDefault();
        const page = Number(link.dataset.page || "1");
        if (!Number.isNaN(page) && page > 0) {
          currentPage = page;
          loadTable();
        }
      });
    });
    paginationContainer.querySelector("[data-opora-per-page]")?.addEventListener("change", (event) => {
      const form = document.getElementById(config.filterFormId);
      if (form) ensureSortField(form, "per_page", event.target.value);
      currentPage = 1;
      loadTable();
    });
  }

  function listReturnUrl() {
    try {
      return window.location.pathname + window.location.search;
    } catch {
      return config.baseUrl || "/requests/";
    }
  }

  function syncListUrl() {
    if (config.syncUrl !== true) return;
    try {
      const path = window.location.pathname;
      if (!path.startsWith("/requests") && !path.startsWith("/defects")) return;
      const params = queryParams();
      const qs = params.toString();
      const next = qs ? `${path}?${qs}` : path;
      const current = `${path}${window.location.search || ""}`;
      if (next !== current) history.replaceState(history.state, "", next);
    } catch {
      /* ignore */
    }
  }

  function reloadListMap() {
    const mapNode = document.getElementById("opsMap");
    if (!mapNode || !window.OporaOpsMap) return;
    const params = queryParams();
    params.delete("page");
    params.delete("per_page");
    params.delete("sort_by");
    params.delete("sort_dir");
    const base = mapNode.getAttribute("data-map-base") || "/requests/map.json";
    const url = `${base}?${params.toString()}`;
    mapNode.setAttribute("data-src", url);
    if (!window.OporaOpsMap.init()) return;
    if (typeof window.OporaOpsMap.reload === "function") window.OporaOpsMap.reload(url);
  }

  function ensureSortField(form, name, value) {
    let el = form.querySelector(`[name="${name}"]`);
    if (!el) {
      el = document.createElement("input");
      el.type = "hidden";
      el.name = name;
      form.appendChild(el);
    }
    if (el.tagName === "SELECT") {
      const has = Array.from(el.options).some((o) => o.value === value);
      if (!has) el.appendChild(new Option(value, value, true, true));
    }
    el.value = value;
  }

  function applySort(field, defaultDir = "asc") {
    const form = document.getElementById(config.filterFormId);
    if (!form || !field) return;
    const currentBy = form.querySelector('[name="sort_by"]')?.value || "";
    const currentDir = form.querySelector('[name="sort_dir"]')?.value || "desc";
    const nextDir = currentBy === field ? (currentDir === "asc" ? "desc" : "asc") : defaultDir;
    ensureSortField(form, "sort_by", field);
    ensureSortField(form, "sort_dir", nextDir);
    currentPage = 1;
    loadTable();
  }

  function bindTableEvents() {
    const tableContainer = document.getElementById(config.tableContainerId);
    if (!tableContainer || tableContainer.dataset.oporaBound === "1") return;
    tableContainer.dataset.oporaBound = "1";

    tableContainer.addEventListener("click", (e) => {
      const sortBtn = e.target.closest("[data-opora-sort]");
      if (sortBtn) {
        e.preventDefault();
        e.stopPropagation();
        applySort(sortBtn.dataset.oporaSort, sortBtn.dataset.oporaSortDefault || "asc");
        return;
      }
      if (e.target.closest("[data-opora-action], [data-opora-repeat], .table-actions, .dropdown, .dropdown-menu")) return;
      const row = e.target.closest("tr[data-opora-id]");
      if (row) openView(row.dataset.oporaId);
    });
  }

  function openView(id) {
    if (!id) return;
    if (config.viewMode === "page") {
      const returnTo = encodeURIComponent(listReturnUrl());
      const href = `${config.baseUrl}/${id}?return_url=${returnTo}`;
      if (window.OporaNav?.go) {
        window.OporaNav.go(href);
        return;
      }
      window.location.href = href;
      return;
    }
    return openViewModal(id);
  }

  async function openViewModal(id) {
    const modal = detailModal();
    if (!modal) return;
    detailModalBody().innerHTML = '<div class="text-center py-4"><div class="spinner-border text-primary"></div></div>';
    detailModalTitle().textContent = "Загрузка...";
    detailModalBadge().innerHTML = "";
    detailEditBtn()?.classList.add("d-none");
    const openBtn = detailOpenPageBtn();
    if (openBtn) {
      openBtn.classList.add("d-none");
      openBtn.removeAttribute("href");
    }
    bootstrap.Modal.getOrCreateInstance(modal).show();

    try {
      const html = await fetchHtml(`${config.baseUrl}/${id}`);
      detailModalBody().innerHTML = html;

      const card = detailModalBody().querySelector("[data-opora-card-title]");
      const badge = detailModalBody().querySelector("[data-opora-card-badge]");
      if (card) detailModalTitle().textContent = card.textContent.trim();
      if (badge) detailModalBadge().innerHTML = badge.innerHTML;

      const pageLink = detailModalBody().querySelector("[data-opora-page-url]");
      const pageUrl = pageLink?.getAttribute("data-opora-page-url") || `${config.baseUrl}/${id}?full=1`;
      if (openBtn) {
        openBtn.href = pageUrl;
        openBtn.classList.remove("d-none");
      }

      if (config.canEdit) {
        detailEditBtn()?.classList.remove("d-none");
        detailEditBtn().onclick = () => {
          bootstrap.Modal.getInstance(detailModal())?.hide();
          openEdit(id);
        };
      }
      bindDetailForms(id);
      window.OporaProjectDocuments?.init?.(detailModalBody());
    } catch {
      detailModalBody().innerHTML = '<div class="alert alert-danger">Не удалось загрузить карточку</div>';
    }
  }

  function bindGlobalActions() {
    if (document.body.dataset.oporaGlobalBound === "1") return;
    document.body.dataset.oporaGlobalBound = "1";

    document.addEventListener("click", (e) => {
      const actionBtn = e.target.closest("[data-opora-action]");
      if (actionBtn && config.baseUrl) {
        e.preventDefault();
        e.stopPropagation();
        const action = actionBtn.dataset.oporaAction;
        const id = actionBtn.dataset.id;
        if (action === "view") openView(id);
        else if (action === "edit") openEdit(id);
        else if (action === "delete") openDeleteConfirm(id);
        else if (action === "complete") completeFromList(id);
        return;
      }

      const editUrlBtn = e.target.closest("[data-opora-edit]");
      if (editUrlBtn) {
        e.preventDefault();
        e.stopPropagation();
        openEditUrl(editUrlBtn.getAttribute("data-opora-edit"));
        return;
      }

      const deleteUrlBtn = e.target.closest("[data-opora-delete]");
      if (deleteUrlBtn) {
        e.preventDefault();
        e.stopPropagation();
        openDeleteConfirmUrl(
          deleteUrlBtn.getAttribute("data-opora-delete"),
          deleteUrlBtn.getAttribute("data-opora-delete-message")
        );
        return;
      }

      const repeatBtn = e.target.closest("[data-opora-repeat]");
      if (repeatBtn) {
        e.preventDefault();
        e.stopPropagation();
        markRepeatFromList(repeatBtn.dataset.id, repeatBtn.dataset.number || "");
        return;
      }

      if (!config.baseUrl) return;
      if (e.target.closest("[data-opora-create]")) {
        e.preventDefault();
        const createBtn = e.target.closest("[data-opora-create]");
        const createUrl = createBtn?.getAttribute("data-opora-create");
        if (createUrl) openCreateUrl(createUrl);
        else openCreate();
      }
    });

    confirmModalBtn()?.addEventListener("click", executeDelete);
  }

  async function fetchHtml(url) {
    const response = await fetch(url, { headers: AJAX_HEADERS });
    const text = await response.text();
    if (!response.ok) {
      try {
        const data = JSON.parse(text);
        throw new Error(data.message || "Не удалось загрузить данные");
      } catch (err) {
        if (err instanceof SyntaxError) throw new Error("Не удалось загрузить данные");
        throw err;
      }
    }
    return text;
  }

  function enhanceForm(form) {
    if (!form) return;
    if (window.OporaPhoneMask) OporaPhoneMask.init(form);
    if (window.OporaRequestsForm) OporaRequestsForm.init(form);
    initChoiceSearch(form);
    const firstInvalid = form.querySelector(".is-invalid");
    if (firstInvalid) firstInvalid.focus();
  }

  function initChoiceSearch(root) {
    if (!root) return;
    root.querySelectorAll("select[data-choice-url]").forEach((select) => {
      if (select.dataset.choiceBound === "1") return;
      select.dataset.choiceBound = "1";
      const input = document.createElement("input");
      input.type = "search";
      input.className = "form-control form-control-sm mb-1";
      input.placeholder = select.dataset.choicePlaceholder || "Поиск…";
      input.autocomplete = "off";
      select.parentNode.insertBefore(input, select);
      let timer = null;
      input.addEventListener("input", () => {
        clearTimeout(timer);
        timer = setTimeout(() => fetchChoices(select, input.value), 250);
      });
    });
  }

  async function fetchChoices(select, query) {
    const url = new URL(select.dataset.choiceUrl, window.location.origin);
    url.searchParams.set("q", query || "");
    [...select.options].forEach((option) => {
      if (option.selected && option.value) url.searchParams.append("id", option.value);
    });
    try {
      const response = await fetch(url.toString(), {
        headers: { "X-Requested-With": "XMLHttpRequest" },
      });
      if (!response.ok) return;
      const data = await response.json();
      const selected = new Set(
        [...select.selectedOptions].map((option) => option.value).filter(Boolean)
      );
      const empty = select.querySelector('option[value=""]');
      select.innerHTML = "";
      if (empty && !select.multiple) {
        select.appendChild(empty);
      } else if (!select.multiple) {
        const blank = document.createElement("option");
        blank.value = "";
        blank.textContent = "Не выбран";
        select.appendChild(blank);
      }
      (data.items || []).forEach((item) => {
        const option = document.createElement("option");
        option.value = item.id;
        option.textContent = item.label;
        if (selected.has(item.id)) option.selected = true;
        select.appendChild(option);
      });
    } catch {
      /* поиск справочника не должен ломать форму */
    }
  }

  function bindFormSubmit(form) {
    if (!form) return;
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const submitBtn = form.querySelector('[type="submit"]');
      const originalHtml = submitBtn?.innerHTML;
      const modal = formModal();
      let saving = true;
      const blockHide = (ev) => {
        if (saving) ev.preventDefault();
      };
      modal?.addEventListener("hide.bs.modal", blockHide);

      const setBusy = (busy) => {
        form.setAttribute("aria-busy", busy ? "true" : "false");
        if (!submitBtn) return;
        submitBtn.disabled = busy;
        if (originalHtml) submitBtn.innerHTML = busy ? "Сохранение…" : originalHtml;
      };
      setBusy(true);

      const doSubmit = async () => {
        const response = await fetch(form.action, {
          method: form.method || "POST",
          headers: AJAX_HEADERS,
          body: new FormData(form),
        });
        const data = await parseJsonResponse(response, "Ошибка сохранения");
        if (data.success) {
          saving = false;
          modal?.removeEventListener("hide.bs.modal", blockHide);
          bootstrap.Modal.getInstance(modal)?.hide();
          showToast(data.message || "Сохранено");
          if (data.redirect_url) {
            if (window.OporaNav?.go) {
              window.OporaNav.go(data.redirect_url);
              return;
            }
            window.location.href = data.redirect_url;
            return;
          }
          await refreshAfterMutation();
        } else {
          if (data.html) {
            formModalBody().innerHTML = data.html;
            const newForm = formModalBody().querySelector("form");
            bindFormSubmit(newForm);
            enhanceForm(newForm);
          }
          showToast(data.message || "Проверьте форму", "danger");
        }
      };

      try {
        if (!validateRequestFormBeforeSave(form)) {
          return;
        }
        if (window.OporaRequestsForm?.handleCreateSubmit) {
          await OporaRequestsForm.handleCreateSubmit(form, doSubmit);
        } else {
          await doSubmit();
        }
      } catch (err) {
        showToast(err?.message || "Ошибка сохранения", "danger");
      } finally {
        saving = false;
        modal?.removeEventListener("hide.bs.modal", blockHide);
        setBusy(false);
      }
    });
  }

  function bindDetailForms(id) {
    detailModalBody()?.querySelectorAll("form[data-opora-detail-form]").forEach((form) => {
      if (form.dataset.oporaBound === "1") return;
      form.dataset.oporaBound = "1";
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const submitBtn = form.querySelector('[type="submit"]');
        if (submitBtn) submitBtn.disabled = true;
        try {
          const response = await fetch(form.action, {
            method: form.method || "POST",
            headers: AJAX_HEADERS,
            body: new FormData(form),
          });
          const data = await parseJsonResponse(response, "Не удалось добавить комментарий");
          if (!data.success) throw new Error(data.message || "Проверьте комментарий");
          showToast(data.message || "Комментарий добавлен");
          await openViewModal(id);
        } catch (err) {
          showToast(err?.message || "Не удалось добавить комментарий", "danger");
        } finally {
          if (submitBtn) submitBtn.disabled = false;
        }
      });
    });
  }

  async function refreshAfterMutation() {
    if (config.tableContainerId && document.getElementById(config.tableContainerId)) {
      await loadTable();
    } else {
      window.location.reload();
    }
  }

  async function openCreate() {
    const modal = formModal();
    if (!modal) return;
    formModalTitle().textContent = config.createTitle || "Создание";
    formModalBody().innerHTML = '<div class="text-center py-4"><div class="spinner-border text-primary"></div></div>';
    bootstrap.Modal.getOrCreateInstance(modal).show();
    try {
      const html = await fetchHtml(`${config.baseUrl}/new`);
      formModalBody().innerHTML = html;
      const form = formModalBody().querySelector("form");
      if (form) {
        bindFormSubmit(form);
        enhanceForm(form);
      }
    } catch {
      formModalBody().innerHTML = '<div class="alert alert-danger">Не удалось загрузить форму</div>';
    }
  }

  async function openCreateUrl(url) {
    const modal = formModal();
    if (!modal || !url) return;
    formModalTitle().textContent = config.createTitle || "Создание";
    formModalBody().innerHTML = '<div class="text-center py-4"><div class="spinner-border text-primary"></div></div>';
    bootstrap.Modal.getOrCreateInstance(modal).show();
    try {
      const html = await fetchHtml(url);
      formModalBody().innerHTML = html;
      const form = formModalBody().querySelector("form");
      if (form) {
        bindFormSubmit(form);
        enhanceForm(form);
      }
    } catch {
      formModalBody().innerHTML = '<div class="alert alert-danger">Не удалось загрузить форму</div>';
    }
  }

  async function openEdit(id) {
    const modal = formModal();
    if (!modal) return;
    formModalTitle().textContent = config.editTitle || "Редактирование";
    formModalBody().innerHTML = '<div class="text-center py-4"><div class="spinner-border text-primary"></div></div>';
    bootstrap.Modal.getOrCreateInstance(modal).show();
    try {
      const html = await fetchHtml(`${config.baseUrl}/${id}/edit`);
      formModalBody().innerHTML = html;
      const form = formModalBody().querySelector("form");
      if (form) {
        bindFormSubmit(form);
        enhanceForm(form);
      }
    } catch {
      formModalBody().innerHTML = '<div class="alert alert-danger">Не удалось загрузить форму</div>';
    }
  }

  async function openEditUrl(url) {
    const modal = formModal();
    if (!modal || !url) return;
    formModalTitle().textContent = config.editTitle || "Редактирование";
    formModalBody().innerHTML = '<div class="text-center py-4"><div class="spinner-border text-primary"></div></div>';
    bootstrap.Modal.getOrCreateInstance(modal).show();
    try {
      const html = await fetchHtml(url);
      formModalBody().innerHTML = html;
      const form = formModalBody().querySelector("form");
      if (form) {
        bindFormSubmit(form);
        enhanceForm(form);
      }
    } catch {
      formModalBody().innerHTML = '<div class="alert alert-danger">Не удалось загрузить форму</div>';
    }
  }

  function openDeleteConfirm(id) {
    pendingDeleteId = id;
    pendingDeleteUrl = null;
    pendingDeleteMessage = null;
    confirmModalBody().textContent =
      config.deleteMessage || "Вы уверены, что хотите удалить эту запись? Это действие нельзя отменить.";
    bootstrap.Modal.getOrCreateInstance(confirmModal()).show();
  }

  function openDeleteConfirmUrl(url, message) {
    pendingDeleteId = null;
    pendingDeleteUrl = url;
    pendingDeleteMessage = message;
    confirmModalBody().textContent =
      message ||
      config.deleteMessage ||
      "Вы уверены, что хотите удалить эту запись? Это действие нельзя отменить.";
    bootstrap.Modal.getOrCreateInstance(confirmModal()).show();
  }

  function defaultLocalDateTime() {
    const now = new Date();
    const pad = (n) => String(n).padStart(2, "0");
    return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}T${pad(now.getHours())}:${pad(now.getMinutes())}`;
  }

  function parseRepeatInput(raw) {
    const text = String(raw || "").trim().replace(" ", "T");
    const match = text.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
    if (!match) return null;
    const [, y, m, d, hh, mm] = match;
    return `${y}-${m}-${d}T${hh}:${mm}`;
  }

  function ensureRepeatModal() {
    let modal = document.getElementById("oporaRepeatModal");
    if (modal) return modal;
    document.body.insertAdjacentHTML(
      "beforeend",
      `<div class="modal fade" id="oporaRepeatModal" tabindex="-1" aria-hidden="true">
        <div class="modal-dialog">
          <div class="modal-content">
            <div class="modal-header">
              <h5 class="modal-title" id="oporaRepeatModalTitle">Повторное обращение</h5>
              <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Закрыть"></button>
            </div>
            <div class="modal-body">
              <div class="mb-3">
                <label class="form-label" for="oporaRepeatAt">Дата и время <span class="text-danger">*</span></label>
                <input type="datetime-local" class="form-control" id="oporaRepeatAt" required>
              </div>
              <div class="mb-0">
                <label class="form-label" for="oporaRepeatDescription">Новое описание (необязательно)</label>
                <textarea class="form-control" id="oporaRepeatDescription" rows="4"
                  placeholder="Можно оставить пустым"></textarea>
              </div>
            </div>
            <div class="modal-footer">
              <button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal">Отмена</button>
              <button type="button" class="btn btn-primary" id="oporaRepeatSaveBtn">Сохранить</button>
            </div>
          </div>
        </div>
      </div>`
    );
    return document.getElementById("oporaRepeatModal");
  }

  function askRepeatDetails(number) {
    return new Promise((resolve) => {
      const modalEl = ensureRepeatModal();
      const title = document.getElementById("oporaRepeatModalTitle");
      const atInput = document.getElementById("oporaRepeatAt");
      const descInput = document.getElementById("oporaRepeatDescription");
      const saveBtn = document.getElementById("oporaRepeatSaveBtn");
      if (title) title.textContent = number ? `Повторное обращение — ${number}` : "Повторное обращение";
      if (atInput) atInput.value = defaultLocalDateTime();
      if (descInput) descInput.value = "";

      const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
      let settled = false;

      const cleanup = () => {
        saveBtn?.removeEventListener("click", onSave);
        modalEl.removeEventListener("hidden.bs.modal", onHide);
      };

      const onHide = () => {
        if (settled) return;
        settled = true;
        cleanup();
        resolve(null);
      };

      const onSave = () => {
        const receivedAt = parseRepeatInput(atInput?.value || "");
        if (!receivedAt) {
          showToast("Укажите дату и время повторного обращения", "danger");
          atInput?.focus();
          return;
        }
        settled = true;
        cleanup();
        modal.hide();
        resolve({
          receivedAt,
          description: (descInput?.value || "").trim(),
        });
      };

      saveBtn?.addEventListener("click", onSave);
      modalEl.addEventListener("hidden.bs.modal", onHide);
      modal.show();
      window.setTimeout(() => atInput?.focus(), 200);
    });
  }

  async function markRepeatFromList(id, number) {
    if (!id) return;
    const details = await askRepeatDetails(number || "");
    if (!details) return;
    try {
      const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
      const body = new FormData();
      if (csrf) body.append("csrf_token", csrf);
      body.append("received_at", details.receivedAt);
      if (details.description) body.append("description", details.description);
      const response = await fetch(`/requests/${id}/mark-repeat`, {
        method: "POST",
        headers: {
          ...AJAX_HEADERS,
          ...(csrf ? { "X-CSRFToken": csrf } : {}),
        },
        body,
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.success) {
        throw new Error(data.message || "Не удалось зафиксировать повтор");
      }
      showToast(data.message || "Повторное обращение зафиксировано.");
      await refreshAfterMutation();
    } catch (err) {
      showToast(err.message || "Ошибка", "danger");
    }
  }

  function validateRequestFormBeforeSave(form) {
    if (!form?.matches?.("[data-requests-form]")) return true;
    const received = form.querySelector('[name="received_at"]');
    if (received && !String(received.value || "").trim()) {
      showToast("Укажите дату и время получения заявки", "danger");
      received.classList.add("is-invalid");
      received.focus();
      return false;
    }
    const phone = form.querySelector('[name="phone"]');
    if (phone && !String(phone.value || "").trim()) {
      const ok = window.confirm(
        "Телефон заявителя не заполнен.\n\nСохранить заявку без телефона?"
      );
      if (!ok) {
        phone.focus();
        return false;
      }
    }
    return true;
  }

  async function executeDelete() {
    const id = pendingDeleteId;
    const url = pendingDeleteUrl;
    pendingDeleteId = null;
    pendingDeleteUrl = null;
    pendingDeleteMessage = null;
    if (!id && !url) return;
    bootstrap.Modal.getInstance(confirmModal())?.hide();

    try {
      const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
      const body = new FormData();
      body.append("csrf_token", csrf);
      const response = await fetch(url || `${config.baseUrl}/${id}/delete`, {
        method: "POST",
        headers: AJAX_HEADERS,
        body,
      });
      const data = await parseJsonResponse(response, "Ошибка удаления");
      if (data.success) {
        showToast(data.message || "Удалено");
        await refreshAfterMutation();
      } else {
        showToast(data.message || "Ошибка удаления", "danger");
      }
    } catch {
      showToast("Ошибка удаления", "danger");
    }
  }

  async function completeFromList(id) {
    if (!id) return;
    if (!window.confirm("Отметить заявку выполненной?")) return;
    const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
    try {
      const response = await fetch(`${config.baseUrl}/${id}/complete`, {
        method: "POST",
        headers: {
          "X-Requested-With": "XMLHttpRequest",
          Accept: "application/json",
          ...(csrf ? { "X-CSRFToken": csrf } : {}),
        },
        body: csrf ? new URLSearchParams({ csrf_token: csrf }) : undefined,
      });
      const data = await parseJsonResponse(response, "Не удалось отметить заявку выполненной");
      if (!response.ok || data.ok === false) {
        throw new Error(data.message || "Не удалось отметить заявку выполненной");
      }
      showToast(data.message || "Заявка завершена.");
      loadTable();
    } catch (err) {
      showToast(err?.message || "Не удалось отметить заявку выполненной", "danger");
    }
  }

  function initFilter() {
    const form = document.getElementById(config.filterFormId);
    const resetBtn = document.getElementById(config.resetBtnId);
    if (!form) return;
    if (form.dataset.oporaFilterBound === "1") return;
    form.dataset.oporaFilterBound = "1";

    form.addEventListener("submit", (e) => {
      e.preventDefault();
      currentPage = 1;
      loadTable();
    });

    resetBtn?.addEventListener("click", () => {
      form.reset();
      currentPage = 1;
      loadTable();
    });
  }

  function bindFilters() {
    initFilter();
    initChoiceSearch(document);
  }

  function reset() {
    tableToken += 1;
    tableAbort?.abort();
    tableAbort = null;
    tableInflight.clear();
    config = {};
    currentPage = 1;
    clearTimeout(debounceTimer);
  }

  function init(options) {
    config = options;
    const pageFromUrl = Number(new URLSearchParams(window.location.search).get("page") || "1");
    currentPage = pageFromUrl > 0 ? pageFromUrl : 1;
    initFilter();
    bindTableEvents();
    bindPagination();
    if (!window.__oporaListGlobalBound) {
      bindGlobalActions();
      window.__oporaListGlobalBound = true;
    }
    if (config.loadOnStart) {
      loadTable();
    }
  }

  function bootPage() {
    initFromConfigElement();
    initChoiceSearch(document);
  }

  function initFromConfigElement() {
    const cfg = document.getElementById("oporaListConfig");
    if (!cfg) {
      reset();
      return;
    }
    const fromUrl = listKindFromLocation();
    const defects = fromUrl === "defects" || (!fromUrl && cfg.dataset.listKind === "defects");
    init({
      listKind: defects ? "defects" : cfg.dataset.listKind || "",
      baseUrl: defects ? "/defects" : cfg.dataset.baseUrl,
      filterFormId:
        defects && document.getElementById("defectFilterForm")
          ? "defectFilterForm"
          : cfg.dataset.filterFormId,
      tableContainerId:
        defects && document.getElementById("defectsTableContainer")
          ? "defectsTableContainer"
          : cfg.dataset.tableContainerId,
      paginationContainerId:
        defects && document.getElementById("defectsPaginationContainer")
          ? "defectsPaginationContainer"
          : cfg.dataset.paginationContainerId,
      resetBtnId:
        defects && document.getElementById("defectFilterReset")
          ? "defectFilterReset"
          : cfg.dataset.resetBtnId,
      pageLinkClass: defects ? "defect-page-link" : cfg.dataset.pageLinkClass,
      createTitle: cfg.dataset.createTitle,
      editTitle: cfg.dataset.editTitle,
      deleteMessage: cfg.dataset.deleteMessage,
      canEdit: cfg.dataset.canEdit === "true",
      viewMode: cfg.dataset.viewMode || "modal",
      loadOnStart: cfg.dataset.loadOnStart === "true",
      syncUrl: cfg.dataset.syncUrl === "true",
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootPage);
  } else {
    bootPage();
  }

  return { init, reset, bootPage, bindFilters, loadTable, showToast, openView, openEdit, openCreate, initFromConfigElement };
})();
