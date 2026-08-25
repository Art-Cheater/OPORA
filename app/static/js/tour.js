/**
 * Интерактивное обучение «Опора» — по ролям и с разбором экрана раздела.
 */
(() => {
  const PAD = 10;

  const LIST_STEPS = (noun, createLabel) => [
    {
      target: "page-header",
      title: "Заголовок раздела",
      text: `Вы в разделе «${noun}». Справа сверху — действия (создать, обновить и т.п.), если они доступны вашей роли.`,
    },
    {
      target: "filters",
      title: "Поиск и фильтры",
      text: "Заполните нужные поля и нажмите «Поиск». Без кнопки список не меняется. «Сброс» возвращает полный список.",
      optional: true,
    },
    {
      target: "create",
      title: createLabel || "Кнопка «Создать»",
      text: "Нажмите «Создать», чтобы открыть форму. Если кнопки нет — у вашей роли нет права создавать записи (можно только смотреть).",
      optional: true,
    },
    {
      target: "list-table",
      title: "Список записей",
      text: "Здесь все найденные строки. Клик по строке открывает карточку. В колонке действий: просмотр, карандаш (правка), корзина (удаление — если разрешено).",
      wait: 1200,
    },
    {
      target: "create",
      title: "Откроем форму",
      text: "Сейчас откроется окно создания — покажем, куда заполнять поля и где сохранять. Ничего сохранять не обязательно: в конце просто закроем окно.",
      action: "openCreate",
      optional: true,
    },
    {
      target: "form-body",
      title: "Поля формы",
      text: "Заполните обязательные поля (часто отмечены звёздочкой). Адрес подсказывается при вводе. Прокрутите форму вниз, если полей много.",
      optional: true,
    },
    {
      target: "form-save",
      title: "Сохранение",
      text: "Кнопка «Сохранить» (или «Создать») записывает данные. «Отмена» или крестик закрывают окно без сохранения. Сейчас закроем форму и продолжим.",
      action: "closeModals",
      optional: true,
    },
  ];

  const SECTIONS = [
    {
      id: "welcome",
      title: "Интерфейс",
      icon: "layout-sidebar",
      permission: null,
      steps: [
        {
          target: "sidebar",
          title: "Меню слева",
          text: "Все доступные вам разделы. Чужие модули скрыты — так устроены роли.",
        },
        {
          target: "search",
          title: "Глобальный поиск",
          text: "Быстрый поиск по системе. На компьютере: Ctrl+K.",
        },
        {
          target: "tour-button",
          title: "Обучение",
          text: "Эту кнопку можно нажать снова в любой момент. Автоматически обучение предлагается только при первом входе.",
        },
        {
          target: "messenger-top",
          title: "Сообщения и уведомления",
          text: "Чаты с коллегами и колокольчик уведомлений. Красная точка — есть непрочитанное.",
        },
        {
          target: "profile",
          title: "Профиль",
          text: "Ваше имя и роль. Здесь же можно снова открыть обучение или выйти.",
        },
      ],
    },
    {
      id: "requests",
      title: "Заявки",
      icon: "clipboard-check",
      permission: "requests.view",
      route: "/requests/",
      roleTips: {
        dispatcher: "Создаёте заявки, назначаете мастера/бригаду, следите за статусами.",
        master: "Берёте заявки в работу, отмечаете выполнение, закрываете.",
        executor: "Видите свои заявки, ход работ и материалы.",
      },
      steps: LIST_STEPS("Заявки", "Создать заявку"),
    },
    {
      id: "objects",
      title: "Объекты",
      icon: "geo-alt",
      permission: "objects.view",
      route: "/objects/",
      steps: LIST_STEPS("Объекты", "Создать объект"),
    },
    {
      id: "projects",
      title: "Проекты",
      icon: "folder2-open",
      permission: "projects.view",
      route: "/projects/",
      steps: LIST_STEPS("Проекты", "Создать проект"),
    },
    {
      id: "tenders",
      title: "Заявки на торги",
      icon: "hammer",
      permission: "tenders.view",
      route: "/tenders/",
      steps: LIST_STEPS("Заявки на торги", "Создать заявку на торги"),
    },
    {
      id: "contracts",
      title: "Контракты",
      icon: "file-earmark-text",
      permission: "contracts.view",
      route: "/contracts/",
      steps: [
        {
          target: "page-header",
          title: "Контракты",
          text: "Контракты из закупок и ЕИС. Обычно создаются импортом, реже вручную.",
        },
        {
          target: "filters",
          title: "Фильтры",
          text: "Ищите по номеру, подрядчику, году. Откройте строку — увидите суммы и документы.",
          optional: true,
        },
        {
          target: "list-table",
          title: "Список контрактов",
          text: "Клик по строке открывает карточку. Не путать с разделом «Договора на опоры».",
          wait: 1000,
        },
      ],
    },
    {
      id: "contractors",
      title: "Подрядчики",
      icon: "building",
      permission: "contractors.view",
      route: "/contractors/",
      steps: LIST_STEPS("Подрядчики", "Добавить подрядчика"),
    },
    {
      id: "agreements",
      title: "Договора на опоры",
      icon: "broadcast",
      permission: "agreements.view",
      route: "/agreements/",
      steps: [
        {
          target: "page-header",
          title: "Договора на опоры",
          text: "Договоры на размещение оборудования на опорах наружного освещения.",
        },
        {
          target: "filters",
          title: "Проверка адреса",
          text: "Введите улицу и нажмите «Проверить» — увидите, есть ли уже оборудование по адресу.",
        },
        {
          target: "agreements-map",
          title: "Карта",
          text: "Точки на карте — адреса из договоров. Нажмите точку, чтобы открыть договор и файл.",
          optional: true,
        },
        {
          target: "create",
          title: "Загрузить договор",
          text: "Выберите файл Word/PDF — система сама подтянет название, заказчика и таблицу адресов. Затем нажмите кнопку загрузки.",
          optional: true,
        },
        {
          target: "list-table",
          title: "Список договоров",
          text: "Откройте строку, чтобы править точки, сроки и файлы.",
          wait: 1000,
        },
      ],
    },
    {
      id: "inquiries",
      title: "Обращения",
      icon: "envelope",
      permission: "inquiries.view",
      route: "/inquiries/",
      roleTips: {
        dispatcher: "Письмо можно переслать сотруднику — оно появится у него в обращениях и в чате.",
      },
      steps: [
        {
          target: "page-header",
          title: "Обращения с почты",
          text: "Письма с корпоративного ящика. Если вам только пересылают — видите свою папку входящих.",
        },
        {
          target: "inquiries-sync",
          title: "Забрать письма",
          text: "Кнопка вручную забирает новые письма с почты. Обычно забор идёт сам по расписанию.",
          optional: true,
        },
        {
          target: "filters",
          title: "Поиск писем",
          text: "Поиск по теме и отправителю. Непрочитанные отмечены отдельно.",
          optional: true,
        },
        {
          target: "list-table",
          title: "Список писем",
          text: "Откройте письмо: текст, вложения (можно листать галереей), пересылка коллеге.",
          wait: 1000,
        },
      ],
    },
    {
      id: "eis",
      title: "Импорт ЕИС",
      icon: "cloud-download",
      permission: "eis.view",
      route: "/eis/",
      steps: [
        {
          target: "page-header",
          title: "Импорт ЕИС",
          text: "Подтягивает закупки и контракты с zakupki.gov.ru (Дирекция благоустройства, освещение).",
        },
        {
          target: "eis-run",
          title: "Запустить сейчас",
          text: "Ручной прогон. Идёт несколько минут — не нажимайте повторно. По расписанию тоже запускается сам.",
          optional: true,
        },
        {
          target: "page-header",
          title: "Результат",
          text: "Ниже — последний прогон: сколько создано проектов, торгов, контрактов и что не сопоставилось с объектами.",
        },
      ],
    },
    {
      id: "reports",
      title: "Отчёты",
      icon: "bar-chart",
      permission: "reports.view",
      route: "/reports/",
      steps: [
        {
          target: "page-header",
          title: "Отчёты",
          text: "Сводки для контроля. Выберите нужный отчёт на странице и при необходимости задайте период.",
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
          title: "Чаты",
          text: "Откройте «Мессенджер» в меню: слева чаты и контакты, справа переписка. Можно прикреплять файлы и карточки заявок.",
        },
        {
          target: "messenger-top",
          title: "Значок в шапке",
          text: "Быстрый вход в чат. При новом сообщении — звук и всплывающее уведомление, даже если вкладка свёрнута.",
        },
      ],
    },
    {
      id: "documents",
      title: "Личные документы",
      icon: "folder",
      permission: "documents.use",
      route: "/documents/",
      steps: [
        {
          target: "page-header",
          title: "Личные документы",
          text: "Ваш личный архив: обычные файлы и, по желанию, договоры. Чужие сюда не заглянут.",
        },
        {
          target: "docs-feature",
          title: "Включить договоры",
          text: "Переключатель включает вкладку «Договоры». Можно работать только с файлами — тогда оставьте выключенным.",
          optional: true,
        },
        {
          target: "docs-tabs",
          title: "Вкладки",
          text: "«Файлы» — обычные документы. «Договоры» — контракты со сроком и напоминаниями.",
          optional: true,
        },
        {
          target: "docs-file",
          title: "Выбор файлов",
          text: "На вкладке «Файлы» укажите PDF, Word, Excel или фото и нажмите «Загрузить».",
          optional: true,
        },
        {
          target: "docs-contract-upload",
          title: "Загрузка договора",
          text: "На вкладке «Договоры» загрузите PDF, DOC или DOCX. Система вытащит название и дату окончания (в том числе из сканов через OCR). Поля можно поправить вручную.",
          optional: true,
        },
        {
          target: "docs-contracts",
          title: "Список договоров",
          text: "Здесь сроки и напоминания: за месяц и за 2 недели до окончания придёт уведомление в колокольчик.",
          optional: true,
        },
        {
          target: "docs-list",
          title: "Мои файлы",
          text: "Открыть, скачать или удалить обычный документ.",
          optional: true,
        },
        {
          target: "notifications",
          title: "Колокольчик",
          text: "Напоминания о сроках договоров появятся здесь. Можно отметить все прочитанными.",
        },
      ],
    },
    {
      id: "employees",
      title: "Сотрудники",
      icon: "people",
      permission: "users.view",
      route: "/employees/",
      steps: LIST_STEPS("Сотрудники", "Добавить сотрудника").concat([
        {
          target: "page-header",
          title: "Роль сотрудника",
          text: "Важно: новому человеку назначают роль — от неё зависит, что он увидит в меню.",
        },
      ]),
    },
    {
      id: "roles",
      title: "Роли и права",
      icon: "shield-lock",
      permission: "roles.view",
      route: "/roles/",
      steps: [
        {
          target: "page-header",
          title: "Роли",
          text: "Матрица прав: какие разделы и поля доступны диспетчеру, мастеру, исполнителю.",
        },
        {
          target: "list-table",
          title: "Список ролей",
          text: "Откройте роль и отметьте галочки прав. Сохраните — у сотрудников с этой ролью меню обновится.",
          wait: 800,
          optional: true,
        },
      ],
    },
    {
      id: "audit",
      title: "Журнал действий",
      icon: "journal-text",
      permission: "audit.view",
      route: "/audit/",
      steps: [
        {
          target: "page-header",
          title: "Аудит",
          text: "Кто что изменил — для разбора спорных ситуаций.",
        },
        {
          target: "filters",
          title: "Фильтры журнала",
          text: "Отфильтруйте по пользователю, модулю или дате.",
          optional: true,
        },
        {
          target: "list-table",
          title: "Записи",
          text: "Каждая строка — действие в системе с временем и автором.",
          wait: 800,
        },
      ],
    },
  ];

  let config = { userId: "", userName: "", roles: [], roleNames: [], permissions: [] };
  let root = null;
  let steps = [];
  let index = 0;
  let mode = "menu";
  let running = false;

  function storageKey() {
    return `opora_tour_seen_v1_${config.userId || "anon"}`;
  }

  function hasSeen() {
    try {
      if (localStorage.getItem(storageKey()) === "1") return true;
      // старый ключ без userId — чтобы после обновления снова не всплывало
      if (localStorage.getItem("opora_tour_seen_v1") === "1") {
        localStorage.setItem(storageKey(), "1");
        return true;
      }
      return false;
    } catch {
      return true;
    }
  }

  function markSeen() {
    try {
      localStorage.setItem(storageKey(), "1");
    } catch {
      /* ignore */
    }
  }

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

  function sleep(ms) {
    return new Promise((resolve) => window.setTimeout(resolve, ms));
  }

  function targetEl(name) {
    if (!name) return null;
    return (
      document.querySelector(`[data-tour="${name}"]`) ||
      (name === "list-table" ? document.querySelector('[id$="TableContainer"]') : null) ||
      (name === "form-save"
        ? document.querySelector(
            "#oporaFormModal.show [type=submit], #oporaFormModal.show .btn-primary, #oporaFormModal .modal-form-footer .btn-primary"
          )
        : null) ||
      (name === "form-body"
        ? document.querySelector("#oporaFormModal.show .opora-modal-form, #oporaFormModal.show .modal-body, #oporaFormModalBody")
        : null)
    );
  }

  function closeModals() {
    document.querySelectorAll(".modal.show").forEach((modal) => {
      try {
        bootstrap.Modal.getInstance(modal)?.hide();
      } catch {
        /* ignore */
      }
    });
  }

  async function openCreate() {
    const btn = document.querySelector('[data-opora-create], [data-tour="create"]');
    if (!btn) return false;
    btn.click();
    const deadline = Date.now() + 4000;
    while (Date.now() < deadline) {
      const form =
        document.querySelector("#oporaFormModal.show form") ||
        document.querySelector("#oporaFormModal .opora-modal-form") ||
        document.querySelector("#oporaFormModalBody form");
      if (form) {
        form.setAttribute("data-tour", "form-body");
        const save =
          form.querySelector('[type="submit"]') ||
          form.querySelector(".btn-primary") ||
          document.querySelector("#oporaFormModal .modal-form-footer .btn-primary");
        if (save) save.setAttribute("data-tour", "form-save");
        await sleep(200);
        return true;
      }
      await sleep(120);
    }
    return false;
  }

  function pathMatches(route) {
    if (!route) return true;
    const now = window.location.pathname.replace(/\/+$/, "") || "/";
    const want = route.replace(/\/+$/, "") || "/";
    return now === want || now.startsWith(`${want}/`);
  }

  async function goRoute(route) {
    if (!route || pathMatches(route)) {
      await sleep(200);
      return;
    }
    const waitNav = new Promise((resolve) => {
      const onNav = () => {
        window.removeEventListener("opora:navigated", onNav);
        resolve();
      };
      window.addEventListener("opora:navigated", onNav);
      window.setTimeout(() => {
        window.removeEventListener("opora:navigated", onNav);
        resolve();
      }, 5000);
    });
    if (window.OporaNav?.go) {
      window.OporaNav.go(route, "Обучение");
    } else {
      window.location.href = route;
      return;
    }
    await waitNav;
    await sleep(350);
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
    root.querySelector("[data-tour-scrim]").addEventListener("click", () => {
      if (mode === "menu") stop();
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

  function openSidebarIfNeeded(targetName) {
    const sidebarTargets = new Set([
      "sidebar",
      "logo",
      "dashboard",
      "requests",
      "objects",
      "projects",
      "tenders",
      "contracts",
      "contractors",
      "agreements",
      "inquiries",
      "eis",
      "reports",
      "messenger",
      "documents",
      "employees",
      "roles",
      "audit",
      "about",
      "user-card",
    ]);
    if (!sidebarTargets.has(targetName)) return;
    if (window.innerWidth >= 992) return;
    document.getElementById("sidebar")?.classList.add("open");
    document.getElementById("sidebarOverlay")?.classList.add("show");
  }

  function placeCardNear(rect) {
    const card = root.querySelector("[data-tour-card]");
    card.style.position = "fixed";
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const cardW = Math.min(400, vw - 24);
    card.style.width = `${cardW}px`;
    card.style.maxWidth = `${cardW}px`;

    let top = 72;
    let left = Math.max(12, (vw - cardW) / 2);

    if (rect) {
      const below = rect.bottom + 16;
      const spaceBelow = vh - below;
      if (spaceBelow > 240) top = below;
      else top = Math.max(12, rect.top - 16 - 180);
      left = Math.min(Math.max(12, rect.left), vw - cardW - 12);
      if (rect.left > vw * 0.55) left = Math.max(12, rect.right - cardW);
    }
    card.style.top = `${Math.min(Math.max(12, top), vh - 100)}px`;
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
      return false;
    }
    openSidebarIfNeeded(targetName);
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
    return true;
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

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function buildSteps(sections) {
    const role = primaryRole();
    const out = [];
    sections.forEach((section) => {
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
          route: section.route || null,
        });
      });
    });
    return out;
  }

  function show() {
    ensureRoot();
    root.hidden = false;
    document.body.classList.add("is-opora-tour");
  }

  function stop() {
    markSeen();
    running = false;
    closeModals();
    if (!root) return;
    root.hidden = true;
    document.body.classList.remove("is-opora-tour");
    document.querySelectorAll(".opora-tour-target").forEach((el) => {
      el.classList.remove("opora-tour-target");
    });
    mode = "menu";
  }

  function finish() {
    markSeen();
    running = false;
    closeModals();
    mode = "menu";
    root.querySelector("[data-tour-spot]").hidden = true;
    root.querySelector("[data-tour-scrim]").style.opacity = "1";
    document.querySelectorAll(".opora-tour-target").forEach((el) => {
      el.classList.remove("opora-tour-target");
    });
    root.querySelector("[data-tour-progress]").hidden = true;
    root.querySelector("[data-tour-eyebrow]").textContent = "Готово";
    root.querySelector("[data-tour-title]").textContent = "Можно работать";
    root.querySelector("[data-tour-body]").innerHTML =
      "<p class=\"opora-tour__text\">Снова открыть обучение — кнопка «Обучение» вверху или пункт в меню профиля. Автоматически больше не спросим.</p>";
    placeCardNear(null);
    setActions([
      { label: "К разделам", className: "btn btn-outline-primary", onClick: openMenu },
      { label: "Закрыть", className: "btn btn-primary", onClick: stop },
    ]);
  }

  function renderMenu() {
    mode = "menu";
    steps = [];
    index = 0;
    running = false;
    closeModals();
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
        Покажем интерфейс и как работать в разделах (кнопки, фильтры, формы, сохранение).
        Роль: <strong>${rolesLabel}</strong> — только ваши доступные модули.
      </p>
      <div class="opora-tour__topics">${list || "<p class=\"text-muted\">Нет доступных разделов.</p>"}</div>
    `;
    root.querySelectorAll("[data-section]").forEach((btn) => {
      btn.addEventListener("click", () => startSection(btn.getAttribute("data-section")));
    });
    placeCardNear(null);
    setActions([
      { label: "Закрыть", className: "btn btn-outline-secondary", onClick: stop },
      { label: "Полный обзор", className: "btn btn-primary", onClick: () => startFull() },
    ]);
  }

  async function prepareStep(step) {
    if (step.route) await goRoute(step.route);
    if (step.wait) await sleep(step.wait);
    if (step.action === "openCreate") {
      const ok = await openCreate();
      if (!ok && step.optional) return "skip";
    }
    if (step.action === "closeModals") {
      /* close after highlight via next/finish — keep form visible for this step */
    }
    if (step.optional && step.target && !targetEl(step.target)) return "skip";
    if (step.target === "list-table") {
      const deadline = Date.now() + 2500;
      while (Date.now() < deadline && !targetEl("list-table")?.querySelector("table, .alert, tr")) {
        await sleep(150);
      }
    }
    return "ok";
  }

  async function renderStep() {
    if (!running) return;
    mode = "step";
    while (index < steps.length) {
      const step = steps[index];
      const prepared = await prepareStep(step);
      if (!running) return;
      if (prepared === "skip") {
        index += 1;
        continue;
      }
      break;
    }
    if (index >= steps.length) {
      finish();
      return;
    }

    const step = steps[index];
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
      { label: "Закрыть", className: "btn btn-outline-secondary", onClick: stop },
    ];
    if (index > 0) {
      actions.push({
        label: "Назад",
        className: "btn btn-outline-primary",
        onClick: async () => {
          closeModals();
          index -= 1;
          await renderStep();
        },
      });
    }
    actions.push({
      label: index === steps.length - 1 ? "Готово" : "Далее",
      className: "btn btn-primary",
      onClick: async () => {
        if (step.action === "closeModals") closeModals();
        if (index >= steps.length - 1) finish();
        else {
          index += 1;
          await renderStep();
        }
      },
    });
    setActions(actions);
  }

  async function startFull() {
    steps = buildSteps(availableSections());
    if (!steps.length) {
      openMenu();
      return;
    }
    index = 0;
    running = true;
    show();
    await renderStep();
  }

  async function startSection(sectionId) {
    const section = SECTIONS.find((item) => item.id === sectionId);
    if (!section || !can(section.permission)) {
      openMenu();
      return;
    }
    steps = buildSteps([section]);
    if (!steps.length) {
      openMenu();
      return;
    }
    index = 0;
    running = true;
    show();
    await renderStep();
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

  function init() {
    const parsed = readConfig();
    if (!parsed) return;
    config = parsed;
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
})();
