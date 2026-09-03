# OPORA Architecture

This document describes the architecture represented by repository HEAD
`71697fd` and Alembic revision `044_object_kind_cable_waybill_status`. Current
code remains the final source of truth.

## System overview

OPORA («Опора») is a corporate municipal information system covering request
dispatch, defects, field work, outdoor-lighting objects, projects, procurement,
contracts, employees, internal communication and reporting.

It is a modular monolith. Flask Blueprints divide the HTTP surface into domain
modules, while the application shares one process, SQLAlchemy model, session,
database and set of cross-cutting services.

## Tech stack

- Python 3.12 and Flask 3.1.0.
- Flask-SQLAlchemy 3.1.1 and Flask-Migrate 4.0.7.
- PostgreSQL 17 in production; SQLite is supported for local work and tests.
- Flask-Login, Flask-WTF, WTForms and bcrypt.
- Server-rendered Jinja, Bootstrap 5 and vanilla JavaScript.
- Leaflet for maps; vendor assets are stored in the repository.
- Gunicorn 23 using `gthread`, behind Nginx.
- Docker Compose for the web, database, proxy and background workers.
- openpyxl, pypdf, PyMuPDF, Tesseract and Pillow for imports and documents.
- pytest and Locust for functional and load testing.

There is no separate frontend build, React/Vue application, Celery, Redis or
WebSocket service.

## Repository structure

```text
app/
  __init__.py           application factory and cross-cutting registration
  config.py             environment configuration
  extensions.py         db, migrate, login and CSRF instances
  core/                 audit, RBAC, uploads, search, addresses, performance
  integrations/         external clients and parsers
  models/               shared SQLAlchemy domain model
  modules/              Flask Blueprint modules
  seed/                 reference data and security catalog
  static/               CSS, JavaScript, Bootstrap and Leaflet
  templates/            shared layouts, components and macros
migrations/versions/    linear Alembic history
tests/                  SQLite/PostgreSQL-compatible pytest suite
docker/                 entrypoint and Nginx configuration
scripts/                deploy, backup, QA and load-test utilities
```

Large CRUD modules normally contain `blueprint.py`, `routes.py`, `services.py`,
`repositories.py`, `forms.py` and `templates/<module>/`. Small modules omit
layers they do not need.

## Application factory

`app.create_app()`:

1. loads a development, production or testing configuration;
2. rejects known default secrets in production;
3. initializes SQLAlchemy, Alembic, Flask-Login and CSRF;
4. configures SQLite pragmas or the PostgreSQL schema;
5. imports all models into migration metadata;
6. registers the Blueprint registry;
7. installs performance, audit, security and SPA hooks;
8. registers error handlers, context processors, filters and CLI commands;
9. ensures the upload directory exists.

`run.py` starts the threaded development server. `wsgi.py` creates a production
application for Gunicorn.

## HTTP flow

```text
Browser
  -> Nginx
     -> /static served directly with gzip and long-lived cache
     -> Gunicorn for application URLs
        -> Flask before-request hooks
        -> Blueprint route and authorization decorator
        -> form validation / service
        -> repository / SQLAlchemy
        -> PostgreSQL
        -> Jinja page, Jinja partial or JSON
        -> browser JavaScript lifecycle
```

Static requests and `/health` deliberately avoid loading the current user from
the database. Other requests enforce inactive/blocked-user checks. Responses
receive security headers and `Server-Timing`; AJAX errors use JSON while normal
requests render or redirect to HTML.

## Module registry

`app/modules/registry.py` registers these Blueprints:

| Blueprint | Prefix | Responsibility |
|---|---|---|
| `main` | none | dashboard, health and about |
| `auth` | `/auth` | login, profile and appearance |
| `requests` | `/requests` | request journals and workflow |
| `defects` | `/defects` | defect register |
| `work_orders` | `/work-orders` | master's queue and WorkPlan UI |
| `waybills` | `/waybills` | route sheets and stops |
| `objects` | `/objects` | address work lots |
| `projects` | `/projects` | projects, members and documents |
| `tenders` | `/tenders` | procurement applications |
| `contracts` | `/contracts` | contracts, objects and documents |
| `contractors` | `/contractors` | contractor organizations |
| `agreements` | `/agreements` | pole agreements and map sites |
| `inquiries` | `/inquiries` | incoming corporate mail |
| `eis` | `/eis` | EIS import and run journal |
| `employees` | `/employees` | user administration |
| `positions` | `/positions` | position reference data |
| `roles` | `/roles` | roles and permission matrix |
| `field_builder` | `/field-builder` | built-in and custom fields |
| `wallpapers` | `/wallpapers` | managed background catalog |
| `messenger` | `/messenger` | chat page and JSON API |
| `documents` | `/documents` | private employee documents |
| `notifications` | `/notifications` | unread/read API |
| `search` | `/search` | global search page and API |
| `audit` | `/audit` | global audit journal |
| `reports` | `/reports` | request/object reports and export |

