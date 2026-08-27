# PROJECT_CONTEXT.md — технический паспорт «Опора»

> Единый контекст для Cursor / ChatGPT / разработчиков.  
> **Не README.** Отвечает на вопрос: *как устроена система и как безопасно менять код.*  
> Источник истины — текущий код репозитория. Секреты сюда не записывать.

**Снимок состояния (проверено при генерации файла):**

| Поле | Значение |
|------|----------|
| Branch | `main` |
| HEAD | `1099d33` — `[фикс] Аудит: privilege escalation, path traversal, wipe, индексы` |
| RELEASE | `20260826h` (`app/release.py`) |
| Alembic head | `035_integrity_indexes` |
| Origin | локально `main` может быть **ahead 1** относительно `origin/main` — перед деплоем сверить |

---

# 1. Project Overview

| | |
|--|--|
| **Название** | Опора |
| **Тип** | Корпоративная ИС (монолит Flask), server-rendered UI + лёгкая SPA-навигация |
| **Бизнес-задача** | Диспетчеризация заявок по наружному освещению (Киров), учёт объектов/проектов/торгов/контрактов, договора на опоры, корпоративная почта, импорт ЕИС, внутренняя коммуникация |
| **Пользователи** | Администратор, директор, диспетчер, мастер, исполнитель (роли из seed) |
| **Основные сценарии** | Приём и жизненный цикл заявки; импорт/ведение объектов; автосоздание проекта по результату обследования; торги и контракты; договора на опоры с картой; обращения с IMAP; мессенджер; личные документы; матрица ролей |
| **Стиль** | Modular monolith: Blueprint → Route → Service → Repository → SQLAlchemy → PostgreSQL |

Публичной саморегистрации нет: учётные записи создаёт сотрудник с правом `users.create`.

---

# 2. Technology Stack

| Технология | Версия / факт | Где |
|------------|---------------|-----|
| Python | **3.12** | `Dockerfile` |
| Flask | 3.1.0 | `requirements.txt` |
| Flask-SQLAlchemy | 3.1.1 | |
| Flask-Migrate / Alembic | 4.0.7 | |
| PostgreSQL | **17** (Docker `postgres:17-alpine`) | `docker-compose.yml` |
| Schema | по умолчанию `opora` (`POSTGRES_SCHEMA`) | `app/config.py` |
| Flask-Login | 0.6.3 | |
| Flask-WTF / WTForms | 1.2.2 / 3.2.1 | CSRF |
| bcrypt | 4.2.1 | пароли |
| Gunicorn | 23.0.0, `gthread` | `Dockerfile` CMD |
| Nginx | reverse proxy + static | `docker/nginx.conf` |
| Bootstrap 5 | vendor CSS/JS | `app/static` |
| JavaScript | vanilla | `app/static/js/*` |
| Leaflet | карта договоров | `agreements-map.js` |
| OSM embed | карта заявки | `request-detail.js` |
| openpyxl / pypdf / pymupdf / Pillow / pytesseract | импорт Excel, PDF, OCR | |
| pytest | 8.3.5 | |
| locust | 2.34.1 | нагрузка |
| Docker Compose | db, web, nginx, 3 workers | |
| Опц. LibreOffice | build-arg `WITH_LIBREOFFICE` | парсинг .doc |

Опционально локально: **SQLite** (`USE_SQLITE=1`) для dev/tests.

---

# 3. Architecture

```text
Browser
  → Nginx (:5000→80) — static + proxy
  → Gunicorn (wsgi:app)
  → Flask create_app()
       before_request: block inactive; SPA flag (X-Opora-Nav)
  → Blueprint (registry)
  → Route (@login_required + @permission_required)
  → Service (бизнес-правила, ValidationError)
  → Repository (запросы, pagination, eager/noload)
  → SQLAlchemy / PostgreSQL
  → Response: full HTML | spa_shell partial | JSON ajax_ok/ajax_error
  → after_request: security headers, SPA headers
```

### Routes (`*/routes.py`)
HTTP: формы, redirects, `ajax_ok`/`ajax_error`, декораторы прав, тонкая склейка form → payload. **Не** место для длинной бизнес-логики и сложных запросов.

### Services (`*/services.py`)
Правила, транзакции `commit`, audit, side effects (статусы, цепочки Object→Project). Единственная «правда» изменений данных.

### Repositories (`*/repositories.py`)
Выборки, фильтры, `paginated_list`, `joinedload`/`noload`. Без бизнес-переходов статусов.

### Models (`app/models/`)
Таблицы, FK, soft-delete (`BaseModel`), relationships. Почти все сущности наследуют soft-delete.

### Core (`app/core/`)
Cross-cutting: `permission_service`, `decorators`, `upload_utils`, `address/*`, `audit_service`, `http`, `security`, field permissions helpers.

