window.OporaRequestsJournal = {
  init() {
    document.querySelectorAll(".journal-filters").forEach((form) => {
      if (form.dataset.journalFiltersBound === "1") return;
      form.dataset.journalFiltersBound = "1";
      const extraBtn = form.querySelector(".journal-filters__more");
      extraBtn?.addEventListener("click", () => {
        const open = form.classList.toggle("is-extra-open");
        extraBtn.setAttribute("aria-expanded", open ? "true" : "false");
      });
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
})();
