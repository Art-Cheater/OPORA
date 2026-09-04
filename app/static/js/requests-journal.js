window.OporaRequestsJournal = {
  _abort: null,
  destroy() { this._abort?.abort(); this._abort = null; },
  init() {
    this.destroy();
    const abort = new AbortController();
    this._abort = abort;
    document.querySelectorAll(".journal-filters").forEach((form) => {
      if (form.dataset.journalFiltersBound === "1") return;
      form.dataset.journalFiltersBound = "1";
      const extraBtn = form.querySelector(".journal-filters__more");
      extraBtn?.addEventListener("click", () => {
        const open = form.classList.toggle("is-extra-open");
        extraBtn.setAttribute("aria-expanded", open ? "true" : "false");
      }, { signal: abort.signal });
    });
  },
};

(function bootJournal() {
  const run = () => window.OporaRequestsJournal.init();
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", run);
  } else {
    run();
  }
  window.addEventListener("opora:navigated", run);
  window.addEventListener("opora:before-navigate", () => window.OporaRequestsJournal.destroy());
})();