### Integrations (`app/integrations/`)
Внешние HTTP (сейчас zakupki/ЕИС). Не UI-модули.

### Seed (`app/seed/`)
Справочники статусов, ролей, каталог permissions/modules/fields.

---

# 4. Project Structure

```text
OPORA/
├── app/
│   ├── __init__.py          # factory, SPA, CLI, errors, security hooks
│   ├── config.py            # env-конфиг
│   ├── release.py           # RELEASE для /health и ?v= cache-bust
│   ├── extensions.py        # db, migrate, login, csrf
│   ├── core/
│   ├── models/
│   ├── modules/             # бизнес-модули (blueprints)
│   ├── integrations/zakupki/
│   ├── seed/
│   ├── static/{css,js,vendor}/
│   └── templates/{layouts,components,macros}/
├── migrations/versions/     # 001 … 035
├── tests/
├── docker/                  # entrypoint, nginx
├── scripts/                 # deploy, backup, locust, helpers
├── docs/
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── run.py / wsgi.py
└── .env.example
```

**Зарегистрированные modules** (`app/modules/registry.py`):  
`main`, `auth`, `requests`, `objects`, `projects`, `tenders`, `contracts`, `contractors`, `agreements`, `inquiries`, `eis`, `employees`, `positions`, `roles`, `field_builder`, `messenger`, `documents`, `notifications`, `search`, `audit`, `reports`.

**Не в registry:** `_template` (`/_template`).  
**В каталоге прав без blueprint:** `materials` (seed/`MODULE_ACTIONS` — модуля UI нет).

---

# 5. Module Map

| Module | Prefix | Назначение | Основные модели | Services / ключевое | Permissions (типично) |
|--------|--------|------------|-----------------|---------------------|------------------------|
| main | `/` | index, health, about | — | — | public health/about |
| auth | `/auth` | login/logout/profile/logs | User, LoginLog | AuthService | profile.*, auth.login_logs.view |
| requests | `/requests` | Диспетчерские заявки | Request, Status, History, Material | RequestService, workflow | requests.* , approve, dispatch |
| objects | `/objects` | Объекты освещения, Excel, цепочка | WorkObject | ObjectService | objects.* |
| projects | `/projects` | Проекты | Project, Member, Document, History | ProjectService | projects.* |
| tenders | `/tenders` | Заявки на торги | TenderApplication, TenderProject | TenderService | tenders.* |
| contracts | `/contracts` | Контракты | Contract, ContractObject, … | ContractService | contracts.* |
| contractors | `/contractors` | Подрядчики | Contractor | ContractorService | contractors.* |
| agreements | `/agreements` | Договора на опоры + карта | PoleAgreement, Site | AgreementService | agreements.* |
| inquiries | `/inquiries` | Почтовые обращения | Inquiry | InquiryService | inquiries.* , sync |
| eis | `/eis` | Импорт zakupki | EisImportRun/Event | EisImportService | eis.view, eis.run |
| employees | `/employees` | Сотрудники | User, UserRole | EmployeeService | users.* |
| roles | `/roles` | Матрица прав | Role, RolePermission, RoleFieldPermission | RoleService | roles.view, roles.manage |
| field_builder | `/field-builder` | Поля модулей | FieldDefinition, CustomField | — | roles.manage |
| positions | `/positions` | Должности (список) | Position | — | roles.manage |
| messenger | `/messenger` | Чаты | Conversation, Message | MessengerService | messenger.use |
| documents | `/documents` | Личные файлы/договоры | Attachment, PersonalContract | PersonalDocumentService | documents.use |
| notifications | `/notifications` | JSON unread/read | Notification | — | login |
| search | `/search` | Глобальный поиск | — | search repos | search.use |
| audit | `/audit` | Журнал | AuditLog | — | audit.view, export |
| reports | `/reports` | Отчёты | — | ReportService | reports.view, export |

---

# 6. Database Architecture

- **СУБД:** PostgreSQL 17; schema `POSTGRES_SCHEMA` (default `opora`).
- **ORM soft-delete:** `BaseModel.deleted_at` + `active_filter()` (`app/models/base.py`).
- **Миграции:** линейные `001_initial` … **`035_integrity_indexes`** (единственный head).
- **Тесты** часто используют `db.create_all()` (не полный Alembic path) — drift migrations↔models может не ловиться в CI.

### Карта связей (упрощённо)

```text
User ─┬─ UserRole ─ Role ─┬─ RolePermission ─ Permission ─ SystemModule
      │                   └─ RoleFieldPermission ─ FieldDefinition
      ├─ Position
      ├─ MessengerConversation / MessengerMessage
      ├─ PersonalContract ─ Attachment
      └─ Notification, Comment, LoginLog

WorkObject ─┬─ Project (object_id RESTRICT)
            │    ├─ Request.project_id (SET NULL)
            │    ├─ TenderProject ─ TenderApplication
            │    └─ Contract.project_id
            ├─ TenderApplication.object_id
            └─ ContractObject ─ Contract ─ ContractContractor ─ Contractor

Inquiry · PoleAgreement ─ PoleAgreementSite
EisImportRun ─ EisImportEvent
CustomField ─ CustomFieldValue (EAV entity_type+entity_id)
AuditLog (soft_delete запрещён)
```

