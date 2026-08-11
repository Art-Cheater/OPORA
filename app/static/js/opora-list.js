/**
 * Опора — единый модуль списков с AJAX-фильтрацией и CRUD-модалками.
 */
window.OporaList = (() => {
  const AJAX_HEADERS = { "X-Requested-With": "XMLHttpRequest" };

  let config = {};
  let currentPage = 1;
  let debounceTimer = null;
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

  function queryParams() {
    const form = document.getElementById(config.filterFormId);
    if (!form) return new URLSearchParams();
    const data = new FormData(form);
    data.set("page", String(currentPage));
    const params = new URLSearchParams();
    for (const [k, v] of data.entries()) {
      if (v !== "") params.append(k, String(v));
    }
    return params;
  }

  async function loadTable() {
    const tableContainer = document.getElementById(config.tableContainerId);
    const paginationContainer = document.getElementById(config.paginationContainerId);
    if (!tableContainer) return;

    const url = `${config.baseUrl}/table?${queryParams().toString()}`;
    const response = await fetch(url, { headers: AJAX_HEADERS });
    if (!response.ok) return;
    const data = await response.json();
    tableContainer.innerHTML = data.table_html;
    if (paginationContainer) {
      paginationContainer.innerHTML = data.pagination_html;
    }
    bindTableEvents();
    bindPagination();
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
  }

  function bindTableEvents() {
    const tableContainer = document.getElementById(config.tableContainerId);
    if (!tableContainer || tableContainer.dataset.oporaBound === "1") return;
    tableContainer.dataset.oporaBound = "1";

    tableContainer.addEventListener("click", (e) => {
      if (e.target.closest("[data-opora-action]")) return;
      const row = e.target.closest("tr[data-opora-id]");
      if (row) openView(row.dataset.oporaId);
    });
  }

  function openView(id) {
    if (!id) return;
    if (config.viewMode === "page") {
      window.location.href = `${config.baseUrl}/${id}`;
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
    if (!response.ok) throw new Error("Не удалось загрузить данные");
    return response.text();
  }

  function enhanceForm(form) {
    if (!form) return;
    if (window.OporaPhoneMask) OporaPhoneMask.init(form);
    if (window.OporaRequestsForm) OporaRequestsForm.init(form);
    const firstInvalid = form.querySelector(".is-invalid");
    if (firstInvalid) firstInvalid.focus();
  }

  function bindFormSubmit(form) {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const submitBtn = form.querySelector('[type="submit"]');
      if (submitBtn) submitBtn.disabled = true;

      const doSubmit = async () => {
        const response = await fetch(form.action, {
          method: form.method || "POST",
          headers: AJAX_HEADERS,
          body: new FormData(form),
        });
        const data = await response.json();
        if (data.success) {
          bootstrap.Modal.getInstance(formModal())?.hide();
          showToast(data.message || "Сохранено");
          if (data.redirect_url) {
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
        if (window.OporaRequestsForm?.handleCreateSubmit) {
          await OporaRequestsForm.handleCreateSubmit(form, doSubmit);
        } else {
          await doSubmit();
        }
      } catch (err) {
        showToast(err?.message || "Ошибка сохранения", "danger");
      } finally {
        if (submitBtn) submitBtn.disabled = false;
      }
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
      const data = await response.json();
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

  function initFilter() {
    const form = document.getElementById(config.filterFormId);
    const resetBtn = document.getElementById(config.resetBtnId);
    if (!form) return;

    function debouncedReload() {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        currentPage = 1;
        loadTable();
      }, 250);
    }

    form.querySelectorAll("input, select").forEach((el) => {
      el.addEventListener("input", debouncedReload);
      el.addEventListener("change", debouncedReload);
    });

    resetBtn?.addEventListener("click", () => {
      form.reset();
      currentPage = 1;
      loadTable();
    });
  }

  function init(options) {
    config = options;
    initFilter();
    bindTableEvents();
    bindPagination();
    bindGlobalActions();
  }

  function initFromConfigElement() {
    const cfg = document.getElementById("oporaListConfig");
    if (!cfg) return;
    init({
      baseUrl: cfg.dataset.baseUrl,
      filterFormId: cfg.dataset.filterFormId,
      tableContainerId: cfg.dataset.tableContainerId,
      paginationContainerId: cfg.dataset.paginationContainerId,
      resetBtnId: cfg.dataset.resetBtnId,
      pageLinkClass: cfg.dataset.pageLinkClass,
      createTitle: cfg.dataset.createTitle,
      editTitle: cfg.dataset.editTitle,
      deleteMessage: cfg.dataset.deleteMessage,
      canEdit: cfg.dataset.canEdit === "true",
      viewMode: cfg.dataset.viewMode || "modal",
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initFromConfigElement);
  } else {
    initFromConfigElement();
  }

  return { init, loadTable, showToast, openView, openEdit, openCreate, initFromConfigElement };
})();
