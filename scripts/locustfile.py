"""Locust-сценарий нагрузки (против уже запущенного сервера).

Запуск:
  pip install locust
  # в другом терминале: python run.py
  locust -f scripts/locustfile.py --host http://127.0.0.1:5000

UI: http://localhost:8089
Headless пример:
  locust -f scripts/locustfile.py --host http://127.0.0.1:5000 \
    --users 20 --spawn-rate 5 --run-time 2m --headless
"""

from __future__ import annotations

import os
import re

from locust import HttpUser, between, task


ADMIN_EMAIL = os.getenv("LOCUST_EMAIL", "admin@opora.ru")
ADMIN_PASSWORD = os.getenv("LOCUST_PASSWORD", "admin123")


class OporaUser(HttpUser):
    wait_time = between(0.5, 2.0)

    def on_start(self):
        # CSRF-off для testing; для prod берём токен из login page
        page = self.client.get("/auth/login")
        token = ""
        match = re.search(
            r'name="csrf_token"[^>]*value="([^"]+)"', page.text or ""
        )
        if match:
            token = match.group(1)
        self.client.post(
            "/auth/login",
            data={
                "email": ADMIN_EMAIL,
                "password": ADMIN_PASSWORD,
                "csrf_token": token,
                "submit": "Войти",
            },
            name="/auth/login",
        )

    @task(5)
    def dashboard(self):
        self.client.get("/", name="/")

    @task(8)
    def requests_list(self):
        self.client.get("/requests/", name="/requests/")

    @task(3)
    def projects_list(self):
        self.client.get("/projects/", name="/projects/")

    @task(3)
    def contracts_list(self):
        self.client.get("/contracts/", name="/contracts/")

    @task(2)
    def reports(self):
        self.client.get("/reports/requests?period=week", name="/reports/requests")

    @task(4)
    def search(self):
        self.client.get("/search/api?q=QA", name="/search/api")

    @task(4)
    def messenger_unread(self):
        self.client.get("/messenger/api/unread-count", name="/messenger/api/unread-count")

    @task(1)
    def audit(self):
        self.client.get("/audit/", name="/audit/")