Важные unique (после 035 / в моделях): partial unique активных EIS-номеров, EAV values, soft-delete-aware пары junction (`tender_projects`, `contract_objects`, `contract_contractors`).

**Drift (факт):** колонка `requests.assignee_id` осталась в БД после миграции `004` (в модели только `responsible_id`/`executor_id`). Часть unique индексов объявлена в моделях, но не во всех старых миграциях (INN подрядчиков, custom_fields и др.) — на «чистом» migrate path могут отсутствовать.

---

# 7. Database Invariants

```text
INV-DB-001  deleted_at IS NOT NULL = soft-deleted. Обычные списки фильтруют active_filter().
INV-DB-002  Soft-delete НЕ запускает SQL ON DELETE CASCADE. CASCADE только при hard DELETE.
INV-DB-003  CRITICAL: User hard-delete каскадно уничтожит чаты/уведомления — операционно только soft-delete.
INV-DB-004  Request.number уникален (исторически absolute unique — коллизия с soft-deleted номерами возможна).
INV-DB-005  Request.project_id может быть NULL; заявка ≠ объект автоматически.
INV-DB-006  CRITICAL: Project.object_id → WorkObject RESTRICT на hard delete; soft-delete объекта оставляет «живые» проекты, указывающие на удалённый объект.
INV-DB-007  CRITICAL: После soft-delete связи TenderProject/ContractObject повторное связывание должно restore() или partial unique (035) — иначе IntegrityError.
INV-DB-008  WorkObject.status отражает цепочку: free | in_project | in_tender | in_contract | completed | archived.
INV-DB-009  AuditLog нельзя soft-delete (raises).
INV-DB-010  Inquiry IMAP uid unique в рамках mailbox+uidvalidity; soft-deleted письма не должны ломать sync (фильтр deleted_at).
```

---

# 8. Authentication

| Тема | Реализация |
|------|------------|
| Login | `POST /auth/login` → `AuthService.authenticate` (`app/modules/auth/`) |
| Logout | **`POST /auth/logout`** (+ CSRF); GET показывает confirm (`logout_confirm.html`) — не завершает сессию |
| Password | bcrypt rounds=12 (`app/core/security.py`); legacy Werkzeug rehash при входе |
| Session | Flask-Login cookie; HttpOnly; SameSite=Lax; **Secure default False** (LAN) |
| Blocked/inactive | `before_request` → logout (`app/__init__.py`) |
| Создание пользователей | `/employees` + `EmployeeService`; seed `AuthService.create_default_admin` / CLI `seed-admin` |
| CSRF | Flask-WTF глобально; AJAX: заголовок `X-CSRFToken` |
| Open redirect | `next` только относительный `/…` без `//` |

Ключевые файлы: `app/modules/auth/routes.py`, `services.py`, `app/models/auth/user.py`, `app/core/security.py`, `app/extensions.py`.

---

# 9. Authorization / RBAC

```text
User → UserRole → Role → RolePermission → Permission (code = module.action)
                         → RoleFieldPermission (module, field_name, access_level)
```

- **Admin:** `user.is_admin` (роль `admin`) → permission `*` / bypass в `PermissionService`.
- **Module actions** (каталог): view/create/edit/delete + спец. (approve, dispatch, sync, run, …) + **`file_upload`/`file_delete`** в каталоге (`permission_service.MODULE_ACTIONS`) — **на routes обычно не проверяются** (используется `*.edit`).
- **Field levels:** NONE / VIEW / EDIT; `resolve_field()` на create без права edit возвращает `None` (не клиентское значение).
- **Decorators:** `permission_required`, `any_permission_required`, `role_required`, `admin_required` — `app/core/decorators.py`.
- **UI ≠ защита:** кнопка скрыта ≠ сервер разрешил; проверка на route + service.

Роли seed: `admin`, `director`, `dispatcher`, `master`, `executor` (`app/models/auth/constants.py`).

---

# 10. Authorization Rules

