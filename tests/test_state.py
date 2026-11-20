import tempfile
import unittest
from pathlib import Path

from ticketing.schema import TicketEdit, TicketFields
from ticketing.state import Conflict
from ticketing.store import Store


class StateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.store = Store(root / "tickets.sqlite3", root / "logs")

    def test_dependency_gate_and_illegal_shortcut(self):
        parent = self.store.create(TicketFields(title="CAD"))
        child = self.store.create(TicketFields(title="Review", depends_on=[parent["id"]]))
        with self.assertRaisesRegex(Conflict, "Finish dependencies"):
            self.store.transition(child["id"], "ready", "Try")
        with self.assertRaisesRegex(Conflict, "Illegal transition"):
            self.store.transition(parent["id"], "done", "Skip")
        for state in ["ready", "in_progress", "review", "done"]:
            self.store.transition(parent["id"], state, "Next")
        self.assertEqual(self.store.transition(child["id"], "ready", "Go")["status"], "ready")

    def test_third_rejection_escalates(self):
        ticket = self.store.create(TicketFields(title="Work", attempts=2, assignee="research_agent"))
        key = ticket["id"]
        self.store.transition(key, "ready", "Start")
        job, kind, current, _ = self.store.claim({"research_agent"})
        self.assertEqual((kind, current["attempts"]), ("work", 3))
        self.store.mutate_job(key, job, status="review", reason="Finished")
        self.store.release(key, job)
        self.assertEqual(self.store.transition(key, "in_progress", "Rejected")["status"], "needs_human")

    def test_cycle_and_id_changes_are_atomic(self):
        parent = self.store.create(TicketFields(title="Parent"))
        child = self.store.create(TicketFields(title="Child", depends_on=[parent["id"]]))
        editable = {name: parent[name] for name in TicketEdit.model_fields}
        with self.assertRaisesRegex(Conflict, "cycle"):
            self.store.edit(parent["id"], TicketEdit(**{**editable, "depends_on": [child["id"]]}))
        changed = self.store.edit(parent["id"], TicketEdit(**{**editable, "id": "T-0100"}))
        self.assertEqual(self.store.get(child["id"])["depends_on"], [changed["id"]])
        self.assertEqual(changed["history"][-1]["old_id"], parent["id"])

    def test_block_and_human_escalation(self):
        key = self.store.create(TicketFields(title="Work"))["id"]
        for state in ["ready", "in_progress", "blocked", "needs_human"]:
            self.assertEqual(self.store.transition(key, state, "Next")["status"], state)
        with self.assertRaisesRegex(Conflict, "Illegal transition"):
            self.store.transition(key, "ready", "Restart")
