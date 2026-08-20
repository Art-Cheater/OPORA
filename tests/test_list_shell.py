"""Списки открываются оболочкой, таблица догружается отдельным запросом."""

from __future__ import annotations


SHELL_PATHS = (
    "/requests/",
    "/objects/",
    "/projects/",
    "/tenders/",
    "/contracts/",
    "/employees/",
    "/audit/",
    "/inquiries/",
    "/agreements/",
    "/contractors/",
)


def test_list_pages_are_shells_and_tables_load(admin_client):
    for path in SHELL_PATHS:
        page = admin_client.get(path)
        assert page.status_code == 200, path
        html = page.get_data(as_text=True)
        assert "opora-loading" in html, path
        assert "cdn.jsdelivr.net" not in html
        assert "unpkg.com" not in html

        table = admin_client.get(f"{path}table")
        assert table.status_code == 200, f"{path}table"
        payload = table.get_json()
        assert payload and "table_html" in payload, path
        assert "pagination_html" in payload, path


def test_agreements_map_json_is_available(admin_client):
    payload = admin_client.get("/agreements/map.json")
    assert payload.status_code == 200
    data = payload.get_json()
    assert "points" in data
    assert "remaining" in data
    assert payload.headers.get("Server-Timing")


def test_projects_index_keeps_create_after_user_choices(admin_client):
    page = admin_client.get("/projects/")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "Создать" in html
    table = admin_client.get("/projects/table")
    assert table.status_code == 200
    assert table.get_json()["table_html"]