```text
RULE-AUTH-001  Не-админ не может назначить роль admin / править / удалять / сбрасывать пароль админа.
               (EmployeeService._assert_privileged_changes — employees/services.py)

RULE-AUTH-002  Permission проверяется на backend (decorator), не только в шаблоне.

RULE-AUTH-003  Field-level нельзя обойти POST’ом: resolve_field / can_edit_field.

RULE-AUTH-004  Личные документы: только владелец (get_own). Мессенджер: ensure_access(conversation, user).

RULE-AUTH-005  Mass wipe объектов по HTTP — только @admin_required (objects/routes.py wipe).

RULE-AUTH-006  Download файлов: путь строго внутри UPLOAD_FOLDER (resolve_storage_path).

RULE-AUTH-007  Скрытие пункта меню ≠ отсутствие права на API того же модуля.

RULE-AUTH-008  roles.manage позволяет собрать почти полный набор прав (кроме частичных ограничений duplicate admin) — учитывать при выдаче права.
```

---

# 11. Request Workflow

Источник истины: `app/modules/requests/workflow.py`.

### Статусы (коды)

| Code | Смысл |
|------|--------|
| `new` | Новая |
| `emergency_dispatched` | Выехала аварийная бригада |
| `accepted_by_master` | Передана мастеру |
| `in_progress` | В работе (опционально) |
| `completed` | Выполнено (final) |
| `cancelled` | Отменена (final) |

### Переходы (`ALLOWED_TRANSITIONS`)

```text
new → emergency_dispatched | accepted_by_master | cancelled
emergency_dispatched → accepted_by_master | cancelled
accepted_by_master → completed | in_progress | cancelled
in_progress → completed | cancelled
completed / cancelled → ∅
```

### Действия × права (`available_actions`)

| Current | Action | Next | Permission |
|---------|--------|------|------------|
| new | Выехала бригада | emergency_dispatched | `requests.dispatch` |
| new | Передать мастеру | accepted_by_master | `requests.dispatch` |
| new | Отменить | cancelled | `requests.dispatch` |
| emergency_dispatched | Передать мастеру | accepted_by_master | `requests.dispatch` |
| emergency_dispatched | Принять на себя | accepted_by_master | `requests.approve` (если нет responsible) |
| emergency_dispatched | Отменить | cancelled | `requests.dispatch` |
| accepted_by_master | Начать работу | in_progress | `requests.approve` |
| accepted_by_master | Выполнено | completed | `requests.approve` или `requests.edit` |
| accepted_by_master | Отменить | cancelled | `requests.dispatch` |
| in_progress | Выполнено | completed | approve/edit |
| in_progress | Отменить | cancelled | dispatch |

Эндпоинты: `/emergency-departed`, assign-master, accept, start-work, complete, cancel — в `requests/routes.py` (с соответствующими `@permission_required` / `any_permission_required`).

**История:** `RequestHistory`. **Материалы:** `RequestMaterial` (не отдельный модуль UI «materials»). **Файлы:** `Attachment` entity_type=request. **project_id:** опциональная связь; workflow заявок **не** создаёт WorkObject/Project.

---

# 12. Request Business Rules

```text
RULE-REQUEST-001  Переход статуса только через can_transition / Allowed transitions — иначе ValidationError.
RULE-REQUEST-002  Действия UI должны совпадать с available_actions (права dispatch/approve/edit).
RULE-REQUEST-003  Финальные completed/cancelled не имеют исходящих переходов.
RULE-REQUEST-004  Soft-deleted заявка не участвует в workflow (available_actions → []).
RULE-REQUEST-005  Номер заявки генерируется сервисом (формат YY-N / natural sort) — не ломать без тестов test_request_*.
RULE-REQUEST-006  Адресные поля/координаты живут на Request; карта — lazy coords (не блокировать list/detail синхронным Nominatim).
RULE-REQUEST-007  Request ≠ Object: автопроект по ТЗ/ЛСР относится к WorkObject, не к заявке.
```

---

# 13. Object → Project → Tender → Contract Chain

```text
WorkObject
  → Project          (авто или вручную)
  → TenderApplication (+ TenderProject M:N)
  → Contract         (+ ContractObject / ContractContractor)
```

### Автосоздание Project

**Триггер-текст (exact):**  
`ObjectService.AUTO_PROJECT_RESULT` =  
«Обследование проведено, ТЗ подготовлено, локально-сметный расчет готов.»  
(`app/modules/objects/services.py` ~28–30)

Также: альтернативные фразы / regex `_RESULT_DRAFT_RE`; цепочки по полям тендера/номера контракта.

**Эффект:** `_ensure_chain_for_result` → `ProjectService.create_project` →  
`WorkObject.status = in_project` (~251–275; также в `projects/services.py` ~292–295).

Тест-защита: `tests/test_object_project_automation.py`.

### Статусы объекта

`free` → `in_project` → `in_tender` → `in_contract` → `completed` / `archived` (`WorkObjectStatus` в `app/models/enums.py`).

Синхронизация при смене статусов тендера/контракта — в `TenderService` / `ContractService` (side effects на project/object).

### Удаление

