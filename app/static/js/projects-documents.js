/**
 * Форма документов проекта: single/multiple по типу, авто-название.
 */
window.OporaProjectDocuments = (() => {
  const OTHER = "other";

  function typeLabel(select) {
    const opt = select?.selectedOptions?.[0];
    return (opt?.textContent || "").trim() || "Документ";
  }

  function stemFromName(name) {
    const raw = String(name || "").trim();
    if (!raw) return "файл";
    const base = raw.includes(".") ? raw.slice(0, raw.lastIndexOf(".")) : raw;
    const stem = base.replace(/[_-]+/g, " ").trim();
    return stem || "файл";
  }

  function suggestTitle(form, files) {
    const typeSelect = form.querySelector("[data-doc-type], select[name='document_type']");
    const type = typeSelect?.value || "";
    const label = typeLabel(typeSelect);
    if (type === OTHER) {
      if (files.length === 1) return stemFromName(files[0].name);
      return "";
    }
    return label;
  }

  function syncFilesMode(form) {
    const typeSelect = form.querySelector("[data-doc-type], select[name='document_type']");
    const filesInput = form.querySelector("[data-doc-files], input[type='file'][name='files']");
    const label = form.querySelector("[data-doc-files-label]");
    const hint = form.querySelector("[data-doc-files-hint]");
    const warn = form.querySelector("[data-doc-files-warn]");
    const isOther = (typeSelect?.value || "") === (form.dataset.otherType || OTHER);

    if (filesInput) {
      if (isOther) filesInput.setAttribute("multiple", "multiple");
      else filesInput.removeAttribute("multiple");
    }
    if (label) label.textContent = isOther ? "Выберите файлы" : "Выберите файл";
    if (hint) {
      hint.textContent = isOther
        ? 'Для типа «Прочее» можно загрузить несколько файлов.'
        : "Для данного типа можно загрузить только один файл.";
    }
    if (warn) {
      warn.classList.add("d-none");
      warn.textContent = "";
    }
  }

  function showWarn(form, message) {
    const warn = form.querySelector("[data-doc-files-warn]");
    if (!warn) {
      window.alert(message);
      return;
    }
    warn.textContent = message;
    warn.classList.remove("d-none");
  }

  function updatePreview(form, files) {
    const preview = form.querySelector("[data-doc-files-preview]");
    if (!preview) return;
    if (!files.length) {
      preview.classList.add("d-none");
      preview.textContent = "";
      return;
    }
    preview.classList.remove("d-none");
    preview.textContent =
      files.length === 1
        ? `Выбран: ${files[0].name}`
        : `Выбрано файлов: ${files.length} — ${[...files].map((f) => f.name).join(", ")}`;
  }

  function applyAutoTitle(form, files) {
    if (form.dataset.titleManual === "1") return;
    const titleInput = form.querySelector("[data-doc-title], input[name='title']");
    if (!titleInput) return;
    const suggested = suggestTitle(form, files);
    titleInput.value = suggested;
  }

  function bindForm(form) {
    if (!form || form.dataset.docBound === "1") return;
    form.dataset.docBound = "1";
    form.dataset.titleManual = "0";

    const typeSelect = form.querySelector("[data-doc-type], select[name='document_type']");
    const titleInput = form.querySelector("[data-doc-title], input[name='title']");
    const filesInput = form.querySelector("[data-doc-files], input[type='file'][name='files']");

    titleInput?.addEventListener("input", () => {
      form.dataset.titleManual = "1";
    });

    typeSelect?.addEventListener("change", () => {
      syncFilesMode(form);
      if (filesInput) {
        filesInput.value = "";
        updatePreview(form, []);
      }
      // Смена типа: новое авто-название, если пользователь не правил вручную
      applyAutoTitle(form, []);
    });

    filesInput?.addEventListener("change", () => {
      const type = typeSelect?.value || "";
      const isOther = type === (form.dataset.otherType || OTHER);
      const files = filesInput.files ? [...filesInput.files] : [];
      if (!isOther && files.length > 1) {
        showWarn(form, "Для выбранного типа документа можно загрузить только один файл.");
        filesInput.value = "";
        updatePreview(form, []);
        return;
      }
      const warn = form.querySelector("[data-doc-files-warn]");
      if (warn) {
        warn.classList.add("d-none");
        warn.textContent = "";
      }
      updatePreview(form, files);
      applyAutoTitle(form, files);
    });

    form.addEventListener("submit", (event) => {
      const type = typeSelect?.value || "";
      const isOther = type === (form.dataset.otherType || OTHER);
      const files = filesInput?.files ? [...filesInput.files] : [];
      if (!files.length) {
        event.preventDefault();
        showWarn(form, "Выберите файл для загрузки.");
        return;
      }
      if (!isOther && files.length > 1) {
        event.preventDefault();
        showWarn(form, "Для выбранного типа документа можно загрузить только один файл.");
      }
    });

    syncFilesMode(form);
  }

  function init(root) {
    const scope = root || document;
    scope.querySelectorAll("form[data-project-documents]").forEach(bindForm);
  }

  return { init };
})();

document.addEventListener("DOMContentLoaded", () => {
  window.OporaProjectDocuments?.init?.();
});
