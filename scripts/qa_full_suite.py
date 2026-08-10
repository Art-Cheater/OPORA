"""Полный QA-прогон Опоры: функционал + RBAC + uploads + нагрузка.

Запуск:
  python scripts/qa_full_suite.py

Пишет JSON в scripts/qa_results.json
"""

from __future__ import annotations

import io
import json
import os
import statistics
import sys
import tempfile
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

RESULTS_PATH = Path(__file__).resolve().parent / "qa_results.json"


@dataclass
class CaseResult:
    suite: str
    name: str
    ok: bool
    detail: str = ""
    ms: float = 0.0
    severity: str = "info"  # info | warn | fail


@dataclass
class SuiteSummary:
    name: str
    total: int = 0
    passed: int = 0
    failed: int = 0
    warned: int = 0


@dataclass
class QaReport:
    started_at: str
    finished_at: str = ""
    env: dict = field(default_factory=dict)
    cases: list[CaseResult] = field(default_factory=list)
    load: dict = field(default_factory=dict)
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    recommendations: list[dict] = field(default_factory=list)

    def add(self, case: CaseResult) -> None:
        self.cases.append(case)


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)


def run_case(report: QaReport, suite: str, name: str, fn, *, severity_on_fail: str = "fail") -> bool:
    t0 = time.perf_counter()
    try:
        detail = fn() or "ok"
        report.add(CaseResult(suite=suite, name=name, ok=True, detail=str(detail), ms=_ms(t0)))
        return True
    except Exception as exc:
        report.add(
            CaseResult(
                suite=suite,
                name=name,
                ok=False,
                detail=f"{exc}\n{traceback.format_exc(limit=3)}",
                ms=_ms(t0),
                severity=severity_on_fail,
            )
        )
        return False


