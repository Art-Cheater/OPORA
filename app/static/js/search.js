(() => {
  const wrap = document.getElementById("globalSearchWrap");
  const input = document.getElementById("globalSearchInput");
  const dropdown = document.getElementById("globalSearchDropdown");
  if (!wrap || !input || !dropdown) return;

  let debounceTimer = null;
  let activeIndex = -1;
  let flatItems = [];

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text || "";
    return div.innerHTML;
  }

  async function fetchResults(query) {
    const res = await fetch(`/search/api?q=${encodeURIComponent(query)}&limit=5`);
    if (!res.ok) return null;
    return res.json();
  }

  function renderResults(data) {
    flatItems = [];
    activeIndex = -1;

    if (!data) {
      dropdown.innerHTML = '<div class="global-search-dropdown__empty">Ошибка поиска</div>';
      dropdown.classList.add("show");
      return;
    }

    if (data.query.length < 2) {
      dropdown.innerHTML = '<div class="global-search-dropdown__hint">Введите минимум 2 символа</div>';
      dropdown.classList.add("show");
      return;
    }

    if (data.total === 0) {
      dropdown.innerHTML = `<div class="global-search-dropdown__empty">Ничего не найдено по «${escapeHtml(data.query)}»</div>`;
      dropdown.classList.add("show");
      return;
    }

    let html = `<div class="global-search-dropdown__meta"><span>${data.total} результат(ов)</span><span>${data.took_ms} мс</span></div>`;

    data.categories.forEach((cat) => {
      html += `<div class="global-search-category"><div class="global-search-category__title"><i class="bi bi-${cat.icon}"></i>${escapeHtml(cat.label)}</div>`;
      cat.hits.forEach((item) => {
        const idx = flatItems.length;
        flatItems.push(item);
        html += `
          <a href="${item.url}" class="global-search-item" data-index="${idx}">
            <div class="global-search-item__title">${escapeHtml(item.title)}</div>
            ${item.subtitle ? `<div class="global-search-item__subtitle">${escapeHtml(item.subtitle)}</div>` : ""}
          </a>`;
      });
      html += "</div>";
    });

    html += `<div class="global-search-dropdown__footer"><a href="/search/?q=${encodeURIComponent(data.query)}">Показать все результаты</a></div>`;
    dropdown.innerHTML = html;
    dropdown.classList.add("show");
  }

  function debouncedSearch() {
    clearTimeout(debounceTimer);
    const q = input.value.trim();
    if (!q) {
      dropdown.classList.remove("show");
      return;
    }
    debounceTimer = setTimeout(async () => {
      const data = await fetchResults(q);
      renderResults(data);
    }, 200);
  }

  function highlightItem(index) {
    dropdown.querySelectorAll(".global-search-item").forEach((el) => el.classList.remove("active"));
    activeIndex = index;
    const el = dropdown.querySelector(`.global-search-item[data-index="${index}"]`);
    if (el) {
      el.classList.add("active");
      el.scrollIntoView({ block: "nearest" });
    }
  }

  input.addEventListener("input", debouncedSearch);
  input.addEventListener("focus", debouncedSearch);

  input.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      dropdown.classList.remove("show");
      input.blur();
      return;
    }
    if (!dropdown.classList.contains("show") || !flatItems.length) return;

    if (e.key === "ArrowDown") {
      e.preventDefault();
      highlightItem(Math.min(activeIndex + 1, flatItems.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      highlightItem(Math.max(activeIndex - 1, 0));
    } else if (e.key === "Enter" && activeIndex >= 0) {
      e.preventDefault();
      window.location.href = flatItems[activeIndex].url;
    }
  });

  document.addEventListener("click", (e) => {
    if (!wrap.contains(e.target)) {
      dropdown.classList.remove("show");
    }
  });

  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "k") {
      e.preventDefault();
      input.focus();
      input.select();
    }
  });
})();
