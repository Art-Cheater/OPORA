# Архитектура проекта «Опора»

Документ описывает репозиторий на commit `71697fd` и Alembic revision
`044_object_kind_cable_waybill_status`. Окончательный источник истины — текущий
код.

## Обзор системы

«Опора» — корпоративная система муниципального предприятия для заявок,
дефектов, выездных работ, объектов освещения, проектов, закупок, контрактов,
сотрудников, коммуникаций и отчётности. Это модульный Flask-монолит с общей ORM,
SQLAlchemy session и базой данных.

## Технологический стек

- Python 3.12, Flask 3.1.0, Flask-SQLAlchemy 3.1.1.
- Flask-Migrate 4.0.7/Alembic; PostgreSQL 17, локально также SQLite.
- Flask-Login, Flask-WTF, WTForms, bcrypt.
- Jinja, Bootstrap 5, vanilla JavaScript, Leaflet.
- Gunicorn 23 (`gthread`), Nginx и Docker Compose.
- openpyxl, pypdf, PyMuPDF, Tesseract, Pillow; pytest и Locust.

React/Vue, Celery, Redis, WebSocket и отдельного frontend build нет.

## Структура репозитория

```text
app/__init__.py        фабрика и сквозные hooks
app/config.py          конфигурация окружений
app/core/              RBAC, audit, uploads, search, addresses, performance
app/models/            общие SQLAlchemy models
app/modules/           Flask Blueprint modules
app/integrations/      внешние clients/parsers
app/seed/              справочники и security catalog
app/templates/         layouts, components, macros
app/static/            CSS, JavaScript и vendor assets
migrations/versions/   история Alembic
tests/                 pytest suite
docker/, scripts/      production и эксплуатация
```

Большой CRUD-модуль обычно имеет `blueprint.py`, `routes.py`, `services.py`,
`repositories.py`, `forms.py` и `templates/`. Небольшие модули опускают
ненужные слои.

## Фабрика приложения

`create_app()` загружает configuration, проверяет production secrets,
инициализирует SQLAlchemy/Alembic/LoginManager/CSRF, настраивает БД, импортирует
models, регистрирует Blueprint, performance/audit/security/SPA hooks, error
handlers, context processors, filters и CLI commands. `run.py` — development
entrypoint, `wsgi.py` — production entrypoint Gunicorn.

## HTTP-поток

```text
Browser -> Nginx -> Gunicorn -> Flask hooks -> route -> service
        -> repository -> SQLAlchemy -> PostgreSQL -> HTML/partial/JSON -> JS
```

Nginx отдаёт `/static` напрямую. Static requests и `/health` не загружают user
из БД. Для остальных проверяются blocked/inactive users. Ответы получают
security headers и `Server-Timing`; AJAX errors возвращаются как JSON.

## Реестр модулей

| Blueprint | Prefix | Назначение |
|---|---|---|
| `main` | — | dashboard, health, about |
| `auth` | `/auth` | login, profile, внешний вид |
| `requests` | `/requests` | журналы и workflow заявок |
| `defects` | `/defects` | дефекты |
| `work_orders` | `/work-orders` | очередь мастера и WorkPlan |
| `waybills` | `/waybills` | путевые листы |
| `objects` | `/objects` | адресные объекты |
| `projects` | `/projects` | проекты и документы |
| `tenders` | `/tenders` | заявки на торги |
| `contracts` | `/contracts` | контракты |
| `contractors` | `/contractors` | подрядчики |
| `agreements` | `/agreements` | договоры на опоры |
| `inquiries` | `/inquiries` | корпоративная почта |
| `eis` | `/eis` | импорт EIS |
| `employees` | `/employees` | users |
| `positions` | `/positions` | должности |
| `roles` | `/roles` | роли и permissions |
| `field_builder` | `/field-builder` | built-in/custom fields |
| `wallpapers` | `/wallpapers` | каталог фонов |
| `messenger` | `/messenger` | чаты и API |
| `documents` | `/documents` | личные документы |
| `notifications` | `/notifications` | уведомления |
| `search` | `/search` | поиск |
| `audit` | `/audit` | журнал действий |
| `reports` | `/reports` | отчёты/export |

`app/modules/_template` в registry не включён.

## Архитектура базы данных

`BaseModel` задаёт UUID PK, `created_at`, `updated_at`, nullable FK
`created_by`/`updated_by` и `deleted_at`. Часть models имеет `is_active`.
Выборки обязаны учитывать soft delete.

```text
User --< UserRole >-- Role --< RolePermission >-- Permission
                           `--< RoleFieldPermission >-- FieldDefinition