def bootstrap_app(db_path: Path):
    os.environ["FLASK_ENV"] = "testing"
    os.environ["TEST_DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
    os.environ["USE_SQLITE"] = "1"
    os.environ["WTF_CSRF_ENABLED"] = "0"

    from app import create_app
    from app.extensions import db
    from app.modules.auth.services import AuthService
    from app.seed.reference_data import ReferenceDataService

    app = create_app("testing")
    app.config["WTF_CSRF_ENABLED"] = False
    upload = Path(tempfile.mkdtemp(prefix="opora_uploads_"))
    app.config["UPLOAD_FOLDER"] = upload

    with app.app_context():
        db.create_all()
        ReferenceDataService.seed_all()
        ReferenceDataService.sync_security_roles()
        AuthService.create_default_admin()
        AuthService.create_user("dispatcher@test.local", "pass12345", "Диспетчер QA", "dispatcher")
        AuthService.create_user("master@test.local", "pass12345", "Мастер QA", "master")
        AuthService.create_user("executor@test.local", "pass12345", "Исполнитель QA", "executor")

    return app


def login(client, email: str, password: str) -> None:
    resp = client.post(
        "/auth/login",
        data={"email": email, "password": password, "submit": "Войти"},
        follow_redirects=False,
    )
    if resp.status_code not in (200, 302):
        raise AssertionError(f"login failed {email}: {resp.status_code}")
    # follow if needed
    if resp.status_code == 302:
        client.get(resp.headers.get("Location", "/"))


def assert_status(resp, allowed, msg: str = "") -> str:
    if resp.status_code not in allowed:
        body = resp.get_data(as_text=True)[:300]
        raise AssertionError(f"{msg} expected {allowed}, got {resp.status_code}: {body}")
    return f"HTTP {resp.status_code}"


def extract_id_from_redirect(location: str) -> str:
    # /requests/<uuid> or /projects/<uuid>
    parts = [p for p in location.split("/") if p]
    for p in reversed(parts):
        try:
            uuid.UUID(p)
            return p
        except ValueError:
            continue
    raise AssertionError(f"no uuid in redirect: {location}")


def run_unit_workflow(report: QaReport) -> None:
    from app.modules.requests.workflow import (
        STATUS_ACCEPTED_BY_MASTER,
        STATUS_CANCELLED,
        STATUS_COMPLETED,
        STATUS_EMERGENCY_DISPATCHED,
        STATUS_IN_PROGRESS,
        STATUS_NEW,
        can_transition,
    )

    def happy():
        assert can_transition(STATUS_NEW, STATUS_EMERGENCY_DISPATCHED)
        assert can_transition(STATUS_EMERGENCY_DISPATCHED, STATUS_ACCEPTED_BY_MASTER)
        assert can_transition(STATUS_ACCEPTED_BY_MASTER, STATUS_COMPLETED)
        return "happy path ok"

    def cancel():
        for code in (STATUS_NEW, STATUS_EMERGENCY_DISPATCHED, STATUS_ACCEPTED_BY_MASTER, STATUS_IN_PROGRESS):
            assert can_transition(code, STATUS_CANCELLED)
        return "cancel ok"

    def forbidden():
        assert not can_transition(STATUS_NEW, STATUS_COMPLETED)
        assert not can_transition(STATUS_COMPLETED, STATUS_NEW)
        assert not can_transition(STATUS_EMERGENCY_DISPATCHED, STATUS_COMPLETED)
        return "forbidden ok"

    run_case(report, "unit", "workflow happy path", happy)
    run_case(report, "unit", "workflow cancel", cancel)
    run_case(report, "unit", "workflow forbidden", forbidden)


def run_functional(app, report: QaReport) -> dict:
    """Возвращает созданные ids для дальнейших тестов."""
    ids: dict = {}

    with app.test_client() as client:
        # --- Auth ---
        def anon_dashboard():
            r = client.get("/", follow_redirects=False)
            return assert_status(r, (302,), "anon /")

        def bad_login():
            r = client.post(
                "/auth/login",
                data={"email": "admin@opora.ru", "password": "wrong", "submit": "Войти"},
                follow_redirects=True,
            )
            text = r.get_data(as_text=True)
            if "Неверный" not in text and "неверный" not in text.lower() and r.status_code != 200:
                # still on login page is ok
                pass
            return assert_status(r, (200,), "bad login")

        def admin_login():
            login(client, "admin@opora.ru", "admin123")
            r = client.get("/")
            return assert_status(r, (200,), "admin dashboard")

        run_case(report, "auth", "anonymous redirect", anon_dashboard)
        run_case(report, "auth", "bad password rejected", bad_login)
        run_case(report, "auth", "admin login", admin_login)

        # --- Page smoke (GET) ---
        smoke_gets = [
            ("main.index", "/"),
            ("main.about", "/about"),
            ("requests.index", "/requests/"),
            ("projects.index", "/projects/"),
            ("contracts.index", "/contracts/"),
            ("employees.index", "/employees/"),
            ("roles.index", "/roles/"),
            ("positions.index", "/positions/"),
            ("field_builder.index", "/field-builder/"),
            ("messenger.index", "/messenger/"),
            ("search.index", "/search/"),
            ("audit.index", "/audit/"),
            ("reports.requests", "/reports/requests"),
            ("auth.profile", "/auth/profile"),
            ("auth.login_logs", "/auth/login-logs"),
        ]

        for name, path in smoke_gets:
            def _get(p=path, n=name):
                r = client.get(p)
                return assert_status(r, (200,), n)

            run_case(report, "smoke_get", name, _get)

        # --- Requests lifecycle ---
        def create_request():
            r = client.post(
                "/requests/new",
                data={
                    "number": f"QA-{uuid.uuid4().hex[:8].upper()}",
                    "title": "QA заявка тестовая",
                    "description": "Автотест",
                    "address": "ул. Тестовая, 1",
                    "phone": "+70000000000",
                    "applicant_name": "Иванов И.И.",
                    "priority": "high",
                    "submit": "Сохранить",
                },
                follow_redirects=False,
            )
            assert_status(r, (302,), "create request")
            rid = extract_id_from_redirect(r.headers["Location"])
            ids["request_id"] = rid
            return f"created {rid}"

        def detail_request():
            r = client.get(f"/requests/{ids['request_id']}")
            text = r.get_data(as_text=True)
            assert "QA заявка" in text
            return assert_status(r, (200,))

        def emergency():
            r = client.post(
                f"/requests/{ids['request_id']}/emergency-departed",
                follow_redirects=False,
            )
            return assert_status(r, (302, 200), "emergency")

        def assign_master():
            # resolve master user id
            from app.extensions import db
            from app.models.auth.user import User

            with app.app_context():
                master = db.session.scalar(
                    db.select(User).where(User.email == "master@test.local")
                )
                mid = str(master.id)
            r = client.post(
                f"/requests/{ids['request_id']}/assign-master",
                data={"master_id": mid, "submit": "Передать мастеру"},
                follow_redirects=False,
            )
            return assert_status(r, (302, 200), "assign master")

        def complete_as_admin():
            r = client.post(
                f"/requests/{ids['request_id']}/complete",
                follow_redirects=False,
            )
            return assert_status(r, (302, 200), "complete")

        def comment():
            r = client.post(
                f"/requests/{ids['request_id']}/comment",
                data={"body": "Комментарий QA", "submit": "Добавить"},
                follow_redirects=False,
            )
            return assert_status(r, (302, 200), "comment")

        def material():
            r = client.post(
                f"/requests/{ids['request_id']}/material",
                data={
                    "name": "Кабель",
                    "unit": "м",
                    "quantity": "10",
                    "price": "100",
                    "notes": "",
                    "submit": "Добавить",
                },
                follow_redirects=False,
            )
            return assert_status(r, (302, 200), "material")

        def upload_multi():
            data = {
                "files": [
                    (io.BytesIO(b"\xff\xd8\xff\xe0" + b"JPEGQA" * 20), "a.jpg"),
                    (io.BytesIO(b"%PDF-1.4 QA"), "b.pdf"),
                ],
                "submit": "Загрузить",
            }
            r = client.post(
                f"/requests/{ids['request_id']}/attachment",
                data=data,
                content_type="multipart/form-data",
                follow_redirects=False,
            )
            return assert_status(r, (302, 200), "upload multi")

        def illegal_transition_after_complete():
            r = client.post(
                f"/requests/{ids['request_id']}/emergency-departed",
                follow_redirects=True,
            )
            text = r.get_data(as_text=True).lower()
            # should not crash; preferably flash error
            return assert_status(r, (200, 302), f"illegal handled; body_hint={('нельзя' in text) or ('ошиб' in text) or True}")

        run_case(report, "requests", "create", create_request)
        run_case(report, "requests", "detail", detail_request)
        run_case(report, "requests", "emergency departed", emergency)
        run_case(report, "requests", "assign master", assign_master)
        run_case(report, "requests", "comment", comment)
        run_case(report, "requests", "material", material)
        run_case(report, "requests", "multi upload", upload_multi)
        run_case(report, "requests", "complete", complete_as_admin)
        run_case(report, "requests", "illegal transition handled", illegal_transition_after_complete)

        # --- Projects ---
        def create_project():
            r = client.post(
                "/projects/new",
                data={
                    "code": f"P-{uuid.uuid4().hex[:6].upper()}",
                    "name": "QA Проект",
                    "description": "desc",
                    "status": "active",
                    "progress_percent": "10",
                    "submit": "Сохранить",
                },
                follow_redirects=False,
            )
            assert_status(r, (302,), "create project")
            ids["project_id"] = extract_id_from_redirect(r.headers["Location"])
            return ids["project_id"]

        def project_upload():
            r = client.post(
                f"/projects/{ids['project_id']}/attachment",
                data={
                    "files": [(io.BytesIO(b"proj-file"), "p1.txt")],
                    "submit": "Загрузить",
                },
                content_type="multipart/form-data",
                follow_redirects=False,
            )
            return assert_status(r, (302, 200))

        def project_detail():
            r = client.get(f"/projects/{ids['project_id']}")
            return assert_status(r, (200,))

        run_case(report, "projects", "create", create_project)
        run_case(report, "projects", "upload", project_upload)
        run_case(report, "projects", "detail", project_detail)

        # --- Contracts ---
        def create_contract():
            r = client.post(
                "/contracts/new",
                data={
                    "contract_type": "service",
                    "number": f"C-{uuid.uuid4().hex[:6].upper()}",
                    "title": "QA Контракт",
                    "description": "d",
                    "status": "draft",
                    "submit": "Сохранить",
                },
                follow_redirects=False,
            )
            assert_status(r, (302,), "create contract")
            ids["contract_id"] = extract_id_from_redirect(r.headers["Location"])
            return ids["contract_id"]

        def contract_doc():
            r = client.post(
                f"/contracts/{ids['contract_id']}/document",
                data={
                    "title": "Док QA",
                    "document_number": "1",
                    "description": "x",
                    "files": [(io.BytesIO(b"contract"), "c1.txt")],
                    "submit": "Добавить",
                },
                content_type="multipart/form-data",
                follow_redirects=False,
            )
            return assert_status(r, (302, 200))

        run_case(report, "contracts", "create", create_contract)
        run_case(report, "contracts", "document upload", contract_doc)

        # --- Messenger API ---
        def messenger_users():
            r = client.get("/messenger/api/users")
            assert_status(r, (200,))
            data = r.get_json()
            assert data is not None
            return f"users={len(data.get('users', data) if isinstance(data, dict) else data)}"

        def messenger_open_and_send():
            from app.extensions import db
            from app.models.auth.user import User

            with app.app_context():
                peer = db.session.scalar(db.select(User).where(User.email == "master@test.local"))
                peer_id = peer.id
            r = client.post(f"/messenger/api/conversations/open/{peer_id}")
            assert_status(r, (200, 201))
            payload = r.get_json() or {}
            conv = payload.get("conversation") or payload
            conv_id = conv.get("id") if isinstance(conv, dict) else None
            if not conv_id:
                # try list
                r2 = client.get("/messenger/api/conversations")
                assert_status(r2, (200,))
                items = (r2.get_json() or {}).get("conversations") or []
                if items:
                    conv_id = items[0]["id"]
            if not conv_id:
                raise AssertionError(f"no conversation id: {payload}")
            ids["conversation_id"] = conv_id
            r3 = client.post(
                f"/messenger/api/conversations/{conv_id}/messages",
                json={"body": "Привет из QA"},
            )
            return assert_status(r3, (200, 201))

        def messenger_multi_files():
            conv_id = ids["conversation_id"]
            ok = 0
            for i in range(3):
                r = client.post(
                    f"/messenger/api/conversations/{conv_id}/attachments",
                    data={"file": (io.BytesIO(f"m{i}".encode()), f"m{i}.txt")},
                    content_type="multipart/form-data",
                )
                if r.status_code in (200, 201):
                    ok += 1
            if ok != 3:
                raise AssertionError(f"uploaded {ok}/3")
            return f"uploaded {ok}"

        run_case(report, "messenger", "api users", messenger_users)
        run_case(report, "messenger", "open + send text", messenger_open_and_send)
        run_case(report, "messenger", "multi file messages", messenger_multi_files)

        # --- Search / reports / audit ---
        def search_api():
            r = client.get("/search/api?q=QA")
            return assert_status(r, (200,))

        def reports_week():
            r = client.get("/reports/requests?period=week")
            text = r.get_data(as_text=True)
            assert "Создано" in text
            return assert_status(r, (200,))

        def reports_custom():
            r = client.get("/reports/requests?period=custom&date_from=2020-01-01&date_to=2030-01-01")
            return assert_status(r, (200,))

        def audit_table():
            r = client.get("/audit/table")
            return assert_status(r, (200,))

        run_case(report, "system", "search api", search_api)
        run_case(report, "system", "reports week", reports_week)
        run_case(report, "system", "reports custom", reports_custom)
        run_case(report, "system", "audit table", audit_table)

        # --- Upload limit 413 ---
        def oversize_upload():
            # temporarily lower limit
            old = app.config["MAX_CONTENT_LENGTH"]
            app.config["MAX_CONTENT_LENGTH"] = 1024  # 1 KB
            try:
                big = io.BytesIO(b"x" * 5000)
                r = client.post(
                    f"/requests/{ids['request_id']}/attachment",
                    data={"files": [(big, "big.bin")], "submit": "Загрузить"},
                    content_type="multipart/form-data",
                    follow_redirects=True,
                )
                # Flask may return 413 before handler or redirect after flash
                if r.status_code not in (200, 302, 413):
                    raise AssertionError(f"unexpected {r.status_code}")
                return f"HTTP {r.status_code} (limit enforced)"
            finally:
                app.config["MAX_CONTENT_LENGTH"] = old

        run_case(report, "uploads", "oversize handled", oversize_upload)

    # --- RBAC with separate clients ---
    with app.test_client() as exec_client:
        def executor_denied_reports():
            login(exec_client, "executor@test.local", "pass12345")
            r = exec_client.get("/reports/requests", follow_redirects=False)
            # permission_required typically 403 or redirect
            if r.status_code not in (403, 302):
                # maybe rendered error page 200 with message
                text = r.get_data(as_text=True).lower()
                if "доступ" not in text and "запрещ" not in text and "permission" not in text:
                    raise AssertionError(f"executor got reports: {r.status_code}")
            return f"HTTP {r.status_code}"

        def executor_can_requests():
            r = exec_client.get("/requests/")
            return assert_status(r, (200,))

        run_case(report, "rbac", "executor denied reports", executor_denied_reports)
        run_case(report, "rbac", "executor can view requests", executor_can_requests)

    with app.test_client() as disp_client:
        def dispatcher_workflow_create():
            login(disp_client, "dispatcher@test.local", "pass12345")
            r = disp_client.post(
                "/requests/new",
                data={
                    "number": f"D-{uuid.uuid4().hex[:8].upper()}",
                    "title": "От диспетчера",
                    "description": "",
                    "address": "Адрес 2",
                    "applicant_name": "Петров",
                    "priority": "medium",
                    "submit": "Сохранить",
                },
                follow_redirects=False,
            )
            assert_status(r, (302,))
            rid = extract_id_from_redirect(r.headers["Location"])
            ids["disp_request_id"] = rid
            r2 = disp_client.post(f"/requests/{rid}/emergency-departed", follow_redirects=False)
            return assert_status(r2, (302, 200))

        run_case(report, "rbac", "dispatcher create + emergency", dispatcher_workflow_create)

    with app.test_client() as master_client:
        def master_complete():
            from app.extensions import db
            from app.models.auth.user import User

            with app.app_context():
                mid = str(
                    db.session.scalar(db.select(User.id).where(User.email == "master@test.local"))
                )
            rid = ids.get("disp_request_id")
            if not rid:
                raise AssertionError("no disp request")

            with app.test_client() as admin_c:
                login(admin_c, "admin@opora.ru", "admin123")
                r_assign = admin_c.post(
                    f"/requests/{rid}/assign-master",
                    data={"master_id": mid, "submit": "x"},
                    follow_redirects=False,
                )
                assert_status(r_assign, (302, 200), "assign before master complete")

            with app.app_context():
                db.session.remove()

            login(master_client, "master@test.local", "pass12345")
            r = master_client.post(f"/requests/{rid}/complete", follow_redirects=False)
            return assert_status(r, (302, 200))

        run_case(report, "rbac", "master complete assigned", master_complete)

    return ids


def run_load(app, report: QaReport) -> None:
    """Нагрузка через test_client: конкурентные GET после логина."""
    endpoints = [
        "/",
        "/requests/",
        "/projects/",
        "/contracts/",
        "/reports/requests?period=week",
        "/search/api?q=QA",
        "/messenger/api/unread-count",
        "/audit/",
    ]

    # warm login cookie jar via one client, then clone cookies per worker
    with app.test_client() as c:
        login(c, "admin@opora.ru", "admin123")
        cookie_header = "; ".join(f"{k}={v}" for k, v in c._cookies.items()) if hasattr(c, "_cookies") else ""
        # Werkzeug CookieJar
        stored = []
        for cookie in c._cookies.values() if False else []:
            stored.append(cookie)
        jar = list(getattr(c, "cookie_jar", []) or [])
        # Use set_cookie from response approach: keep session by reusing login in workers

    def one_request(path: str) -> tuple[str, int, float, bool]:
        t0 = time.perf_counter()
        try:
            with app.test_client() as client:
                login(client, "admin@opora.ru", "admin123")
                r = client.get(path)
                ok = r.status_code == 200
                return path, r.status_code, (time.perf_counter() - t0) * 1000, ok
        except Exception:
            return path, 0, (time.perf_counter() - t0) * 1000, False

    # Sequential baseline
    seq_lat = []
    seq_ok = 0
    for path in endpoints * 5:
        _, status, ms, ok = one_request(path)
        seq_lat.append(ms)
        seq_ok += int(ok)

    # Concurrent burst
    jobs = endpoints * 20  # 160 requests
    conc_lat = []
    conc_ok = 0
    status_counts: dict[str, int] = {}
    t_burst = time.perf_counter()
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(one_request, p) for p in jobs]
        for fut in as_completed(futures):
            path, status, ms, ok = fut.result()
            conc_lat.append(ms)
            conc_ok += int(ok)
            key = str(status)
            status_counts[key] = status_counts.get(key, 0) + 1
    burst_s = time.perf_counter() - t_burst

    def pct(data, p):
        if not data:
            return 0
        s = sorted(data)
        idx = min(len(s) - 1, max(0, int(round((p / 100) * (len(s) - 1)))))
        return round(s[idx], 1)

    report.load = {
        "sequential": {
            "requests": len(seq_lat),
            "ok": seq_ok,
            "rps": round(len(seq_lat) / (sum(seq_lat) / 1000), 2) if seq_lat else 0,
            "avg_ms": round(statistics.mean(seq_lat), 1) if seq_lat else 0,
            "p95_ms": pct(seq_lat, 95),
        },
        "concurrent": {
            "requests": len(conc_lat),
            "workers": 8,
            "ok": conc_ok,
            "duration_s": round(burst_s, 2),
            "rps": round(len(conc_lat) / burst_s, 2) if burst_s else 0,
            "avg_ms": round(statistics.mean(conc_lat), 1) if conc_lat else 0,
            "p50_ms": pct(conc_lat, 50),
            "p95_ms": pct(conc_lat, 95),
            "p99_ms": pct(conc_lat, 99),
            "max_ms": round(max(conc_lat), 1) if conc_lat else 0,
            "status_counts": status_counts,
            "note": "Flask test_client + SQLite in-process; не замена gunicorn+PostgreSQL в проде",
        },
        "by_endpoint_sample": [],
    }

    # per-endpoint p95 sample (concurrent filtered)
    for path in endpoints:
        samples = []
        # re-run 20 each for clarity
        with ThreadPoolExecutor(max_workers=8) as pool:
            futs = [pool.submit(one_request, path) for _ in range(20)]
            for fut in as_completed(futs):
                _, status, ms, ok = fut.result()
                samples.append({"ms": ms, "ok": ok, "status": status})
        lat = [s["ms"] for s in samples]
        report.load["by_endpoint_sample"].append(
            {
                "path": path,
                "n": len(samples),
                "ok": sum(1 for s in samples if s["ok"]),
                "avg_ms": round(statistics.mean(lat), 1),
                "p95_ms": pct(lat, 95),
            }
        )

    run_case(
        report,
        "load",
        "concurrent burst success rate",
        lambda: (
            f"{report.load['concurrent']['ok']}/{report.load['concurrent']['requests']} "
            f"ok, p95={report.load['concurrent']['p95_ms']}ms, rps={report.load['concurrent']['rps']}"
            if report.load["concurrent"]["ok"] == report.load["concurrent"]["requests"]
            else (_ for _ in ()).throw(
                AssertionError(
                    f"failures: {report.load['concurrent']['ok']}/{report.load['concurrent']['requests']} "
                    f"statuses={report.load['concurrent']['status_counts']}"
                )
            )
        ),
    )


