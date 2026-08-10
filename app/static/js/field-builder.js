/**
 * Конструктор полей — отдельные обработчики edit/hide/delete.
 * Не зависит от таблицы OporaList (на этой странице её нет).
 */
(function () {
  const AJAX_HEADERS = { "X-Requested-With": "XMLHttpRequest" };

  function csrfToken() {
    return document.querySelector('meta[name="csrf-token"]')?.content || "";
  }

  function toast(message, type) {
    if (window.OporaList && typeof window.OporaList.showToast === "function") {
      window.OporaList.showToast(message, type || "success");
      return;
    }
    window.alert(message);
  }

  function formModal() {
    return document.getElementById("oporaFormModal");
  }

  function formModalBody() {
    return document.getElementById("oporaFormModalBody");
  }

  function formModalTitle() {
    return document.getElementById("oporaFormModalLabel");
  }

  function confirmModal() {
    return document.getElementById("oporaConfirmModal");
  }

  function confirmModalBody() {
    return document.getElementById("oporaConfirmModalBody");
  }

  function confirmModalBtn() {
    return document.getElementById("oporaConfirmModalBtn");
  }

  async function fetchHtml(url) {
    const response = await fetch(url, { headers: AJAX_HEADERS, credentials: "same-origin" });
    if (!response.ok) {
      throw new Error("HTTP " + response.status);
    }
    return response.text();
  }

  function enhanceForm(form) {
    if (!form) return;
    const sel = form.querySelector("#fieldTypeSelect");
    const block = form.querySelector("#optionsBlock");
    if (sel && block) {
      const toggle = () => {
        block.style.display = sel.value === "select" ? "" : "none";
      };
      sel.addEventListener("change", toggle);
      toggle();
    }
  }

  function bindFormSubmit(form) {
    if (!form || form.dataset.oporaBound === "1") return;
    form.dataset.oporaBound = "1";
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const submitBtn = form.querySelector('[type="submit"]');
      if (submitBtn) submitBtn.disabled = true;
      try {
        const response = await fetch(form.action, {
          method: "POST",
          headers: AJAX_HEADERS,
          credentials: "same-origin",
          body: new FormData(form),
        });
        const data = await response.json();
        if (data.success) {
          bootstrap.Modal.getInstance(formModal())?.hide();
          toast(data.message || "Сохранено");
          window.location.reload();
          return;
        }
        if (data.html) {
          formModalBody().innerHTML = data.html;
          const next = formModalBody().querySelector("form");
          bindFormSubmit(next);
          enhanceForm(next);
        }
        toast(data.message || "Проверьте форму", "danger");
      } catch (err) {
        console.error(err);
        toast("Ошибка сохранения", "danger");
      } finally {
        if (submitBtn) submitBtn.disabled = false;
      }
    });
  }

  async function openForm(url, title) {
    const modal = formModal();
    if (!modal) {
      toast("Модальное окно не найдено на странице", "danger");
      return;
    }
    formModalTitle().textContent = title || "Форма";
    formModalBody().innerHTML =
      '<div class="text-center py-4"><div class="spinner-border text-primary"></div></div>';
    bootstrap.Modal.getOrCreateInstance(modal).show();
    try {
      const html = await fetchHtml(url);
      formModalBody().innerHTML = html;
      const form = formModalBody().querySelector("form");
      bindFormSubmit(form);
      enhanceForm(form);
    } catch (err) {
      console.error(err);
      formModalBody().innerHTML =
        '<div class="alert alert-danger">Не удалось загрузить форму. Обновите страницу.</div>';
    }
  }

  let pendingDeleteUrl = null;

  function openDeleteConfirm(url, message) {
    const modal = confirmModal();
    if (!modal) {
      if (window.confirm(message || "Подтвердите действие")) {
        executeDelete(url);
      }
      return;
    }
    pendingDeleteUrl = url;
    confirmModalBody().textContent =
      message || "Вы уверены, что хотите удалить это поле?";
    const btn = confirmModalBtn();
    if (btn) btn.textContent = message && message.indexOf("Скрыть") === 0 ? "Скрыть" : "Удалить";
    bootstrap.Modal.getOrCreateInstance(modal).show();
  }

  async function executeDelete(url) {
    const target = url || pendingDeleteUrl;
    pendingDeleteUrl = null;
    if (!target) return;
    bootstrap.Modal.getInstance(confirmModal())?.hide();
    try {
      const body = new FormData();
      body.append("csrf_token", csrfToken());
      const response = await fetch(target, {
        method: "POST",
        headers: AJAX_HEADERS,
        credentials: "same-origin",
        body,
      });
      const data = await response.json();
      if (data.success) {
        toast(data.message || "Готово");
        window.location.reload();
        return;
      }
      toast(data.message || "Ошибка", "danger");
    } catch (err) {
      console.error(err);
      toast("Ошибка запроса", "danger");
    }
  }

  function onClick(e) {
    const createBtn = e.target.closest("[data-opora-create]");
    if (createBtn) {
      e.preventDefault();
      e.stopPropagation();
      const url = createBtn.getAttribute("data-opora-create");
      if (url) openForm(url, "Новое поле");
      return;
    }

    const editBtn = e.target.closest("[data-opora-edit]");
    if (editBtn) {
      e.preventDefault();
      e.stopPropagation();
      const url = editBtn.getAttribute("data-opora-edit");
      if (url) openForm(url, "Редактирование поля");
      return;
    }

    const deleteBtn = e.target.closest("[data-opora-delete]");
    if (deleteBtn) {
      e.preventDefault();
      e.stopPropagation();
      openDeleteConfirm(
        deleteBtn.getAttribute("data-opora-delete"),
        deleteBtn.getAttribute("data-opora-delete-message")
      );
    }
  }

  function init() {
    if (!document.getElementById("oporaFieldBuilderPage")) return;
    document.addEventListener("click", onClick);
    confirmModalBtn()?.addEventListener("click", () => executeDelete());
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
