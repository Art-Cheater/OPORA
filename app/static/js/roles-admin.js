(() => {
  const root = document.getElementById("rolesAdmin");
  if (!root) return;

  const canManage = root.dataset.canManage === "true";
  const csrf = root.dataset.csrf || document.querySelector('meta[name="csrf-token"]')?.content || "";
  const list = document.getElementById("rolesList");
  const editorPanel = document.getElementById("roleEditorPanel");
  const editorTitle = document.getElementById("roleEditorTitle");
  const searchInput = document.getElementById("roleSearchInput");
  const EDITOR_LOADING =
    '<div class="opora-loading" role="status"><div class="spinner-border text-primary"></div><div class="opora-loading__text">Загрузка прав роли…</div></div>';
  let saveBusy = false;

  function api(url, options = {}) {
    const headers = { ...(options.headers || {}), "X-Requested-With": "XMLHttpRequest" };
    if (options.method === "POST" && csrf) headers["X-CSRFToken"] = csrf;
    return fetch(url, { ...options, headers });
  }

  function isOk(data) {
    return Boolean(data && (data.success === true || data.ok === true));
  }

  function toast(msg, type = "success") {
    if (window.OporaList?.showToast) window.OporaList.showToast(msg, type);
    else if (window.OporaToast) window.OporaToast.show(msg, type);
    else alert(msg);
  }

  function setSaveBusy(form, busy) {
    saveBusy = busy;
    if (busy) {
      window.OporaBusy?.begin(
        "Сохранение роли…",
        "Другие разделы сейчас недоступны: сервер занят этой операцией"
      );
    } else {
      window.OporaBusy?.end();
    }
    const btn = form?.querySelector("#roleSaveBtn");
    if (!btn) return;
    btn.disabled = busy;
    btn.innerHTML = busy
      ? '<span class="spinner-border spinner-border-sm me-1" role="status"></span> Сохранение…'
      : '<i class="bi bi-check-lg"></i> Сохранить';
  }

  function bindEditorEvents() {
    const form = document.getElementById("roleEditorForm");
    const moduleSelect = document.getElementById("fieldModuleSelect");
    if (moduleSelect) {
      moduleSelect.querySelectorAll("[data-field-module]").forEach((btn) => {
        btn.addEventListener("click", () => {
          const code = btn.dataset.fieldModule;
          moduleSelect.querySelectorAll("[data-field-module]").forEach((item) => {
            const on = item === btn;
            item.classList.toggle("btn-primary", on);
            item.classList.toggle("btn-outline-secondary", !on);
          });
          document.querySelectorAll(".field-module-panel").forEach((el) => {
            el.classList.toggle("d-none", el.dataset.module !== code);
          });
        });
      });
    }
    if (form && canManage) {
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        if (saveBusy) return;
        setSaveBusy(form, true);
        try {
          const res = await api(form.action, { method: "POST", body: new FormData(form) });
          const data = await res.json();
          if (isOk(data)) {
            toast(data.message || "Сохранено");
            const name = form.querySelector('[name="name"]')?.value?.trim();
            if (name && editorTitle) editorTitle.textContent = name;
            const roleId = data.id || list.querySelector(".roles-admin__item.active")?.dataset.roleId;
            if (roleId) {
              const item = list.querySelector(`.roles-admin__item[data-role-id="${roleId}"]`);
              const title = item?.querySelector(".fw-semibold");
              if (title && name) title.textContent = name;
            }
          } else {
            toast(data.message || "Ошибка сохранения", "danger");
          }
        } catch {
          toast("Не удалось сохранить роль. Повторите попытку.", "danger");
        } finally {
          setSaveBusy(form, false);
        }
      });
    }
  }

  async function loadEditor(roleId) {
    if (!editorPanel) return;
    editorPanel.innerHTML = EDITOR_LOADING;
    const url = roleId ? `/roles/editor/${roleId}` : "/roles/editor/new";
    try {
      const res = await api(url);
      const data = await res.json();
      if (!data.html) {
        editorPanel.innerHTML = '<div class="text-muted text-center py-5">Не удалось открыть роль</div>';
        return;
      }
      editorPanel.innerHTML = data.html;
      bindEditorEvents();
      list?.querySelectorAll(".roles-admin__item").forEach((el) => {
        el.classList.toggle("active", el.dataset.roleId === roleId);
      });
      const dup = document.getElementById("roleDuplicateBtn");
      const del = document.getElementById("roleDeleteBtn");
      if (dup) dup.dataset.roleId = roleId || "";
      if (del) del.dataset.roleId = roleId || "";
    } catch {
      editorPanel.innerHTML = '<div class="text-muted text-center py-5">Не удалось открыть роль</div>';
    }
  }

  list?.addEventListener("click", (e) => {
    const item = e.target.closest(".roles-admin__item");
    if (!item || saveBusy || window.OporaBusy?.isBusy()) return;
    e.preventDefault();
    loadEditor(item.dataset.roleId);
    const name = item.querySelector(".fw-semibold")?.textContent;
    if (name && editorTitle) editorTitle.textContent = name;
  });

  document.getElementById("roleCreateBtn")?.addEventListener("click", () => {
    if (saveBusy || window.OporaBusy?.isBusy()) return;
    if (editorTitle) editorTitle.textContent = "Новая роль";
    loadEditor(null);
  });

  document.getElementById("roleDuplicateBtn")?.addEventListener("click", async (e) => {
    const id = e.currentTarget.dataset.roleId;
    if (!id || saveBusy || window.OporaBusy?.isBusy()) return;
    if (!confirm("Создать копию этой роли?")) return;
    window.OporaBusy?.begin("Копирование роли…", "Дождитесь окончания — затем можно продолжить работу");
    try {
      const res = await api(`/roles/${id}/duplicate`, { method: "POST" });
      const data = await res.json();
      if (isOk(data)) {
        toast(data.message);
        window.location.href = `/roles?role_id=${data.id}`;
      } else toast(data.message, "danger");
    } finally {
      window.OporaBusy?.end();
    }
  });

  document.getElementById("roleDeleteBtn")?.addEventListener("click", async (e) => {
    const id = e.currentTarget.dataset.roleId;
    if (!id || saveBusy || window.OporaBusy?.isBusy()) return;
    if (!confirm("Удалить эту роль?")) return;
    const fd = new FormData();
    fd.append("csrf_token", csrf);
    const res = await api(`/roles/${id}/delete`, { method: "POST", body: fd });
    const data = await res.json();
    if (isOk(data)) {
      toast(data.message);
      window.location.href = "/roles";
    } else toast(data.message, "danger");
  });

  searchInput?.addEventListener("input", () => {
    const q = searchInput.value.trim().toLowerCase();
    list.querySelectorAll(".roles-admin__item").forEach((el) => {
      const text = el.textContent.toLowerCase();
      el.classList.toggle("d-none", q && !text.includes(q));
    });
  });

  const selectedId = list?.querySelector(".roles-admin__item.active")?.dataset.roleId;
  if (selectedId) loadEditor(selectedId);
  else if (canManage) loadEditor(null);
})();
