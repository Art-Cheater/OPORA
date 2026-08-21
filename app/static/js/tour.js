/**
 * Интерактивное обучение «Опора» — шаги зависят от прав и роли.
 */
(() => {
  const STORAGE_KEY = "opora_tour_seen_v1";
  const PAD = 10;

  const SECTIONS = [
    {
      id: "welcome",
      title: "Добро пожаловать",
      icon: "mortarboard",
      permission: null,
      steps: [
        {
          target: "sidebar",
          title: "Меню слева",
          text: "Здесь собраны все разделы, к которым у вас есть доступ. Набор пунктов зависит от вашей роли — чужие разделы просто не показываются.",
        },
        {
          target: "search",
          title: "Глобальный поиск",
          text: "Быстрый поиск по заявкам, адресам, проектам и сотрудникам. На компьютере удобно открывать сочетанием Ctrl+K.",
        },
        {
          target: "tour-button",
          title: "Кнопка «Обучение»",
          text: "В любой момент можно снова пройти обзор или открыть помощь только по нужному разделу. Обучение можно прервать кнопкой «Закрыть».",
        },
        {
          target: "profile",
          title: "Ваш профиль",
          text: "Здесь видно ваше имя и роль. Через меню можно открыть профиль, снова запустить обучение или выйти из системы.",
        },
      ],
    },
    {
      id: "requests",
      title: "Заявки",
      icon: "clipboard-check",
      permission: "requests.view",
      roleTips: {
        dispatcher:
          "Диспетчер создаёт заявки, назначает выезд бригады и следит за статусами.",
        master:
          "Мастер принимает заявки в работу, отмечает выполнение и закрывает их.",
        executor:
          "Исполнитель видит свои заявки, отмечает ход работ и добавляет материалы.",
        director: "Руководство контролирует поток заявок и результаты.",
      },
      steps: [
        {
          target: "requests",
          title: "Раздел «Заявки»",
          text: "Основная работа по обращениям жителей и аварийным выездам: список, фильтры, статусы, фото и история.",
        },
        {
          target: "requests",
          title: "Как пользоваться",
          text: "Откройте заявку из списка. В карточке меняют статус, добавляют файлы, материалы и комментарии. Повторные звонки по адресу подсвечиваются.",
        },
      ],
    },
    {
      id: "objects",
      title: "Объекты",
      icon: "geo-alt",
      permission: "objects.view",
      steps: [
        {
          target: "objects",
          title: "Адресные объекты",
          text: "Справочник улиц и мест работ: дворы, МКД, планы освещения. По объектам строятся проекты и торги.",
        },
      ],
    },
    {
      id: "projects",
      title: "Проекты",
      icon: "folder2-open",
      permission: "projects.view",
      steps: [
        {
          target: "projects",
          title: "Проекты",
          text: "Карточки работ по объектам: состав, документы, связь с торгами и контрактами.",
        },
      ],
    },
    {
      id: "tenders",
      title: "Заявки на торги",
      icon: "hammer",
      permission: "tenders.view",
      steps: [
        {
          target: "tenders",
          title: "Торги",
          text: "Подготовка заявок на закупки по объектам и проектам: сроки, состав, документы.",
        },
      ],
    },
    {
      id: "contracts",
      title: "Контракты",
      icon: "file-earmark-text",
      permission: "contracts.view",
      steps: [
        {
          target: "contracts",
          title: "Контракты (ЕИС)",
          text: "Контракты из закупок и ЕИС: суммы, подрядчики, документы. Не путать с «Договорами на опоры».",
        },
      ],
    },
    {
      id: "contractors",
      title: "Подрядчики",
      icon: "building",
      permission: "contractors.view",
      steps: [
        {
          target: "contractors",
          title: "Подрядчики",
          text: "Справочник организаций-исполнителей, связанных с контрактами.",
        },
      ],
    },
    {
      id: "agreements",
      title: "Договора на опоры",
      icon: "broadcast",
      permission: "agreements.view",
      steps: [
        {
          target: "agreements",
          title: "Договора на опоры",
          text: "Договоры на размещение оборудования на опорах наружного освещения, карта точек и файлы договоров.",
        },
      ],
    },
    {
      id: "inquiries",
      title: "Обращения",
      icon: "envelope",
      permission: "inquiries.view",
      roleTips: {
        dispatcher:
          "Письма с корпоративной почты можно переслать сотруднику в чат и в его список обращений.",
      },
      steps: [
        {
          target: "inquiries",
          title: "Обращения с почты",
          text: "Входящие письма с kirovsvet@mail.ru. Откройте письмо, посмотрите вложения, при необходимости перешлите коллеге.",
        },
      ],
    },
    {
      id: "eis",
      title: "Импорт ЕИС",
      icon: "cloud-download",
      permission: "eis.view",
      steps: [
        {
          target: "eis",
          title: "Импорт с zakupki.gov.ru",
          text: "Автозагрузка закупок и контрактов Дирекции благоустройства. Запускается по расписанию или вручную.",
        },
      ],
    },
    {
      id: "reports",
      title: "Отчёты",
      icon: "bar-chart",
      permission: "reports.view",
      steps: [
        {
          target: "reports",
          title: "Отчёты",
          text: "Сводки по объектам и работе подразделений для контроля и руководства.",
        },
      ],
    },
    {
      id: "messenger",
      title: "Мессенджер",
      icon: "chat-dots",
      permission: "messenger.use",
      steps: [
        {
          target: "messenger",
          title: "Корпоративный чат",
          text: "Переписка с коллегами, файлы и карточки заявок/обращений. При новом сообщении — звук и всплывающее уведомление.",
        },
        {
          target: "messenger-top",
          title: "Значок в шапке",
          text: "Красная точка на значке чата показывает непрочитанные сообщения. Откройте мессенджер и ответьте коллеге.",
        },
      ],
    },
    {
      id: "documents",
      title: "Личные документы",
      icon: "folder",
      permission: "documents.use",
      steps: [
        {
          target: "documents",
          title: "Ваши файлы",
          text: "Личный архив: загружайте PDF, Word, Excel и фото. Их видите только вы.",
        },
      ],
    },
    {
      id: "employees",
      title: "Сотрудники",
      icon: "people",
      permission: "users.view",
      steps: [
        {
          target: "employees",
          title: "Сотрудники",
          text: "Учётные записи: ФИО, роль, отдел, блокировка. Новому человеку назначают роль — от неё зависит меню.",
        },
      ],
    },
    {
      id: "roles",
      title: "Роли и права",
      icon: "shield-lock",
      permission: "roles.view",
      steps: [
        {
          target: "roles",
          title: "Роли",
          text: "Матрица прав: какие разделы и поля видит диспетчер, мастер, исполнитель. Администратор настраивает доступ без программиста.",
        },
      ],
    },
    {
      id: "audit",
      title: "Журнал действий",
      icon: "journal-text",
      permission: "audit.view",
      steps: [
        {
          target: "audit",
          title: "Аудит",
          text: "Кто что изменил в системе — для разбора спорных ситуаций и контроля.",
        },
      ],
    },
  ];

  let config = { userName: "", roles: [], roleNames: [], permissions: [] };
  let root = null;
  let steps = [];
  let index = 0;
  let mode = "menu";

  function can(permission) {
    if (!permission) return true;
    const perms = config.permissions || [];
    return perms.includes("*") || perms.includes(permission);
  }

  function primaryRole() {
    const roles = config.roles || [];
    for (const code of ["admin", "director", "dispatcher", "master", "executor"]) {
      if (roles.includes(code)) return code;
    }
    return roles[0] || "";
  }

  function availableSections() {
    return SECTIONS.filter((section) => can(section.permission));
  }

  function buildFullSteps() {
    const role = primaryRole();
    const out = [];
    availableSections().forEach((section) => {
      section.steps.forEach((step, stepIndex) => {
        let text = step.text;
        if (stepIndex === 0 && section.roleTips && section.roleTips[role]) {
          text = `${text}\n\nДля вашей роли: ${section.roleTips[role]}`;
        }
        out.push({
          ...step,
          text,
          sectionId: section.id,
          sectionTitle: section.title,
        });
      });
    });
    return out;
  }

  function buildSectionSteps(sectionId) {
    const section = SECTIONS.find((item) => item.id === sectionId);
    if (!section || !can(section.permission)) return [];
    const role = primaryRole();
    return section.steps.map((step, stepIndex) => {
      let text = step.text;
      if (stepIndex === 0 && section.roleTips && section.roleTips[role]) {
        text = `${text}\n\nДля вашей роли: ${section.roleTips[role]}`;
      }
      return {
        ...step,
        text,
        sectionId: section.id,
        sectionTitle: section.title,
      };
    });
  }

  function targetEl(name) {
    if (!name) return null;
    return document.querySelector(`[data-tour="${name}"]`);
  }

  function ensureRoot() {
    if (root) return root;
    root = document.createElement("div");
    root.id = "oporaTour";
    root.className = "opora-tour";
    root.hidden = true;
    root.innerHTML = `
      <div class="opora-tour__scrim" data-tour-scrim></div>
      <div class="opora-tour__spot" data-tour-spot hidden></div>
      <div class="opora-tour__card" data-tour-card role="dialog" aria-modal="true" aria-labelledby="oporaTourTitle">
        <div class="opora-tour__card-head">
          <div>
            <div class="opora-tour__eyebrow" data-tour-eyebrow></div>
            <h2 class="opora-tour__title" id="oporaTourTitle" data-tour-title></h2>
          </div>
          <button type="button" class="opora-tour__x" data-tour-close title="Закрыть обучение" aria-label="Закрыть">
            <i class="bi bi-x-lg"></i>
          </button>
        </div>
        <div class="opora-tour__body" data-tour-body></div>
        <div class="opora-tour__progress" data-tour-progress hidden>
          <div class="opora-tour__bar"><span data-tour-bar></span></div>
          <div class="opora-tour__count" data-tour-count></div>
        </div>
        <div class="opora-tour__actions" data-tour-actions></div>
      </div>
    `;
    document.body.appendChild(root);
    root.querySelector("[data-tour-close]").addEventListener("click", stop);
    root.querySelector("[data-tour-scrim]").addEventListener("click", (event) => {
      if (mode === "menu") stop();
      else event.stopPropagation();
    });
    document.addEventListener("keydown", (event) => {
      if (root.hidden) return;
      if (event.key === "Escape") {
        event.preventDefault();
        stop();
      }
    });
    return root;
  }

  function openSidebarIfNeeded() {
    const sidebar = document.getElementById("sidebar");
    if (!sidebar || window.innerWidth >= 992) return;
    sidebar.classList.add("is-open");
    document.getElementById("sidebarOverlay")?.classList.add("is-open");
  }

  function placeCardNear(rect) {
    const card = root.querySelector("[data-tour-card]");
    card.style.position = "fixed";
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const cardW = Math.min(400, vw - 24);
    card.style.width = `${cardW}px`;
    card.style.maxWidth = `${cardW}px`;

    let top = 80;
    let left = Math.max(12, (vw - cardW) / 2);

    if (rect) {
      const below = rect.bottom + 16;
      const above = rect.top - 16;
      const spaceBelow = vh - below;
      if (spaceBelow > 220) {
        top = below;
      } else if (above > 220) {
        top = Math.max(12, above - 200);
      } else {
        top = Math.max(12, Math.min(below, vh - 240));
      }
      left = Math.min(Math.max(12, rect.left), vw - cardW - 12);
      if (rect.left > vw * 0.55) {
        left = Math.max(12, rect.right - cardW);
      }
    }
    card.style.top = `${Math.min(top, vh - 80)}px`;
    card.style.left = `${left}px`;
  }

  function highlight(targetName) {
    const spot = root.querySelector("[data-tour-spot]");
    const scrim = root.querySelector("[data-tour-scrim]");
    document.querySelectorAll(".opora-tour-target").forEach((el) => {
      el.classList.remove("opora-tour-target");
    });
    const el = targetEl(targetName);
    if (!el) {
      spot.hidden = true;
      scrim.style.opacity = "1";
      placeCardNear(null);
      return;
    }
    openSidebarIfNeeded();
    el.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "smooth" });
    const rect = el.getBoundingClientRect();
    el.classList.add("opora-tour-target");
    spot.hidden = false;
    scrim.style.opacity = "0";
    spot.style.top = `${Math.max(0, rect.top - PAD)}px`;
    spot.style.left = `${Math.max(0, rect.left - PAD)}px`;
    spot.style.width = `${rect.width + PAD * 2}px`;
    spot.style.height = `${rect.height + PAD * 2}px`;
    placeCardNear(rect);
  }

  function setActions(buttons) {
    const box = root.querySelector("[data-tour-actions]");
    box.innerHTML = "";
    buttons.forEach((btn) => {
      const el = document.createElement("button");
      el.type = "button";
      el.className = btn.className;
      el.textContent = btn.label;
      el.addEventListener("click", btn.onClick);
      box.appendChild(el);
    });
  }

  function renderMenu() {
    mode = "menu";
    steps = [];
    index = 0;
    const spot = root.querySelector("[data-tour-spot]");
    const scrim = root.querySelector("[data-tour-scrim]");
    spot.hidden = true;
    scrim.style.opacity = "1";
    root.querySelector("[data-tour-progress]").hidden = true;
    root.querySelector("[data-tour-eyebrow]").textContent = "Обучение";
    const rolesLabel = (config.roleNames || []).join(", ") || "сотрудник";
    root.querySelector("[data-tour-title]").textContent = `Здравствуйте, ${
      config.userName || "коллега"
    }!`;
    const sections = availableSections().filter((s) => s.id !== "welcome");
    const list = sections
      .map(
        (section) => `
      <button type="button" class="opora-tour__topic" data-section="${section.id}">
        <i class="bi bi-${section.icon}"></i>
        <span>${section.title}</span>
      </button>`
      )
      .join("");
    root.querySelector("[data-tour-body]").innerHTML = `
      <p class="opora-tour__lead">
        Краткий обзор системы «Опора» для роли: <strong>${rolesLabel}</strong>.
        Покажем только те разделы, которые доступны именно вам.
      </p>
      <div class="opora-tour__topics">${list || "<p class=\"text-muted\">Нет доступных разделов.</p>"}</div>
    `;
    root.querySelectorAll("[data-section]").forEach((btn) => {
      btn.addEventListener("click", () => startSection(btn.getAttribute("data-section")));
    });
    placeCardNear(null);
    setActions([
      {
        label: "Закрыть",
        className: "btn btn-outline-secondary",
        onClick: stop,
      },
      {
        label: "Полный обзор",
        className: "btn btn-primary",
        onClick: () => startFull(),
      },
    ]);
  }

  function renderStep() {
    mode = "step";
    const step = steps[index];
    if (!step) {
      finish();
      return;
    }
    root.querySelector("[data-tour-progress]").hidden = false;
    root.querySelector("[data-tour-eyebrow]").textContent = step.sectionTitle || "Обучение";
    root.querySelector("[data-tour-title]").textContent = step.title;
    root.querySelector("[data-tour-body]").innerHTML = `<p class="opora-tour__text">${String(step.text)
      .split("\n")
      .map((line) => escapeHtml(line))
      .join("<br>")}</p>`;
    const pct = ((index + 1) / steps.length) * 100;
    root.querySelector("[data-tour-bar]").style.width = `${pct}%`;
    root.querySelector("[data-tour-count]").textContent = `${index + 1} из ${steps.length}`;
    highlight(step.target);

    const actions = [
      {
        label: "Закрыть",
        className: "btn btn-outline-secondary",
        onClick: stop,
      },
    ];
    if (index > 0) {
      actions.push({
        label: "Назад",
        className: "btn btn-outline-primary",
        onClick: () => {
          index -= 1;
          renderStep();
        },
      });
    }
    actions.push({
      label: index === steps.length - 1 ? "Готово" : "Далее",
      className: "btn btn-primary",
      onClick: () => {
        if (index >= steps.length - 1) finish();
        else {
          index += 1;
          renderStep();
        }
      },
    });
    setActions(actions);
  }

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function show() {
    ensureRoot();
    root.hidden = false;
    document.body.classList.add("is-opora-tour");
  }

  function stop() {
    if (!root) return;
    root.hidden = true;
    document.body.classList.remove("is-opora-tour");
    document.querySelectorAll(".opora-tour-target").forEach((el) => {
      el.classList.remove("opora-tour-target");
    });
    mode = "menu";
  }

  function finish() {
    try {
      localStorage.setItem(STORAGE_KEY, "1");
    } catch {
      /* ignore */
    }
    mode = "menu";
    root.querySelector("[data-tour-spot]").hidden = true;
    document.querySelectorAll(".opora-tour-target").forEach((el) => {
      el.classList.remove("opora-tour-target");
    });
    root.querySelector("[data-tour-progress]").hidden = true;
    root.querySelector("[data-tour-eyebrow]").textContent = "Готово";
    root.querySelector("[data-tour-title]").textContent = "Отлично, можно работать";
    root.querySelector("[data-tour-body]").innerHTML =
      "<p class=\"opora-tour__text\">Обучение можно снова открыть кнопкой «Обучение» вверху или из меню профиля.</p>";
    placeCardNear(null);
    setActions([
      {
        label: "К разделам",
        className: "btn btn-outline-primary",
        onClick: openMenu,
      },
      {
        label: "Закрыть",
        className: "btn btn-primary",
        onClick: stop,
      },
    ]);
  }

  function startFull() {
    steps = buildFullSteps();
    if (!steps.length) {
      openMenu();
      return;
    }
    index = 0;
    renderStep();
  }

  function startSection(sectionId) {
    steps = buildSectionSteps(sectionId);
    if (!steps.length) {
      openMenu();
      return;
    }
    index = 0;
    renderStep();
  }

  function openMenu() {
    show();
    renderMenu();
  }

  function readConfig() {
    const node = document.getElementById("oporaTourConfig");
    if (!node) return null;
    try {
      return JSON.parse(node.textContent || "{}");
    } catch {
      return null;
    }
  }

  function bindTriggers() {
    document.getElementById("oporaTourBtn")?.addEventListener("click", (event) => {
      event.preventDefault();
      openMenu();
    });
    document.getElementById("oporaTourMenuStart")?.addEventListener("click", (event) => {
      event.preventDefault();
      openMenu();
    });
  }

  function maybeAutoOffer() {
    let seen = false;
    try {
      seen = localStorage.getItem(STORAGE_KEY) === "1";
    } catch {
      seen = true;
    }
    if (seen) return;
    if (!document.getElementById("appShell")) return;
    window.setTimeout(() => {
      if (document.getElementById("messengerApp")) return;
      openMenu();
    }, 900);
  }

  function init() {
    const parsed = readConfig();
    if (!parsed) return;
    config = parsed;
    bindTriggers();
    maybeAutoOffer();
    window.addEventListener("resize", () => {
      if (!root || root.hidden || mode !== "step") return;
      const step = steps[index];
      if (step) highlight(step.target);
    });
  }

  window.OporaTour = {
    init,
    open: openMenu,
    startFull,
    startSection,
    stop,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
