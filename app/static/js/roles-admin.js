(() => {
  const root = document.getElementById("rolesAdmin");
  if (!root) return;

  const canManage = root.dataset.canManage === "true";
  const csrf = root.dataset.csrf || document.querySelector('meta[name="csrf-token"]')?.content || "";
  const list = document.getElementById("rolesList");
  const editorPanel = document.getElementById("roleEditorPanel");
  const editorTitle = document.getElementById("roleEditorTitle");
  const searchInput = document.getElementById("roleSearchInput");

  function api(url, options = {}) {
    const headers = { ...(options.headers || {}), "X-Requested-With": "XMLHttpRequest" };
    if (options.method === "POST" && csrf) headers["X-CSRFToken"] = csrf;
    return fetch(url, { ...options, headers });
  }

  function toast(msg, type = "success") {
    if (window.OporaToast) window.OporaToast.show(msg, type);
    else alert(msg);
  }

  function bindEditorEvents() {
    const form = document.getElementById("roleEditorForm");
    const moduleSelect = document.getElementById("fieldModuleSelect");
    if (moduleSelect) {
      moduleSelect.addEventListener("change", () => {
        document.querySelectorAll(".field-module-panel").forEach((el) => {
          el.classList.toggle("d-none", el.dataset.module !== moduleSelect.value);
        });
      });
    }
    if (form && canManage) {
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const res = await api(form.action, { method: "POST", body: new FormData(form) });
        const data = await res.json();
        if (data.ok) {
          toast(data.message || "Сохранено");
          if (data.id) window.location.href = `/roles?role_id=${data.id}`;
          else window.location.reload();
        } else {
          toast(data.message || "Ошибка сохранения", "danger");
        }
      });
    }
  }

  async function loadEditor(roleId) {
    const url = roleId ? `/roles/editor/${roleId}` : "/roles/editor/new";
    const res = await api(url);
    const data = await res.json();
    if (!data.html) return;
    editorPanel.innerHTML = data.html;
    bindEditorEvents();
    list.querySelectorAll(".roles-admin__item").forEach((el) => {
      el.classList.toggle("active", el.dataset.roleId === roleId);
    });
  }

  list?.addEventListener("click", (e) => {
    const item = e.target.closest(".roles-admin__item");
    if (!item) return;
    e.preventDefault();
    loadEditor(item.dataset.roleId);
    const name = item.querySelector(".fw-semibold")?.textContent;
    if (name && editorTitle) editorTitle.textContent = name;
  });

  document.getElementById("roleCreateBtn")?.addEventListener("click", () => {
    if (editorTitle) editorTitle.textContent = "Новая роль";
    loadEditor(null);
  });

  document.getElementById("roleDuplicateBtn")?.addEventListener("click", async (e) => {
    const id = e.currentTarget.dataset.roleId;
    if (!id || !confirm("Создать копию этой роли?")) return;
    const res = await api(`/roles/${id}/duplicate`, { method: "POST" });
    const data = await res.json();
    if (data.ok) {
      toast(data.message);
      window.location.href = `/roles?role_id=${data.id}`;
    } else toast(data.message, "danger");
  });

  document.getElementById("roleDeleteBtn")?.addEventListener("click", async (e) => {
    const id = e.currentTarget.dataset.roleId;
    if (!id || !confirm("Удалить эту роль?")) return;
    const fd = new FormData();
    fd.append("csrf_token", csrf);
    const res = await api(`/roles/${id}/delete`, { method: "POST", body: fd });
    const data = await res.json();
    if (data.ok) {
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

  bindEditorEvents();
})();
