"""Контейнер Кировсвета читает из базы только адрес и статус."""

from importlib.machinery import SourceFileLoader
from pathlib import Path

dbmap = SourceFileLoader("kirovsvet_dbmap", str(Path(__file__).parents[1] / "site" / "dbmap.py")).load_module()


def test_public_sql_does_not_select_personal_columns():
    sql = dbmap.OPEN_REQUESTS_SQL.lower()
    for column in ("phone", "applicant_name", "description", "title", "number", "dispatcher_name"):
        assert column not in sql
    assert "is_final is false" in sql


def test_public_rows_drop_phone_and_apartment():
    class Cursor:
        def execute(self, _sql):
            return None

        def fetchall(self):
            return [
                (
                    "ул. Ленина, 10, кв. 5, +7 912 345-67-89",
                    "улица Ленина",
                    "10",
                    "Октябрьский",
                    58.60359555,
                    49.66801234,
                    "Новая",
                )
            ]

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class Connection:
        def cursor(self):
            return Cursor()

    item = dbmap.load_open_requests(Connection())[0]
    assert item == {
        "address": "улица Ленина, 10",
        "status": "Новая",
        "district": "Октябрьский",
        "lat": 58.6036,
        "lon": 49.66801,
    }
    assert "912" not in item["address"]