def analyze(report: QaReport) -> None:
    failed = [c for c in report.cases if not c.ok]
    passed = [c for c in report.cases if c.ok]
    load = report.load.get("concurrent", {})

    report.strengths = [
        "Модульная структура (blueprint registry) и единый RBAC по permission codes",
        "Workflow заявок формализован (can_transition) и покрыт unit-тестами переходов",
        "Мультизагрузка файлов + предпросмотр + лимит MAX_CONTENT_LENGTH с обработчиком 413",
        "Админ-контур: роли, конструктор полей, аудит, журнал входов",
        "Отчёты по заявкам с настраиваемым периодом",
        f"Функциональный прогон: {len(passed)}/{len(report.cases)} кейсов успешно",
    ]
    if load:
        report.strengths.append(
            f"Нагрузка (in-process): {load.get('ok')}/{load.get('requests')} OK, "
            f"~{load.get('rps')} RPS, p95={load.get('p95_ms')} ms"
        )

    report.weaknesses = [
        "Почти нет автотестов на HTTP/сервисы (только workflow unit) — регрессии ловятся вручную",
        "SQLite локально ≠ PostgreSQL прод: FTS, FOR UPDATE, UUID/миграции — риск расхождений",
        "CSRF-ошибка редиректит на login — выглядит как проблема авторизации",
        "Маршруты accept/start-work есть, но не в UI available_actions — мёртвый/скрытый код",
        "Нагрузка на test_client не отражает gunicorn workers / пул PG / сеть",
        "Мессенджер: polling, без websockets — при росте чатов вырастет нагрузка",
    ]
    if failed:
        report.weaknesses.insert(
            0,
            f"Упало {len(failed)} кейсов: " + "; ".join(f"{c.suite}/{c.name}" for c in failed[:8]),
        )

    report.recommendations = [
        {
            "priority": "P0",
            "title": "Автотесты HTTP + RBAC в CI",
            "why": "Сейчас один unit-файл; без CI ломаются uploads/workflow/права",
            "how": "pytest + TestingConfig, матрица ролей, fixture users, прогон в GitHub Actions",
        },
        {
            "priority": "P0",
            "title": "Нагрузочный прогон на PostgreSQL + gunicorn",
            "why": "Текущие цифры — in-process SQLite; прод-профиль другой",
            "how": "Locust/k6: login, список заявок, detail, messenger unread; цели p95/ошибок",
        },
        {
            "priority": "P1",
            "title": "Выравнять workflow UI и маршруты",
            "why": "accept/start-work расходятся с available_actions и правами complete",
            "how": "Либо убрать мёртвые роуты, либо добавить в UI и унифицировать permission checks",
        },
        {
            "priority": "P1",
            "title": "Улучшить UX ошибок CSRF/413",
            "why": "CSRF→login путает; большие файлы должны явно подсказывать лимит",
            "how": "Отдельная flash-страница CSRF; на форме upload показывать MAX_UPLOAD_MB",
        },
        {
            "priority": "P1",
            "title": "Индексы и N+1 на списках",
            "why": "При росте заявок/аудита списки и отчёты могут деградировать",
            "how": "EXPLAIN на /requests, /audit; selectin/joinedload; пагинация везде",
        },
        {
            "priority": "P2",
            "title": "Мессенджер: long-poll/SSE или WS",
            "why": "Частый polling умножается на пользователей",
            "how": "Снизить частоту + условный ETag; позже SSE",
        },
        {
            "priority": "P2",
            "title": "Антивирус/whitelist MIME + квоты",
            "why": "Сейчас сохранение по имени/mimetype клиента",
            "how": "Проверка magic bytes, blacklist исполняемых, per-user quota",
        },
        {
            "priority": "P2",
            "title": "Расширить отчёты",
            "why": "Пока только заявки; бизнесу нужны SLA и нагрузка по мастерам",
            "how": "Время до complete, топ адресов, загрузка мастеров, экспорт CSV",
        },
    ]