`app/modules/_template` is a scaffold and is not registered.

## Database model

Most entities inherit `BaseModel`:

- UUID primary key;
- `created_at` and `updated_at`;
- nullable `created_by` and `updated_by` foreign keys to `users`;
- nullable `deleted_at` for soft delete.

Some reference and domain models also use `is_active`. Active lookups must
explicitly use `active_filter()` and, where relevant, `is_active`.

Important relationships:

```text
User --< UserRole >-- Role --< RolePermission >-- Permission
                           `--< RoleFieldPermission >-- FieldDefinition

RequestJournal --< RequestJournalCounter
RequestJournal --< Request >-- RequestStatus
                         |--< RequestHistory
                         |--< RequestMaterial
                         `-- Project

Defect >-- DefectStatus
       >-- DefectCategory
       `--< DefectHistory

WorkPlan --< WorkPlanItem >-- Request or Defect
Waybill  --< WaybillStop  >-- Request or Defect

WorkObject --< Project
WorkObject --< ContractObject >-- Contract
Project --< TenderProject >-- TenderApplication --< Contract
Project --< Contract
Contract --< ContractContractor >-- Contractor

User --< PersonalContract >-- Attachment
EisImportRun --< EisImportEvent
```

Active partial unique indexes protect user email, role/permission codes,
project/contract numbers, contractor INN, EIS identifiers and junction pairs.
Generic attachments use `entity_type + entity_id` rather than a physical FK.

## Auth / RBAC

Flask-Login stores the authenticated user in the session. Passwords use bcrypt;
legacy Werkzeug hashes remain readable during migration. Inactive, blocked or
soft-deleted users cannot continue a session.

Authorization is many-to-many:

```text
User -> UserRole -> Role -> RolePermission -> Permission
```

Permission codes normally have `<module>.<action>` form. Route decorators
perform coarse checks. `PermissionService` also supports field access levels:

- `0`: hidden;
- `1`: view;
- `2`: edit.

When field rules exist, the maximum access from all active roles is used.
`resolve_field()` ignores client-submitted values that the actor cannot edit.
The administrator role has an explicit full-access bypass.

System roles seeded by current code are `admin`, `director`, `dispatcher`,
`master` and `executor`. Seed synchronization adds missing grants but does not
remove grants already present in a database, so production can be broader than
the static seed matrix.

Sidebar filtering is a usability layer only; backend checks remain mandatory.

## Requests

`Request` stores its journal and number, description and applicant data,
structured address metadata, coordinates, district, PP, received time,
dispatcher, priority, due date, barrier details, repeat history, status,
responsible user, executor and optional project.

Current journals are the main request journal and three village journals for
the Oktyabrsky, Novovyatsky and Leninsky districts.

### Request numbering

The visible format is `YY-N`.

- Scope: one `RequestJournal`.
- Time scope: one calendar year.
- State: `RequestJournalCounter(journal_id, year, last_value)`.
- Integrity: `(journal_id, number)` is unique.

The same visible number can therefore exist in two different journals.
Repository sorting parses the year and sequence numerically rather than sorting
the string lexically.

Request lists support text/number/date, journal, district, PP, status,
priority, dispatcher, responsible/executor and preset filters. Pagination and
sorting are server-side.

Stored status codes are `new`, `emergency_dispatched`, `accepted_by_master`,
`in_progress`, `completed` and `cancelled`. The current visible lifecycle is
simplified toward completing an open request, while older dispatch/accept/start
endpoints remain for compatibility.

Marking a repeated request updates `repeat_count` and the JSON list
`repeat_dates`; it does not create a second Request. Materials, comments,
attachments, request history and global audit are separate records.

## Defects

Defects are a separate Blueprint and table, with number, address, PP, district,
coordinates, description, priority, category, status and responsible user.
Status and category are reference tables; transitions create DefectHistory.
Files use generic Attachment records.

Defects do not have their own sidebar item. The sidebar's «Заявки» item covers
both the Requests and Defects endpoints, and the request-area UI presents the
defect register as a related tab/page.

## Work Orders / WorkPlan

`/work-orders` is the master's combined queue of requests and defects. It can
filter by preset, journal, open state, date, PP, district and responsible user.
It exposes compact entity cards, attachments and completion operations.

The newer planning model is:

```text
WorkPlan(master, work_date, status)
  -> WorkPlanItem(request_id XOR defect_id, order, snapshots, result)
  -> WorkPlanHistory
