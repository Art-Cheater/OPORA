# OPORA agent guide

## Project

OPORA («Опора») is a corporate municipal information system for requests,
defects, field work, lighting objects, procurement, contracts, employees and
internal communication.

- Backend: Python 3.12, Flask 3.1, SQLAlchemy, Flask-Migrate/Alembic.
- Production database: PostgreSQL 17, normally in schema `opora`.
- Local and test fallback: SQLite.
- Frontend: server-rendered Jinja and Bootstrap 5 with vanilla JavaScript and
  Leaflet. Internal navigation replaces the application content like a small
  SPA; this is not a React/Vue application.
- Deployment: Nginx -> Gunicorn (`gthread`) -> Flask -> PostgreSQL, plus
  background worker containers.
- Architecture: a modular monolith. Blueprints separate HTTP modules, but all
  modules share one application, ORM model and database transaction boundary.

The current code is the source of truth. Read the relevant route, service,
repository, model, permissions and tests before changing a feature. See
`docs/ARCHITECTURE.md` for the persistent architecture map.

## Critical rules

1. Do not rewrite the application from scratch or introduce a new architecture
   unless the task requires it.
2. Prefer a small change consistent with the surrounding module.
3. Do not treat README, old comments or `PROJECT_CONTEXT.md` as more
   authoritative than current code.
4. Never edit already published Alembic migrations `001` through `044`.
5. Database changes require a new migration after
   `044_object_kind_cable_waybill_status`.
6. Most domain records use soft delete. Every list, lookup and relationship
   must deliberately account for `deleted_at` and, where applicable,
   `is_active`.
7. UI visibility is not authorization. Enforce RBAC in routes and services.
8. Preserve field-level permissions. Do not accept a forbidden field merely
   because a client submitted it; use the existing field permission helpers.
9. Preserve global audit records and entity history when changing state.
10. Request numbers are unique inside a request journal, not globally.
    Numbering uses a separate counter per journal and calendar year.
11. EIS import follows fill-only behavior for manually maintained business
    fields. Do not overwrite populated values unless the current code
    explicitly treats the field as EIS-owned.
12. Preserve EIS idempotency based on EIS registration numbers, contractor INN
    and active relation uniqueness.
13. Never auto-link an ambiguous or weak EIS address match.
14. Preserve the idempotent Object -> Project -> Tender -> Contract chain.
15. Store uploads through `save_upload()` and resolve paths through
    `resolve_storage_path()`.
16. Preserve ownership checks for personal documents and participant checks for
    messenger conversations and files.
17. A page loaded through partial navigation must initialize on both
    `DOMContentLoaded` and `opora:navigated`.
18. Page initializers must be idempotent. Mark the current root as bound or
    otherwise clean up handlers before binding again.
19. Never initialize Leaflet twice on the same container. Dispose or reuse the
    prior map when a page is replaced.
20. Do not use `location.reload()` or forced F5 as a fix for SPA lifecycle
    defects.
21. Do not put long-running sync loops in a Gunicorn process. Use the existing
    Compose sidecars.
22. Do not add blocking Nominatim calls to list or detail request paths.
23. Do not expose secrets, `.env` contents, production credentials or personal
    data in source, logs, tests or documentation.
24. Never run `docker compose down -v` for this project. Production database and
    uploads are stored in named volumes.
25. Do not destructively operate on production volumes.
26. Do not run `git push --force`.
27. Do not access or deploy to the server without a separate explicit request.
28. Bump `app/release.py` when a deployed static change needs a new cache key.

## Git workflow

The operational flow is:

```text
LOCAL -> GitHub origin/main -> SERVER
```

Before work, inspect:

```bash
git status
git branch --show-current
git remote -v
```

Preserve unrelated user changes. Do not reset or reformat them.

After implementation, when the user requested delivery through Git:

```text
relevant tests -> full pytest when practical -> git diff -> commit
-> git push origin main
```

The user updates the server separately unless deployment was explicitly
requested.

## Architecture shortcuts

### Requests

- `app/modules/requests/{routes,services,repositories,forms,workflow,journals}.py`
- `app/models/requests/`
- `app/static/js/{requests,requests-form,requests-journal,request-detail}.js`
- `tests/test_request_*.py`, `tests/test_requests_journals.py`

### Defects

- `app/modules/defects/`
- `app/models/defects/`
- `tests/test_defects.py`

### Work Orders / WorkPlan

- `app/modules/work_orders/{routes,services,plan_service}.py`
- `app/models/work_plans/`
- `app/static/js/{work-orders,work-plan-new,work-plan-detail,ops-map}.js`
- `tests/test_work_orders.py`, `tests/test_nearby.py`

### Waybills

- `app/modules/waybills/`
- `app/models/waybills/`
- `tests/test_waybills.py`

### Objects

- `app/modules/objects/`
- `app/models/work_objects/`
- `tests/test_object_project_automation.py`, `tests/test_objects_report.py`

### Projects

- `app/modules/projects/`
- `app/models/projects/`
- `app/static/js/projects-documents.js`
- `tests/test_project_documents.py`, `tests/test_procurement_chain.py`

### Contracts

- `app/modules/contracts/`, `app/modules/contractors/`
- `app/models/contracts/`, `app/models/contractors/`
- `tests/test_contracts.py`, `tests/test_contract_documents.py`

### EIS

- `app/integrations/zakupki/`
- `app/modules/eis/{services,matching,scheduler,routes}.py`
- `tests/test_eis_import.py`, `tests/test_zakupki_parser.py`

### RBAC

- `app/core/{permission_service,decorators,field_permissions}.py`
- `app/models/auth/`
- `app/modules/{roles,employees,field_builder}/`
- `app/seed/{security_catalog,reference_data}.py`
- `tests/test_roles.py`, `tests/test_security_hardening.py`

### SPA and UI shell

- `app/static/js/main.js`
- `app/templates/layouts/{base,app,spa_shell}.html`
- `app/templates/components/{sidebar,topbar}.html`
- page-specific JavaScript and CSS
- `tests/test_list_shell.py`

### Deploy

- `Dockerfile`, `docker-compose.yml`, `docker/`
- `scripts/deploy.sh`
- `.github/workflows/`
- `docs/SERVER_SETUP.md`

## Testing

- Find existing tests for the affected module before editing it.
- Run focused tests before and after a risky change when the environment is
  ready.
- Run the full `pytest -q` suite after cross-cutting, schema, RBAC, workflow or
  infrastructure changes.
- Schema-sensitive changes should be checked on PostgreSQL as well as SQLite.
- Do not weaken, delete or rewrite a test merely to obtain a green result.
- Do not commit obviously broken behavior.
- CSRF is disabled in the common pytest fixture; do not mistake this for
  production behavior.
- For frontend lifecycle changes, manually verify both a full page load and an
  in-app navigation because browser-level coverage is currently absent.

## Known technical debt

- `WorkPlan` and `Waybill` partially duplicate planning and completion logic.
- Legacy Request workflow endpoints remain beside the simplified current UX.
- Some older JavaScript initializers still depend only on `DOMContentLoaded`.
- File permissions are not equally granular in every module; several file
  routes use the module's general `edit` permission.
- There are no browser tests for partial-navigation lifecycle and Leaflet
  teardown/reinitialization.
- Several routes and services are large, particularly Requests, Objects and
  Work Orders.
- `PROJECT_CONTEXT.md` is a legacy snapshot and is not current architecture
  documentation.

