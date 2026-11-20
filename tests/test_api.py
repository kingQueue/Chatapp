import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from ticketing.app import create_app
from ticketing.config import Settings


class ApiTests(unittest.TestCase):
    def test_auth_and_ticket_lifecycle(self):
        with tempfile.TemporaryDirectory() as temp:
            settings = Settings(Path(temp), "a" * 32, False, "soup", {})
            with TestClient(create_app(settings)) as client:
                response = client.get("/")
                self.assertEqual(response.status_code, 401)
                self.assertIn("Unlock tickets", response.text)
                for path in ("ui", "ui.js", "ui.css", "api/tickets", "api/approvals", "api/training", "api/datasets"):
                    self.assertEqual(client.get("/" + path).status_code, 401)
                headers = {"Authorization": "Bearer " + settings.token}
                self.assertIn("Ticket board", client.get("/ui", headers=headers).text)
                response = client.post("/api/tickets", headers=headers, json={"title": "Phone ticket"})
                self.assertEqual(response.status_code, 201)
                ticket = response.json()
                path = "/api/tickets/" + ticket["id"]
                response = client.post(path + "/transition", headers=headers, json={"status": "done", "reason": "Skip"})
                self.assertEqual(response.status_code, 409)
                self.assertIn("Illegal transition", response.json()["detail"])
                for field in ("history", "active", "triage_queued"):
                    ticket.pop(field)
                ticket["title"] = "Edited"
                ticket["status"] = "ready"
                self.assertEqual(client.put(path, headers=headers, json=ticket).status_code, 200)
                self.assertEqual(client.put(path, headers=headers, json=ticket).status_code, 409)
