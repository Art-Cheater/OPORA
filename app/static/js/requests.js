(() => {
  const form = document.getElementById("requestFilterForm");
  if (!form) return;

  const tableContainer = document.getElementById("requestsTableContainer");
  const paginationContainer = document.getElementById("requestsPaginationContainer");
  const resetBtn = document.getElementById("requestFilterReset");
  let currentPage = 1;
  let debounceTimer = null;

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
    const params = queryParams();
    const url = `/requests/table?${params.toString()}`;
    const response = await fetch(url, {
      headers: { "X-Requested-With": "XMLHttpRequest" },
    });
    if (!response.ok) return;
    const data = await response.json();
    tableContainer.innerHTML = data.table_html;
    paginationContainer.innerHTML = data.pagination_html;
    bindPagination();
  }

  function bindPagination() {
    paginationContainer.querySelectorAll(".request-page-link").forEach((link) => {
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

  bindPagination();
})();
