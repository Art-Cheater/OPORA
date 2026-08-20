window.OporaAudit = (() => {
  let tableAbort = null;
  let debounceTimer = null;
  let currentPage = 1;

  function init() {
    const form = document.getElementById("auditFilterForm");
    if (!form) return;

    const tableContainer = document.getElementById("auditTableContainer");
    const paginationContainer = document.getElementById("auditPaginationContainer");
    const resetBtn = document.getElementById("auditFilterReset");
    currentPage = 1;
    clearTimeout(debounceTimer);
    tableAbort?.abort();

    function queryParams() {
      const data = new FormData(form);
      data.set("page", String(currentPage));
      const params = new URLSearchParams();
      for (const [k, v] of data.entries()) {
        if (v !== "") params.append(k, String(v));
      }
      return params;
    }

    async function loadTable() {
      if (!tableContainer) return;
      tableAbort?.abort();
      tableAbort = new AbortController();
      const params = queryParams();
      try {
        const res = await fetch(`/audit/table?${params.toString()}`, {
          headers: { "X-Requested-With": "XMLHttpRequest" },
          signal: tableAbort.signal,
        });
        if (!res.ok) return;
        const data = await res.json();
        tableContainer.innerHTML = data.table_html;
        if (paginationContainer) paginationContainer.innerHTML = data.pagination_html;
        bindPagination();
      } catch (err) {
        if (err?.name === "AbortError") return;
      }
    }

    function bindPagination() {
      paginationContainer?.querySelectorAll(".audit-page-link").forEach((link) => {
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

    function debouncedReload() {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        currentPage = 1;
        loadTable();
      }, 300);
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

    loadTable();
  }

  document.addEventListener("DOMContentLoaded", init);

  return { init };
})();