RequestJournal --< RequestJournalCounter
RequestJournal --< Request >-- RequestStatus --< RequestHistory
Defect >-- DefectStatus/DefectCategory --< DefectHistory
WorkPlan --< WorkPlanItem >-- Request или Defect
Waybill --< WaybillStop >-- Request или Defect
WorkObject --< Project --< Contract
WorkObject --< ContractObject >-- Contract
Project --< TenderProject >-- TenderApplication --< Contract
Contract --< ContractContractor >-- Contractor
User --< PersonalContract >-- Attachment
EisImportRun --< EisImportEvent
```

Partial unique indexes защищают active email/codes/numbers, Contractor INN,
EIS identifiers и junction pairs. Attachment использует
`entity_type + entity_id`, а не domain FK.

## Авторизация и RBAC

Связь прав: `User -> UserRole -> Role -> RolePermission -> Permission`.
Permission codes имеют вид `<module>.<action>`. Field access levels: `0` — нет,
`1` — просмотр, `2` — редактирование. `resolve_field()` игнорирует запрещённые
POST values. Admin имеет full-access bypass.

Роли: `admin`, `director`, `dispatcher`, `master`, `executor`. Seed добавляет
grants, но не снимает существующие, поэтому production matrix может отличаться.
Sidebar filtering не заменяет backend decorators/service checks.

## Заявки

Request хранит journal/number, заявителя, structured address, coordinates,
district, PP, received time, dispatcher, priority, due date, barrier data,
repeats, status, responsible/executor и Project.

### Нумерация заявок

Формат — `YY-N`. Scope — один RequestJournal и календарный год. Состояние хранит
`RequestJournalCounter(journal_id, year, last_value)`, уникальна пара
`(journal_id, number)`. Одинаковый видимый number допустим в разных journals.

Статусы: `new`, `emergency_dispatched`, `accepted_by_master`, `in_progress`,
`completed`, `cancelled`. Текущий UX упрощён, но старые workflow endpoints
сохранены. Repeat обновляет `repeat_count`/`repeat_dates`. Filters, sorting и
pagination серверные; history, materials, comments и attachments разделены.

## Дефекты

Defect — отдельные Blueprint/table с number, address, PP, district, coordinates,
description, priority, category, status и responsible. Переходы создают
DefectHistory. В sidebar отдельного пункта нет: Defects входят в раздел
«Заявки» как связанная вкладка/страница.

## Работа по заявкам / WorkPlan

`/work-orders` объединяет очередь Request и Defect. Поддерживаются filters,
карточки, attachments, завершение и related/nearby suggestions.

```text
WorkPlan(master, work_date, status)
  -> WorkPlanItem(request_id XOR defect_id, order, snapshots, result)
  -> WorkPlanHistory
```

Мастер создаёт draft, добавляет работы, сохраняет план, завершает или исключает
items и завершает WorkPlan. Related works группируются по PP, точному адресу и
району. Snapshot сохраняет данные пункта при изменении source entity.

## Путевые листы

```text
Waybill(master, work_date, status)
  -> WaybillStop(request_id XOR defect_id, order, snapshots)
  -> WaybillMember / WaybillHistory