- Soft-delete проекта **не всегда** сбрасывает статус объекта → риск «залипания» `in_project`.
- Wipe объектов по HTTP: только admin; занятые (`in_project`/`in_tender`/`in_contract`) **пропускаются**.
- Junction re-link: restore soft-deleted rows (`TenderService._sync_project_links`, `ContractService._ensure_object_link`).

---

# 14. Address System

| Компонент | Факт |
|-----------|------|
| Провайдер | Nominatim + heuristic (каталог улиц Кирова) — `app/core/address/` |
| Конфиг | `GEOCODING_*`, `NOMINATIM_*`, viewbox Кировской обл. |
| Request | address, original/normalized, region, district, settlement, street, house, lat/lng, address_source |
| WorkObject | в основном `address` / `name` — **без** lat/lng/district колонок |
| Карта заявки | OSM embed / `request-detail.js`; lazy `GET/POST /requests/<id>/coords` (persist только с `requests.edit`) |
| Карта договоров | Leaflet + `/agreements/map.json` |
| CLI | `flask repair-request-districts` |

Браузер **не** ходит в Nominatim напрямую (серверный прокси suggestions).

---

# 15. File Storage

| | |
|--|--|
| Корень | `UPLOAD_FOLDER` (Docker volume `uploads_data` → `/app/instance/uploads`) |
| Сохранение | `save_upload()` → `{dir}/{uuid}_{secure_name}` (`app/core/upload_utils.py`) |
| Безопасность пути | **`resolve_storage_path()`** — запрет `..`, абсолютных путей, выход за root |
| MIME/size | validate_upload, magic bytes, лимиты `MAX_UPLOAD_*` |
| Модели | Attachment (polymorphic), ProjectDocument, ContractDocument, TenderDocument, PoleAgreement.storage_key, MessengerMessage files |
| Доступ | всегда через permission модуля + ownership/ensure_access где применимо |

---

# 16. Messenger

- Модели: `MessengerConversation` (participant_a/b), `MessengerMessage`, `UserPresence`.
- Permission: `messenger.use`.
- **CRITICAL:** любой API messages/files обязан `MessengerService.ensure_access(conversation_id, user_id)` — нельзя читать чужой чат подменой ID.
- Unread/poll: JS + intervals из config; звук/тосты в `main.js`.
- Файлы: `get_file_path` → `resolve_storage_path`.

Файлы: `app/modules/messenger/{routes,services,repositories}.py`, `static/js/messenger.js`.

---

# 17. Documents

- Личные файлы и personal contracts — `app/modules/documents/`.
- Permission: `documents.use`.
- **CRITICAL:** `PersonalDocumentService.get_own(user_id, file_id)` — чужой ID → 404/запрет.
- Worker `documents-notify` — напоминания по срокам договоров.
- Upload/download/delete только своих вложений.

---

# 18. External Integrations

### Nominatim
- Service: `app/core/address/service.py`, `providers.py`.
- Outbound HTTP + rate limit; timeouts из config.
- Credentials: не требуются; User-Agent обязателен политикой OSM.

### ЕИС / zakupki.gov.ru
- Package: `app/integrations/zakupki/` + `app/modules/eis/`.
- TLS: **verify по умолчанию**; opt-out `EIS_SSL_VERIFY=0` (`client.py`).
- Worker: `flask eis-sync --loop` (часы `EIS_SYNC_HOURS`, TZ Moscow).
- UI run: может поднять daemon thread в web-процессе.
- Годы: `EIS_YEAR_FROM`/`TO` (default 2025–2100).

### IMAP (обращения)
- Config: `INQUIRY_IMAP_*` (пароль только в `.env`, не в git).
- Service: `InquiryService` + `imap_client` / `parse_email`.
- Worker: `flask inquiry-sync --loop` (~120s); advisory lock на Postgres.
- Download вложений не должен блокироваться ожиданием IMAP (restore в worker).

---

# 19. Background Workers

| Worker | Команда | Назначение | Риски |
|--------|---------|------------|-------|
| eis-sync | `flask eis-sync --loop` | Импорт закупок | Сеть/TLS; stale `running`; пул БД |
| inquiry-sync | `flask inquiry-sync --loop` | Почта → Inquiry + files | Credentials; shared uploads volume |
| documents-notify | `flask documents-notify --loop` | Напоминания договоров | — |

Дополнительно: ручной sync EIS/Inquiry и geocode agreements могут использовать **`threading.Thread(daemon=True)` внутри gunicorn** — задача умрёт с worker; предпочитать compose workers.

---

# 20. Frontend Architecture

- Layouts: `templates/layouts/{base,app,spa_shell,auth}.html`.
- SPA: `static/js/main.js` шлёт `X-Opora-Nav: 1` → сервер отдаёт `spa_shell` + `X-Opora-Partial`.
- Списки: `opora-list.js` (AJAX table/pagination).
- CSRF: meta `csrf-token` → `X-CSRFToken`.
- Модалки: `components/crud_modals.html` + module partials.
- Тур обучения: `tour.js` / config `#oporaTourConfig`.
- CSS: `main.css`, module css; Bootstrap Icons vendor.