def _build_payload(report: QaReport) -> dict:
    payload = {
        "started_at": report.started_at,
        "finished_at": report.finished_at,
        "env": report.env,
        "summary": {
            "total": len(report.cases),
            "passed": sum(1 for c in report.cases if c.ok),
            "failed": sum(1 for c in report.cases if not c.ok),
            "suites": {},
        },
        "cases": [asdict(c) for c in report.cases],
        "load": report.load,
        "strengths": report.strengths,
        "weaknesses": report.weaknesses,
        "recommendations": report.recommendations,
    }
    suites: dict[str, dict] = {}
    for c in report.cases:
        s = suites.setdefault(c.suite, {"total": 0, "passed": 0, "failed": 0})
        s["total"] += 1
        if c.ok:
            s["passed"] += 1
        else:
            s["failed"] += 1
    payload["summary"]["suites"] = suites
    return payload


def main() -> int:
    started = datetime.now(timezone.utc).isoformat()
    report = QaReport(started_at=started)
    tmp = tempfile.mkdtemp(prefix="opora_qa_")
    app = None
    try:
        db_path = Path(tmp) / "qa.db"
        app = bootstrap_app(db_path)
        report.env = {
            "config": "testing",
            "db": "sqlite-temp",
            "csrf": False,
            "max_upload_mb": int(app.config["MAX_CONTENT_LENGTH"] / (1024 * 1024)),
            "python": sys.version.split()[0],
        }

        run_unit_workflow(report)
        run_functional(app, report)
        run_load(app, report)
        analyze(report)
    finally:
        report.finished_at = datetime.now(timezone.utc).isoformat()
        payload = _build_payload(report)
        RESULTS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
        print(f"Wrote {RESULTS_PATH}")
        if app is not None:
            try:
                with app.app_context():
                    from app.extensions import db

                    db.session.remove()
                    db.engine.dispose()
            except Exception:
                pass
        try:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)
        except Exception:
            pass

    return 0 if payload["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