```

Routes поддерживают CRUD, status, add/remove/reorder, nearby и map. Часть
`/work-orders/plan/*` использует Waybill. Этот механизм пересекается с WorkPlan.

## Объекты

WorkObject — адресный лот, не отдельная опора. Виды: `planned`, `court`,
`tech_connect`, `other`; для `other` есть `kind_comment`. Create form содержит
включённый checkbox создания draft Project. `ObjectService` также идемпотентно
строит Project/Tender/Contract из result/import data. Contracts связаны через
`ContractObject`.

## Проекты

Project содержит code, status, dates, progress, manager, members, WorkObject и
plan/fact volumes СИП, кабеля, опор, светильников, ШУНО/шкафов. Есть Requests,
Contracts, Tenders, ProjectHistory, Attachment, custom fields и ProjectDocument
с type/title/number/date/description/file.

## Торги

TenderApplication объединяет WorkObject, Projects через TenderProject,
documents, responsible, deadline, NMCK и EIS metadata. Enum values: `draft`,
`submitted`, `won`, `lost`, `cancelled`. Domain services синхронизируют statuses
Project и WorkObject и могут создать Contract.

## Контракты

Contract хранит type, unique active number, amount, currency, dates, status,
responsible и EIS metadata. Возможны `project_id`, `tender_application_id`,
несколько WorkObject через ContractObject и Contractor через ContractContractor.
ContractDocument содержит формальные metadata; ContractHistory и AuditLog имеют
разные назначения.

## Подрядчики

Contractor хранит name, INN, KPP, address и contacts. Active non-empty INN
уникален и служит ключом идемпотентности EIS.

## Интеграция с ЕИС

Источник — zakupki.gov.ru; не менять без отдельной задачи.

```text
zakupki.gov.ru -> HTTP client -> pagination -> HTML parser
-> EisOrder/EisContract/EisSupplier -> matching -> domain sync
-> EisImportRun/EisImportEvent
```

Matching учитывает normalized address, settlement, street tokens, house и
distinctive tokens. `matched`: score >= `0.82` и обычно gap >= `0.08`;
`ambiguous`: score >= `0.70`, но candidates близки; иначе `unmatched`.
`ambiguous`/`unmatched` не связываются автоматически.

Fill-only дополняет пустые business fields, сохраняя вручную заполненные. EIS
identifiers/source metadata принадлежат EIS; status mapping может обновлять
status. Идемпотентность опирается на registration numbers, Contractor INN,
существующую chain и unique pairs. Run statuses: `running`, `success`, `partial`,
`failed`. Scheduler использует `EIS_SYNC_HOURS`/`EIS_SYNC_TIMEZONE`.

## Файлы и документы

Attachment хранит uploader, entity type/id, filename, storage key, MIME, size и
checksum. ProjectDocument/ContractDocument — формальные domain records;
MessengerMessage хранит file metadata сам.

`save_upload()` проверяет extension/MIME/magic bytes/size и пишет UUID-prefixed
file внутри `UPLOAD_FOLDER`. `resolve_storage_path()` запрещает absolute path,
`..`, `~` и выход за root. Personal documents ограничены owner; PersonalContract
поддерживает PDF/DOCX/DOC/RTF/text и OCR. Soft delete обычно не удаляет physical
file.

## Адресная система

Helpers канонизируют адрес (`Киров, улица …, дом …`). Local street catalog даёт
suggestions. Server-side Nominatim добавляет structured fields/coordinates и
использует `User-Agent`, timeout, viewbox, limit 1 MB, TTL/LRU cache и rate
limiter. Signed token защищает выбранную suggestion. District aliases сводятся
к четырём официальным районам.

## Карты

Leaflet используется в Defects, Work Orders, Waybills и Agreements.
`ops-map.js` общий для очереди и маршрута. Nearby учитывает PP, distance, exact
address и district. Нельзя оставлять две Leaflet instances на одном container.

## Поиск

`/search/` и `/search/api` ищут Requests, Defects, Projects, Contracts, Objects,
Waybills, Users, addresses, numbers и custom fields. PostgreSQL использует
`tsvector`/rank, SQLite — LIKE fallback. Результаты фильтруются по permissions.

## Мессенджер

Conversation — unique pair users; Message хранит body/read/reply/file/card,
UserPresence — heartbeat. Routes проверяют participant access. Реальный
transport — short HTTP polling; SSE отключён, WebSocket отсутствует. UI
обновляет badge и показывает toast/sound/browser notification.

## Аудит

AuditLog хранит actor, action, entity type/id, description, old/new JSON, IP,
`User-Agent`, endpoint и HTTP method. Services создают содержательные records,
after-request hook — резервные записи. Entity histories — timeline карточки,
AuditLog — общий административный журнал; при наличии сохранять оба.

## Главная страница и темы

DashboardService строит permission-aware KPI, attention blocks, recent records
и quick actions. UI имеет light/dark themes, orange accent и backgrounds из
Wallpaper catalog, фотографий Кирова или user upload. Theme применяется в
`<head>`. Основные CSS: `main.css`, `dashboard.css`, `requests-journal.css`,
`work-desk.css`, `work-plans.css`, `messenger.css`, `search.css`, `tour.css`.

## SPA-навигация

App shell отправляет `X-Opora-Nav: 1`, загружает partial, синхронизирует assets,
заменяет `#appContent`, обновляет history и отправляет `opora:navigated`.
`DOMContentLoaded` срабатывает только при полной загрузке shell.

```js
function boot() {
    const root = document.querySelector(...);
    if (!root || root.dataset.bound === "1") return;

    root.dataset.bound = "1";

    // инициализация
}

document.addEventListener("DOMContentLoaded", boot);
window.addEventListener("opora:navigated", boot);
```

Marker принадлежит заменяемому root. Global handlers/instances нужно очищать
или переиспользовать. Не исправлять lifecycle через `location.reload()`.

## Docker и production

```text
Browser -> Nginx -> Gunicorn -> Flask -> PostgreSQL 17
```

Nginx отдаёт static с gzip/cache и проксирует application requests. Gunicorn:
3 workers × 8 `gthread` threads по умолчанию. Sidecars: `eis-sync`,
`inquiry-sync`, `documents-notify`. Named volumes: `postgres_data`,
`uploads_data`; удалять их нельзя. Web entrypoint выполняет `flask db upgrade`,
`flask sync-security`, затем запускает Gunicorn.

## Деплой

```text
LOCAL -> GitHub origin/main -> Linux self-hosted runner -> SERVER
```

`deploy.yml` запускается при push в `main`. `scripts/deploy.sh` сбрасывает server
checkout к `origin/main`, собирает images, пересоздаёт services, ждёт
healthchecks и запускает repair районов. Deploy не запускать без прямого
указания: он уничтожает uncommitted server changes.

## Миграции

Alembic history линейна. Основные этапы: base/RBAC (`001–003`), основные CRM
модули (`004–006`), Messenger/Search/Audit/custom fields (`007–012`), Request
workflow (`013–017`, `022–023`), procurement (`018–026`), Agreements/Inquiries
(`027–031`), Documents/EIS integrity (`032–035`), UI (`036–037`), RequestJournal
`038`, Defect `039`, Waybill `041`, WorkPlan `043`, текущие additions `044`.
`040` добавила Request-Defect junction, `042` его удалила. `001–044` не менять.

## Тесты

Около 229 pytest tests; CI запускает SQLite, PostgreSQL 17 и Ruff. Хорошо
покрыты addresses, EIS, RequestJournal, object/project automation, documents,
Work Orders, security, dashboard/search. Слабее — Nearby, reports, Contract
workflow, notifications и Messenger UX. CSRF в общей fixture отключён. Browser
tests SPA/Leaflet отсутствуют.

## Производительность

- Nginx разгружает Gunicorn от static; используется cache-bust.
- PostgreSQL использует FTS/indexes, SQLite — LIKE fallback.
- `%term%` может давать full scan; lazy relationships — N+1 без eager loading.
- Work Orders объединяет два набора сущностей; Messenger polling зависит от tabs.
- Nominatim, EIS, IMAP, OCR и office conversion блокирующие.
- Profiler считает duration/query count/DB time без SQL parameters.

## Безопасность

- Backend RBAC/ownership checks обязательны; `roles.manage` высокопривилегирован.
- File permissions не везде одинаково детальны.
- Login не имеет application-level rate limit/lockout.
- Secure cookies нужно включать при HTTPS; CSP минимальна из-за inline scripts.
- Upload validation не является malware scanning.
- Generic Attachment integrity обеспечивают services, не domain FK.
- Не раскрывать `.env`, database URL, credentials и mailbox secrets.

## Технический долг

- WorkPlan и Waybill пересекаются; старые Request workflow routes сохранены.
- Requests/Objects/Work Orders имеют крупные routes/services.
- Часть JavaScript слушает только `DOMContentLoaded`; browser tests отсутствуют.
- File permissions не унифицированы; Attachment и formal documents пересекаются.
- Soft delete и SQL cascade задают две семантики удаления.
- Background work использует polling sidecars, а не durable queue.
- `PROJECT_CONTEXT.md` — устаревший снимок.

## Критические инварианты

1. Сохранять soft-delete filters, backend RBAC и field-level access.
2. Сохранять entity history и global audit.
3. Request number остаётся journal-scoped, counter — journal/year-scoped.
4. EIS остаётся fill-only, идемпотентным и не связывает `ambiguous` match.
5. Object -> Project -> Tender -> Contract остаётся идемпотентной chain.
6. Использовать upload/path helpers и ownership/participant checks.
7. SPA pages запускать через `opora:navigated` идемпотентным `boot()`.
8. Не инициализировать Leaflet дважды; длительные loops держать вне Gunicorn.
9. Добавлять migrations, не переписывать `001–044`.
10. Сохранять production volumes и использовать `RELEASE` для static cache.

## Индекс файлов

| Область | Начать с |
|---|---|
| Application lifecycle | `app/__init__.py`, `app/config.py`, `app/modules/registry.py` |
| Requests/Defects | `app/modules/requests/`, `app/modules/defects/`, соответствующие models |
| WorkPlan/Waybill | `app/modules/work_orders/`, `app/modules/waybills/`, соответствующие models |
| Objects/Projects | `app/modules/objects/`, `app/modules/projects/` |
| Tenders/Contracts | `app/modules/tenders/`, `app/modules/contracts/` |
| EIS | `app/integrations/zakupki/`, `app/modules/eis/` |
| RBAC | `app/core/permission_service.py`, `app/models/auth/`, `app/seed/` |
| Audit/uploads | `app/core/audit_service.py`, `app/core/upload_utils.py` |
| Addresses/maps | `app/core/address/`, `app/core/nearby.py`, `app/static/js/ops-map.js` |
| Search/Messenger | `app/modules/search/`, `app/modules/messenger/` |
| SPA/themes | `app/static/js/main.js`, `app/templates/layouts/`, `app/static/css/` |
| Production | `docker-compose.yml`, `Dockerfile`, `docker/`, `scripts/deploy.sh` |
| Migrations/tests | `migrations/versions/`, `tests/`, `.github/workflows/ci.yml` |