Переход: click sidebar → fetch HTML partial → replace content → re-init module scripts (не полный reload), кроме тяжёлых разделов (eis/agreements/reports/audit — prefetch skip).

---

# 21. API / AJAX (значимые)

| METHOD | PATH | AUTH | PERM | NOTES |
|--------|------|------|------|-------|
| GET | `/health` | no | — | `{release, …}` |
| POST | `/auth/login` | no | — | session |
| POST | `/auth/logout` | yes | — | CSRF |
| GET | `/requests/table` | yes | requests.view | list AJAX |
| GET/POST | `/requests/<id>/coords` | yes | view; persist→edit | lazy geocode |
| POST | `/objects/wipe` | yes | **admin** | mass soft-delete free objects |
| * | `/messenger/...` | yes | messenger.use | + ensure_access |
| * | `/documents/...` | yes | documents.use | + get_own |
| POST | `/eis/run` | yes | eis.run | background import |
| POST | `/inquiries/sync` | yes | inquiries.sync | background |
| GET | `/notifications/api/...` | yes | login | own notifications |
| GET | `/agreements/map.json` | yes | agreements.view | map points |
| GET | `/search/` | yes | search.use | unified search |

Формат ошибок AJAX: `{success: false, message, html?}` (`app/core/http.py`).

---

# 22. Error Handling

| Тип | Поведение |
|-----|-----------|
| 404/400/413/500/CSRF | `_register_error_handlers` в `app/__init__.py` |
| AJAX | `ajax_error` JSON |
| 500 | log + `db.session.rollback` |
| ValidationError / NotFoundError / AuthenticationError | доменные, flash или JSON |
| Широкий `except Exception` | sync/import/geocode — логировать, не ронять весь worker по возможности |

---

# 23. Testing

```bash
# Windows / local без Postgres:
set USE_SQLITE=1
python -m pytest
# или:
python -m pytest tests/test_security_hardening.py tests/test_request_workflow.py -q
```

- `tests/conftest.py`: testing config, **CSRF off**, temp uploads, seed roles + users (admin/dispatcher/master/executor).
- Критичные тесты: `test_security_hardening.py`, `test_request_workflow.py`, `test_object_project_automation.py`, `test_documents.py`, `test_procurement_chain.py`, `test_eis_import.py`, `test_http_smoke.py`.

---

# 24. Deployment

```text
git fetch/reset origin/main
  → scripts/deploy.sh
  → docker compose build/up
  → entrypoint: wait DB → flask db upgrade → (seed/sync-security)
  → gunicorn wsgi:app
  → nginx :5000
  + eis-sync, inquiry-sync, documents-notify
```

- Volumes: `postgres_data`, `uploads_data` — **не удалять**.
- После деплоя: Ctrl+F5 (static immutable + `?v=RELEASE`).
- Проверка: `GET /health` → `release` == ожидаемый.
- Backup: `scripts/backup-db.sh` / cron helpers.

---

# 25. Environment Variables

(только имена и смысл; **без значений**)