```

A master creates or resumes a draft, adds work, uses related-work suggestions,
saves the plan, completes or excludes individual items and then completes the
plan. Related work is grouped by normalized PP, exact address and district.
Snapshots preserve the plan's original address, PP, district and display data
even if the source record later changes.

## Waybills

The older planning model remains active:

```text
Waybill(master, work_date, status)
  -> WaybillStop(request_id XOR defect_id, order, snapshots)
  -> WaybillMember
  -> WaybillHistory
```

Waybill routes provide CRUD, status changes, stop add/remove/reorder, nearby and
map data. Parts of `/work-orders/plan/*` still operate on a current-day Waybill.
WorkPlan and Waybill therefore currently overlap and must not be casually
merged or removed.

## Objects

`WorkObject` is an address work lot, not an individual physical pole. It stores
name, work type, plan section, optional comment, address, plan year, deadline,
budget, court decision, result text, legacy contract summary and status.

Object kinds are `planned`, `court`, `tech_connect` and `other`. The `other`
kind uses `kind_comment`.

The create form includes a default-enabled checkbox to create a draft Project.
Independently, `ObjectService` interprets imported/result text and can
idempotently ensure a Project, Tender and Contract. An object has direct
Projects and many Contracts through `ContractObject`.

## Projects

Project fields include code, name, description, status, dates, progress,
manager, members, object and planned/factual volumes for SIP cable, other
cable, poles, lights and SHUNO/cabinets. Lengths are meters; equipment values
are counts. For a technical-connection object, the cabinet label changes from
SHUNO to cabinets.

Projects relate to requests, contracts, tenders, history, generic attachments,
custom fields and formal ProjectDocuments. A ProjectDocument has a type, title,
number, date, description and optional file; it is richer than an attachment.

## Tenders

`TenderApplication` represents a procurement package. It can have a primary
object, multiple projects through `TenderProject`, documents, responsible user,
deadline, publication date, NMCK and EIS metadata. Status codes are `draft`,
`submitted`, `won`, `lost` and `cancelled`.

Winning or imported tenders can lead to contracts. Project and object statuses
are synchronized by domain services.

## Contracts

A Contract stores type, unique active number, title, description, amount,
currency, dates, workflow status, responsible user and EIS metadata. It may
point directly to one Project and Tender, while also relating to multiple
WorkObjects and Contractors through junction tables.

`contractor_name` is retained as a denormalized/legacy display field alongside
normalized Contractor links. ContractDocument stores formal document metadata
and an optional file. ContractHistory and global audit serve different UI and
administrative purposes.

## Contractors

Contractor represents a legal organization with name, INN, KPP, address and
contact data. Active non-empty INN is unique. EIS uses INN as the primary
idempotency key and maintains ContractContractor links.

## EIS

The source is zakupki.gov.ru and must not be replaced without a dedicated task.

```text
zakupki.gov.ru
  -> throttled/retried urllib HTTP client
  -> paginated search/result pages
  -> HTML parser
  -> EisOrder / EisContract / EisSupplier DTOs
  -> object matching
  -> Project / Tender / Contract / Contractor synchronization
  -> EisImportRun and EisImportEvent journal
```

Matching derives normalized address, settlements, street tokens, house and
distinctive tokens. A conflicting known house number prevents unsafe fuzzy
matching.

- matched: best score at least `0.82`, normally with a `0.08` lead;
- ambiguous: score at least `0.70` but candidates are too close;
- unmatched: no safe candidate.

Ambiguous and unmatched items are journaled and not auto-linked.

Fill-only applies to manually maintained business fields: missing number,
title, description, dates, amount, delivery place, links and object contract
summary may be filled, while populated values are generally preserved. EIS
identifiers and source metadata remain EIS-owned. Status mapping may update a
record; internal busy contract states are preserved unless EIS explicitly
reports completion or termination.

Idempotency relies on tender registration number, contract registry number,
contractor INN, existing object/project chain and active unique relation pairs.

Run statuses are `running`, `success`, `partial` and `failed`. Fetch errors,
parse errors, partial cards, unmatched or ambiguous items produce `partial`.
Stale running jobs are failed after the configured timeout. The sidecar
scheduler uses `EIS_SYNC_HOURS` and `EIS_SYNC_TIMEZONE`.

## Files / Documents

Generic Attachment records hold uploader, entity type/id, safe filename,
relative storage key, MIME, size and optional checksum. ProjectDocument and
ContractDocument are formal domain records with their own metadata and file
reference. Messenger stores file metadata directly on MessengerMessage.

`upload_utils.py` permits configured image, PDF, office, archive and text
formats. It checks extension, claimed MIME, available magic bytes, empty files,
per-file size and request size. `save_upload()` writes a UUID-prefixed file
below `UPLOAD_FOLDER`. `resolve_storage_path()` rejects absolute paths, `..`,
`~` and paths escaping the upload root.

Personal documents are always scoped to their owner. PersonalContract can
extract metadata and expiry from PDF, DOCX, DOC/RTF or text, using Tesseract for
scanned PDFs. A sidecar creates reminders one month and two weeks before expiry.

Soft deletion normally leaves the physical file for recovery; orphan cleanup
is not automatic.

## Address system

Request address helpers canonicalize local addresses to forms such as
`Киров, улица Лепсе, дом 79` and create a lower-cased normalized comparison key.
A local street catalog handles fast suggestions and common spelling errors.

The server-side Nominatim provider adds structured region, district,
settlement, street, house, coordinates and external ID. It uses a required
User-Agent, timeout, bounded Kirov-region viewbox, 1 MB response limit,
thread-safe TTL/LRU cache and a cross-thread start-rate limiter. Signed tokens
protect the selected suggestion passed back from a form.

The district layer normalizes OSM names and local aliases to Leninsky,
Oktyabrsky, Pervomaysky or Novovyatsky.

## Maps

Leaflet is bundled locally. Maps are used by defects, work orders, waybills,
pole agreements and some request-related endpoints. `ops-map.js` is shared by
the work queue and route pages. Nearby ranking uses, in order of usefulness,
PP, geographic distance, exact address and district.

A Leaflet container must have no second live map instance. SPA page teardown or
idempotent boot logic must prevent duplicate initialization.

## Search

`/search/` renders results and `/search/api` powers the top bar. Search covers
requests, defects, projects, contracts, objects, waybills, users, addresses,
numbers, custom fields and entities related to matched employees.

PostgreSQL uses stored `tsvector`, generated tsquery and rank expressions.
SQLite and some fallbacks use case-insensitive LIKE. Keyboard-layout variants
are searched. Each result group is filtered by the actor's module permission.

## Messenger

A conversation is a unique normalized pair of users. Messages store body,
read state, reply relation, optional file metadata and optional immutable card
snapshot. UserPresence stores the latest heartbeat.

All conversation/message/file routes call participant access checks. The UI
uses short HTTP polling for heartbeat, conversation state, messages and unread
count. `/api/events` exists only to state that SSE is disabled. There is no
WebSocket transport. New-message feedback includes badge, toast, sound and an
optional browser notification.

## Audit

AuditLog records actor, action, entity type/id, description, old/new JSON, IP,
User-Agent, endpoint and HTTP method. Domain services create rich audit entries;
an after-request hook records selected successful modifying endpoints when the
service did not already mark the action as audited.

Entity histories such as RequestHistory, DefectHistory, ProjectHistory,
ContractHistory, WaybillHistory and WorkPlanHistory are card-oriented business
timelines. AuditLog is the cross-system administrative journal. Preserve both
when a workflow currently uses both.

## Dashboard / Themes

DashboardService calculates permission-aware counts and recent records for
requests, projects and contracts. Attention items include critical requests,
requests awaiting a master, projects without contracts and contracts ending
within 30 days. Quick actions are permission-filtered.

The UI supports light and dark themes, orange accent colors, shared card/table
styles and optional backgrounds. Theme selection runs in `<head>` to prevent a
flash of the wrong theme. Backgrounds can come from the managed Wallpaper
catalog, bundled Kirov photographs or a user's private upload.

Primary stylesheets are `main.css`, `dashboard.css`, `requests-journal.css`,
`work-desk.css`, `work-plans.css`, `messenger.css`, `search.css` and `tour.css`.

## SPA navigation lifecycle

The persistent app shell intercepts eligible same-origin links. It excludes
authentication, messenger, downloads, exports and file URLs. It requests a
partial with `X-Opora-Nav: 1`, synchronizes page assets, replaces `#appContent`,
updates browser history and dispatches `opora:navigated`.

`DOMContentLoaded` fires only when the full app shell loads. It does not fire
again after partial navigation. Page JavaScript must use this pattern:

```js
function boot() {
    const root = document.querySelector(...);
    if (!root || root.dataset.bound === "1") return;

    root.dataset.bound = "1";

    // initialization
}

document.addEventListener("DOMContentLoaded", boot);
window.addEventListener("opora:navigated", boot);
```

The bound marker belongs to the replaceable page root, not the permanent body.
If a feature installs global listeners or external instances, it must also
remove or safely reuse them. Do not fix lifecycle bugs with `location.reload()`.

## Docker / Production

```text
Browser -> Nginx -> Gunicorn -> Flask -> PostgreSQL 17
```

Nginx is the only published service. It serves `/static` directly with gzip
and a 30-day immutable cache, then proxies application requests to Gunicorn.
Gunicorn defaults to three workers with eight gthread threads each.

Sidecars use the same application image and database:

- `eis-sync` runs the EIS loop;
- `inquiry-sync` polls IMAP and stores attachments;
- `documents-notify` creates personal-contract expiry notifications.

Named volumes are `postgres_data` and `uploads_data`. They must never be removed
during an ordinary update.

The web entrypoint waits for PostgreSQL, runs `flask db upgrade`, runs
`flask sync-security` and starts Gunicorn. Initial reference/admin seed is
optional and controlled by `OPORA_SEED_ON_START`.

## Deploy

The expected operational chain is:

```text
local development -> GitHub origin/main -> Linux self-hosted runner -> server
```

GitHub `deploy.yml` triggers on pushes to `main`. `scripts/deploy.sh` fetches
origin, resets the server checkout to `origin/main`, builds images, recreates
web and workers, waits for healthchecks and runs the address-district repair
command. Migration and permission synchronization happen inside the web
entrypoint.

Deployment is destructive to uncommitted changes in the server checkout and
may make rate-limited OSM calls during district repair. Never invoke it unless
the user explicitly asks to update the server.

## Migrations

Alembic history is linear. Major stages are base schema and seeds (`001-003`),
requests/projects/contracts (`004-006`), messenger/search/audit/RBAC/custom
fields (`007-012`), request workflow and address metadata (`013-017`, `022-023`),
procurement and object fields (`018-021`, `024-026`), pole agreements and
inquiries (`027-031`), personal documents and EIS integrity (`032-035`), UI
preferences (`036-037`), request journals (`038`), defects (`039`), waybills
(`041`), WorkPlan (`043`) and current object/cable/status additions (`044`).

Revision `040` introduced a direct Request-Defect relation and `042` removed
it. The current model intentionally has no direct request-defect junction.

Never edit revisions `001-044`. Add a new revision for any schema change and
test it against PostgreSQL as well as SQLite where supported.

## Tests

The repository contains roughly 229 pytest tests. CI runs the suite against
SQLite and PostgreSQL 17, then runs Ruff checks for syntax and undefined names.

Strong areas include address handling, EIS parsing/import, request journals,
object/project automation, project documents, agreements, work orders,
security hardening, dashboard, search and list performance. Thinner areas
include Nearby behavior, reports, contract workflow breadth, notifications and
full messenger UX. CSRF is disabled by the shared test fixture. Browser-level
tests for partial navigation and Leaflet lifecycle are absent.

## Performance considerations

- Nginx serves compressed static files without consuming Gunicorn threads.
- Static URLs use the release value for cache busting.
- PostgreSQL uses FTS and list-specific indexes; SQLite uses slower LIKE
  fallbacks.
- Several list searches still contain `%term%` patterns and can full-scan.
- Large relationships default to lazy select; list repositories must select
  only needed columns or explicitly eager-load template dependencies.
- Work Orders combines and serializes two large entity sets.
- Messenger short polling creates load proportional to active tabs.
- Nominatim, EIS, IMAP, OCR and office conversion are blocking operations.
- The opt-in profiler records request duration, query count and DB time without
  logging SQL parameter values. Every non-static request receives
  `Server-Timing`.

## Security considerations

- Backend decorators and service ownership checks are mandatory.
- `roles.manage` is highly privileged and should not be broadly granted.
- File upload/delete permissions are not equally granular in all modules.
- Login currently has no application-level rate limit or lockout policy.
- Secure cookie defaults are false for LAN HTTP and must be enabled for HTTPS.
- CSP is intentionally minimal because templates contain inline scripts.
- Upload validation is not malware scanning.
- Generic attachment integrity is enforced in services, not by a domain FK.
- Soft-deleted physical files remain on disk until a separate cleanup policy is
  introduced.
- Do not expose `.env`, database URLs, credentials or mailbox secrets.

## Known technical debt

- WorkPlan and Waybill overlap.
- Legacy Request workflow routes remain beside the simplified current flow.
- Requests, Objects and Work Orders contain large route/service files.
- Some older JavaScript listens only to `DOMContentLoaded`.
- There is no browser lifecycle test suite.
- File permissions are not uniformly granular.
- Generic attachments and formal project/contract documents overlap.
- Soft delete and physical SQL cascade provide two deletion semantics.
- Background work is implemented as polling sidecars rather than a durable job
  queue.
- `PROJECT_CONTEXT.md` is an obsolete snapshot.

## Important invariants

1. Preserve soft-delete filters.
2. Preserve backend RBAC and field-level access.
3. Preserve entity history and global audit behavior.
4. Keep request numbers journal-scoped and counters journal/year-scoped.
5. Keep EIS fill-only and idempotent.
6. Do not auto-link ambiguous EIS matches.
7. Keep Object -> Project -> Tender -> Contract automation idempotent.
8. Use safe upload and storage path helpers.
9. Scope personal files by owner and messenger data by participant.
10. Initialize partial pages through `opora:navigated` with idempotent boot.
11. Do not double-initialize Leaflet.
12. Keep long-running loops outside Gunicorn.
13. Add migrations; never rewrite published revisions.
14. Keep named production volumes during updates.
15. Use `RELEASE` for deployed static cache invalidation.

## File index

| Area | Start with |
|---|---|
| App lifecycle | `app/__init__.py`, `app/config.py`, `app/modules/registry.py` |
| Requests | `app/modules/requests/`, `app/models/requests/` |
| Defects | `app/modules/defects/`, `app/models/defects/` |
| Work queue/plans | `app/modules/work_orders/`, `app/models/work_plans/` |
| Waybills | `app/modules/waybills/`, `app/models/waybills/` |
| Objects | `app/modules/objects/`, `app/models/work_objects/` |
| Projects | `app/modules/projects/`, `app/models/projects/` |
| Tenders | `app/modules/tenders/`, `app/models/tenders/` |
| Contracts | `app/modules/contracts/`, `app/models/contracts/` |
| EIS | `app/integrations/zakupki/`, `app/modules/eis/` |
| RBAC | `app/core/permission_service.py`, `app/models/auth/`, `app/seed/` |
| Audit | `app/core/audit_service.py`, `app/core/audit_hooks.py` |
| Uploads | `app/core/upload_utils.py`, `app/models/files/attachment.py` |
| Addresses/maps | `app/core/address/`, `app/core/nearby.py`, `app/static/js/ops-map.js` |
| Search | `app/core/search.py`, `app/modules/search/` |
| Messenger | `app/modules/messenger/`, `app/models/messenger/` |
| SPA shell | `app/static/js/main.js`, `app/templates/layouts/` |
| Themes | `app/static/css/`, `app/static/js/theme.js`, `appearance.js` |
| Production | `docker-compose.yml`, `Dockerfile`, `docker/`, `scripts/deploy.sh` |
| Migrations | `migrations/versions/` |
| Tests | `tests/`, `.github/workflows/ci.yml` |

