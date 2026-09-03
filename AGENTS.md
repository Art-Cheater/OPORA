# Руководство для AI-агентов проекта «Опора»

## Проект

«Опора» — корпоративная информационная система муниципального предприятия для
заявок, дефектов, выездных работ, объектов освещения, закупок, контрактов,
сотрудников и внутренних коммуникаций.

- Backend: Python 3.12, Flask 3.1, SQLAlchemy, Flask-Migrate/Alembic.
- Production-база: PostgreSQL 17, обычно в схеме `opora`; локально — SQLite.
- Frontend: серверный Jinja, Bootstrap 5, vanilla JavaScript и Leaflet.
- Навигация заменяет содержимое страницы подобно SPA; это не React/Vue.
- Production: Nginx -> Gunicorn (`gthread`) -> Flask -> PostgreSQL и sidecars.
- Архитектура: модульный монолит с общей ORM и базой данных.

Источник истины — текущий код. Перед изменением функции прочитайте её route,
service, repository, model, permissions и tests. Полная карта находится в
`docs/ARCHITECTURE.md`.

## Критические правила

1. Не переписывать приложение с нуля и не менять архитектуру без необходимости.
2. Предпочитать небольшой diff, согласованный с окружающим модулем.
3. При противоречии README, комментариев или `PROJECT_CONTEXT.md` верить коду.
4. Не редактировать опубликованные Alembic migrations `001–044`.
5. Изменения БД оформлять новой migration после
   `044_object_kind_cable_waybill_status`.
6. Учитывать soft delete: применять `deleted_at` и при наличии `is_active`.
7. Скрытая кнопка не заменяет авторизацию. RBAC проверять в routes/services.
8. Учитывать field-level permissions и не доверять запрещённым полям из POST.
9. При изменении состояния сохранять глобальный audit и entity history.
10. Request number уникален внутри RequestJournal. Counter разделён по журналу
    и календарному году.
11. EIS заполняет пустые business fields по принципу fill-only. Не затирать
    вручную заполненные значения, если поле явно не принадлежит EIS.
12. Сохранять идемпотентность EIS по регистрационным номерам, INN Contractor и
    уникальности активных связей.
13. Не связывать автоматически `ambiguous` или слабый EIS address match.
14. Сохранять идемпотентность Object -> Project -> Tender -> Contract.
15. Upload сохранять через `save_upload()`, path — через
    `resolve_storage_path()`.
16. Сохранять ownership checks документов и participant checks Messenger.
17. SPA page должна запускаться по `DOMContentLoaded` и `opora:navigated`.
18. Page initializer должен быть идемпотентным: отмечать root как bound либо
    удалять старые handlers.
19. Не инициализировать Leaflet повторно на том же container.
20. Не применять `location.reload()` или F5 как исправление SPA lifecycle.
21. Долгие sync loops держать в Compose sidecars, а не внутри Gunicorn.
22. Не добавлять blocking Nominatim calls в list/detail request path.
23. Не записывать secrets, `.env`, production credentials и персональные данные
    в код, логи, tests или документацию.
24. Никогда не выполнять `docker compose down -v` и не разрушать production
    volumes с БД и uploads.
25. Не делать `git push --force`.
26. Не трогать сервер и не выполнять deploy без отдельного указания.
27. При production-изменении статики обновлять `app/release.py`, если нужен
    новый cache key.

## Рабочий процесс Git

```text
LOCAL -> GitHub origin/main -> SERVER
```

Перед работой:

```bash
git status
git branch --show-current
git remote -v
```

Сохранять посторонние изменения пользователя; не сбрасывать и не форматировать
их. Если пользователь запросил доставку через Git, после реализации:

```text
релевантные tests -> полный pytest при возможности -> git diff -> commit
-> git push origin main
```

Сервер пользователь обновляет отдельно, если deploy прямо не запрошен.

## Быстрые ссылки по архитектуре

### Requests

- `app/modules/requests/{routes,services,repositories,forms,workflow,journals}.py`
- `app/models/requests/`
- `app/static/js/{requests,requests-form,requests-journal,request-detail}.js`
- `tests/test_request_*.py`, `tests/test_requests_journals.py`

### Defects

- `app/modules/defects/`, `app/models/defects/`, `tests/test_defects.py`

### Work Orders / WorkPlan

- `app/modules/work_orders/{routes,services,plan_service}.py`
- `app/models/work_plans/`
- `app/static/js/{work-orders,work-plan-new,work-plan-detail,ops-map}.js`
- `tests/test_work_orders.py`, `tests/test_nearby.py`

### Waybills

- `app/modules/waybills/`, `app/models/waybills/`, `tests/test_waybills.py`

### Objects

- `app/modules/objects/`, `app/models/work_objects/`
- `tests/test_object_project_automation.py`, `tests/test_objects_report.py`

### Projects

- `app/modules/projects/`, `app/models/projects/`
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
- `app/models/auth/`, `app/modules/{roles,employees,field_builder}/`
- `app/seed/{security_catalog,reference_data}.py`
- `tests/test_roles.py`, `tests/test_security_hardening.py`

### SPA и оболочка UI

- `app/static/js/main.js`, `app/templates/layouts/`
- `app/templates/components/{sidebar,topbar}.html`
- page-specific JavaScript/CSS, `tests/test_list_shell.py`

### Deploy

- `Dockerfile`, `docker-compose.yml`, `docker/`
- `scripts/deploy.sh`, `.github/workflows/`, `docs/SERVER_SETUP.md`

## Тестирование

- До правки найти существующие tests затрагиваемого модуля.
- До и после рискованного изменения запускать точечные tests.
- После изменений schema, RBAC, workflow или инфраструктуры запускать
  `pytest -q`.
- Schema-sensitive изменения проверять на PostgreSQL и SQLite.
- Не ослаблять tests только ради результата green.
- Не делать commit с очевидно сломанным функционалом.
- В общей pytest fixture CSRF отключён; это не соответствует production.
- Frontend lifecycle вручную проверять при полной загрузке и внутреннем переходе:
  browser tests пока отсутствуют.

## Известный технический долг

- WorkPlan и Waybill частично дублируют планирование и завершение работ.
- Устаревшие Request workflow endpoints остаются рядом с упрощённым UX.
- Часть старых JavaScript initializers слушает только `DOMContentLoaded`.
- File permissions не везде одинаково детальны; ряд routes использует `edit`.
- Нет browser tests для partial navigation и Leaflet lifecycle.
- Некоторые routes/services велики, особенно Requests, Objects и Work Orders.
- `PROJECT_CONTEXT.md` — устаревший снимок, а не актуальная документация.