| Variable | Назначение |
|----------|------------|
| `SECRET_KEY` | сессии/подписи (prod: не default) |
| `FLASK_ENV` | development/production/testing |
| `DATABASE_URL` / `POSTGRES_*` / `DB_HOST` | БД |
| `POSTGRES_SCHEMA` | schema (default opora) |
| `USE_SQLITE` | локальный SQLite |
| `SESSION_COOKIE_SECURE` / `REMEMBER_COOKIE_SECURE` | Secure cookies |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` / `ADMIN_FULL_NAME` | seed admin |
| `MAX_UPLOAD_MB` / `MAX_UPLOAD_FILE_MB` / `MAX_UPLOAD_FILES` | лимиты |
| `GEOCODING_*` / `NOMINATIM_*` | адреса |
| `EIS_*` / `EIS_SSL_VERIFY` | импорт ЕИС |
| `INQUIRY_*` | IMAP |
| `MESSENGER_*` | таймауты/poll |
| `WEB_CONCURRENCY` / `GUNICORN_*` | gunicorn |
| `OPORA_RUN_MIGRATE` | migrate в entrypoint |
| `TEST_DATABASE_URL` | pytest Postgres |

См. также `.env.example`.

---

# 26. Git Rules

- Основная ветка: **`main`**.
- Коммиты: тег в квадратных скобках + русский заголовок (см. `.cursor/rules/commits-ru.mdc`): `[фикс]`, `[заявки]`, `[инфра]`, …
- `RELEASE` в `app/release.py` — менять при выкладке статики/значимых фич; синхронно тест `/health` в `tests/test_documents.py` если он pinned.
- **Не коммитить:** `.env`, `instance/`, `*.db`, uploads, секреты, CRLF-шум по всем файлам сразу.
- `deploy.sh` делает `git reset --hard origin/main` — локальные незапушенные коммиты на сервер **не попадут**.

---

# 27. ⚠️ DANGEROUS AREAS

| Место | Почему опасно |
|-------|----------------|
| `app/modules/requests/workflow.py` + seed статусов | Ломает жизненный цикл заявок и права действий |
| `app/modules/requests/services.py` | Номера, адрес, материалы, переходы, история |
| `app/modules/objects/services.py` | Автоцепочка Project/Tender/Contract, статусы объектов |
| `app/modules/projects/services.py` / `tenders/services.py` / `contracts/services.py` | Синхронизация статусов цепочки |
| `app/core/permission_service.py` + `seed/security_catalog.py` | RBAC всей системы |
| `app/modules/employees/services.py` | Эскалация привилегий |
| `app/core/upload_utils.py` | Path traversal / загрузки |
| `migrations/versions/001`–`034` | Уже на production — **не редактировать**; только новые ревизии |
| `app/modules/eis/*` + `integrations/zakupki/*` | Порча закупочных данных |
| `app/modules/inquiries/*` | Почта, вложения, sync locks |
| `docker-compose` volumes | Потеря БД/файлов при неосторожном down -v |

---

# 28. Architectural Invariants

```text
ARCH-001  Сложная бизнес-логика — в services, не в routes/templates/JS.
ARCH-002  Изменение данных — через service + явный commit/rollback.
ARCH-003  Permission нельзя считать выполненным из-за скрытой кнопки UI.
ARCH-004  Не изменять уже применённые Alembic revisions на production.
ARCH-005  Soft-delete + фильтры deleted_at обязательны в списках и связях.
ARCH-006  Новые файлы загрузок — только через save_upload / resolve_storage_path.
ARCH-007  Messenger/Documents — всегда ownership / ensure_access на сервере.
ARCH-008  Cache-bust статики — через RELEASE, не через «вечный» APP_VERSION в .env.
ARCH-009  Не добавлять синхронный длинный Nominatim на list/detail в request path.
ARCH-010  Workers длительных задач — compose sidecars, не полагаться на daemon threads web.
```

---

# 29. Known Technical Debt

| Долг | Приоритет |
|------|-----------|
| Очень большие `requests/services|routes`, `objects/services` | желательно |
| Дублирование CRUD-шаблонов модулей | не срочно |
| Soft-delete vs SQL CASCADE семантика | важно понимать |
| DB drift: `assignee_id`, часть unique только в models | важно |
| `file_upload`/`file_delete` в каталоге без enforce | важно |
| Широкие `except Exception` в sync/import | желательно |
| CSRF выключен в pytest | желательно (отдельные CSRF-on smoke) |
| CRLF noise в working tree на Windows | не срочно |
| Модуль `materials` только в permissions | не срочно |
| Weak CSP (frame-ancestors only) | желательно |

---

# 30. Known Bugs / Security Issues

Только **активные** относительно HEAD `1099d33` (исправленные escalation/wipe/path/logout/TLS/resolve_field **не** числятся открытыми).

| ID | Severity | Problem | Location | Status |
|----|----------|---------|----------|--------|
| SEC-01 | HIGH | `file_upload`/`file_delete` не enforce на routes | catalog vs `*.edit` routes | OPEN |
| SEC-02 | HIGH | `roles.manage` ≈ сбор полного набора прав | `roles/services.py` | OPEN (duplicate admin частично ограничен) |
| SEC-03 | MEDIUM | Нет rate-limit/lockout login | `auth/services.py` | OPEN |
| SEC-04 | MEDIUM | `SESSION_COOKIE_SECURE` default False | `config.py` | OPEN (ок для LAN HTTP) |
| SEC-05 | MEDIUM | Soft-delete Project может не сбросить WorkObject.status | `projects/services.py` | OPEN |
| SEC-06 | MEDIUM | CLI wipe без admin gate | `app/__init__.py` CLI | OPEN (нужен shell) |
| SEC-07 | LOW | Inquiry purge path join без resolve | `inquiries/services.py` | OPEN |
| OPS-01 | HIGH* | `1099d33` / `035` могут быть не на origin/prod | git/deploy | *пока не запушено/не задеплоено |

---

# 31. Current Project State

```text
Git branch:     main
Git HEAD:       1099d33
Release:        20260826h
Alembic head:   035_integrity_indexes
Tests:          PASS (полный suite при генерации контекста — см. последний прогон; команда ниже)
Origin sync:    local may be ahead 1 — VERIFY before deploy
Known active:   SEC-01…SEC-07, OPS-01; DB drift assignee_id / some uniques
```

---

# 32. Safe Development Rules

1. Перед правкой прочитать route → service → model → permissions → tests.
2. Не переписывать модуль целиком «для красоты».
3. Не менять workflow заявок без `test_request_workflow`.
4. Не править migrations `001`–`N` на проде; только новая ревизия.
5. Не менять `security_catalog` / PermissionService без проверки ролей.
6. Не удалять side effects цепочки Object→Project→Tender→Contract без callers.
7. Не считать UI-скрытие защитой.
8. Upload/download только через `upload_utils`.
9. После изменений — targeted pytest + при схеме — migration.
10. Не коммитить `.env` / CRLF-простыни.
11. При смене статики/релизе — bump `RELEASE`.
12. Не добавлять блокирующий внешний HTTP в list handlers.

---

# 33. How to Work on This Project

```text
BEFORE CODING:
1. Найти module в app/modules/<name>/
2. Прочитать routes.py (decorators!)
3. Прочитать services.py
4. Прочитать models + связанные FK
5. Проверить permissions constants
6. Найти tests/test_* связанные
7. Понять side effects (audit, status sync, files)

DURING CODING:
1. Минимальный diff
2. Логика в service
3. Переиспользовать repository/helpers
4. Не обходить PermissionService / ensure_access
5. Soft-delete filters сохранить

AFTER CODING:
1. pytest targeted → при необходимости полный
2. Проверить нужен ли Alembic
3. git diff — без секретов и шума
4. Кратко объяснить why в коммите [тег]
```

---

# 34. AI Change Protocol

**Перед изменением зафиксировать:**

```text
TASK:
AFFECTED MODULES:
AFFECTED FILES:
DATABASE IMPACT: none | migration needed | data backfill
AUTHORIZATION IMPACT: none | decorator | service guard | field-level
BUSINESS LOGIC IMPACT:
SECURITY IMPACT:
TESTS REQUIRED:
MIGRATION REQUIRED: yes/no
RISK: low|medium|high
```

**После:**

```text
CHANGED FILES:
WHAT CHANGED:
TESTS: command + result
RESULT:
KNOWN LIMITATIONS:
```

---

# 35. Current Roadmap

### P0
- Запушить `1099d33` на origin и задеплоить; убедиться `flask db upgrade` → `035`; `/health` = `20260826h`.

### P1
- Enforce или убрать `file_upload`/`file_delete` из UI ролей.
- Ограничить `roles.manage` (cap по правам актора).
- Rate-limit / lockout на login.
- При HTTPS: `SESSION_COOKIE_SECURE=True`.

### P2
- Миграция: drop `requests.assignee_id`; недостающие unique (INN, custom fields…).
- Project delete → корректный сброс статуса объекта.
- CSRF-on smoke tests.

### P3
- Ужесточить CSP; нормализация EOL; рефактор гигантских services по мере нужды; модуль materials или чистка каталога.

---

# 36. Quick Reference

```text
PROJECT: Опора
STACK: Python 3.12 · Flask 3.1 · SQLAlchemy · Alembic · PG17 · Bootstrap 5 · JS · Docker
DATABASE: PostgreSQL schema opora · soft-delete · Alembic head 035_integrity_indexes
AUTH: Flask-Login · bcrypt · CSRF · RBAC + field permissions
MAIN MODULES: requests, objects, projects, tenders, contracts, contractors,
  agreements, inquiries, eis, messenger, documents, employees, roles, …

REQUEST WORKFLOW:
  new → emergency_dispatched → accepted_by_master → [in_progress] → completed
  (+ cancel from non-final); perms: dispatch / approve / edit

PROCUREMENT CHAIN:
  WorkObject → Project → Tender ↔ Project → Contract
  AUTO_PROJECT_RESULT in objects/services.py → status in_project

IMPORTANT FILES:
  app/modules/requests/workflow.py
  app/modules/objects/services.py
  app/core/permission_service.py
  app/core/upload_utils.py
  app/modules/employees/services.py
  app/modules/registry.py
  app/release.py
  migrations/versions/035_integrity_indexes.py

DANGEROUS AREAS:
  workflow · objects chain · RBAC · migrations 001-034 · EIS · IMAP · volumes

TEST COMMAND:
  set USE_SQLITE=1 && python -m pytest

DEPLOY COMMAND:
  cd /opt/opora && sudo bash scripts/deploy.sh
  then Ctrl+F5; check /health

CURRENT HEAD:    1099d33
CURRENT RELEASE: 20260826h
CURRENT ALEMBIC: 035_integrity_indexes

TOP PRIORITIES:
  1) Push+deploy hardening + migration 035
  2) file_* RBAC + roles.manage cap + login rate-limit
  3) DB drift cleanup
```

---

*Конец PROJECT_CONTEXT.md. При существенных изменениях архитектуры/workflow/RBAC — обновлять этот файл в том же PR.*
