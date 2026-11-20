import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .schema import TicketFields
from .state import Conflict, Missing, advance


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


class Store:
    def __init__(self, database, logs):
        self.database = Path(database)
        self.logs = Path(logs)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.logs.mkdir(parents=True, exist_ok=True)
        with self.transaction() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS tickets (
                    pk INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE,
                    data TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
                    busy TEXT, work_run TEXT, requested INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS history (
                    seq INTEGER PRIMARY KEY, ticket INTEGER NOT NULL REFERENCES tickets,
                    event TEXT NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS history_no_update BEFORE UPDATE ON history
                    BEGIN SELECT RAISE(ABORT, 'history is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS history_no_delete BEFORE DELETE ON history
                    BEGIN SELECT RAISE(ABORT, 'history is append-only'); END;
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, ticket INTEGER NOT NULL REFERENCES tickets,
                    agent TEXT NOT NULL, kind TEXT NOT NULL, data TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS runs_ticket ON runs(ticket);
                CREATE TABLE IF NOT EXISTS approvals (
                    id TEXT PRIMARY KEY, ticket INTEGER NOT NULL REFERENCES tickets,
                    job TEXT NOT NULL, data TEXT NOT NULL, status TEXT NOT NULL
                );
            """)

    @contextmanager
    def transaction(self, write=True):
        db = sqlite3.connect(self.database, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys = ON")
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _row(self, db, key):
        row = db.execute("SELECT * FROM tickets WHERE id = ?", (key,)).fetchone()
        if row is None:
            raise Missing(f"Ticket {key} was not found.")
        return row

    def _states(self, db):
        return {row["id"]: json.loads(row["data"]) for row in db.execute("SELECT id,data FROM tickets")}

    def _event(self, db, row, kind, **details):
        db.execute("INSERT INTO history(ticket,event) VALUES (?,?)",
                   (row["pk"], encode({"at": now(), "kind": kind, **details})))

    def _validate(self, db, key, ticket):
        states = self._states(db)
        states[key] = ticket
        for value in [ticket["created"], ticket["updated"]]:
            try:
                TicketFields.check_time(value)
            except (ValueError, AttributeError) as exc:
                raise Conflict("Use ISO 8601 timestamps with a time zone.") from exc
        for relation, many in (("depends_on", True), ("parent_id", False)):
            def links(data):
                return data[relation] if many else ([data[relation]] if data[relation] else [])

            direct = links(ticket)
            if len(set(direct)) != len(direct):
                raise Conflict("Dependencies must be unique.")
            if any(item not in states for item in direct):
                raise Conflict(f"Every {relation} reference must name an existing ticket.")
            seen, pending = set(), direct.copy()
            while pending:
                node = pending.pop()
                if node == key:
                    raise Conflict(f"A {relation} reference would create a cycle.")
                if node not in seen:
                    seen.add(node)
                    pending.extend(links(states[node]))
        if ticket["status"] in {"ready", "in_progress"}:
            incomplete = [item for item in ticket["depends_on"] if states[item]["status"] != "done"]
            if incomplete:
                raise Conflict("Finish dependencies first: " + ", ".join(incomplete))

    def _insert(self, db, values, actor):
        ticket = values.model_dump()
        if ticket["status"] != "backlog":
            raise Conflict("Create tickets in backlog, then move them through the board.")
        ticket["created"] = ticket["created"] or now()
        ticket["updated"] = ticket["updated"] or ticket["created"]
        pk = db.execute("INSERT INTO tickets(data) VALUES (?)", (encode(ticket),)).lastrowid
        number = pk
        while db.execute("SELECT 1 FROM tickets WHERE id = ?", (f"T-{number:04}",)).fetchone():
            number += 1
        key = f"T-{number:04}"
        self._validate(db, key, ticket)
        db.execute("UPDATE tickets SET id = ? WHERE pk = ?", (key, pk))
        row = self._row(db, key)
        self._event(db, row, "created", actor=actor)
        return row

    def _view(self, db, row, history=True):
        result = {**json.loads(row["data"]), "id": row["id"], "revision": row["revision"],
                  "active": row["busy"] is not None, "triage_queued": bool(row["requested"])}
        if history:
            result["history"] = [json.loads(event["event"]) for event in db.execute(
                "SELECT event FROM history WHERE ticket = ? ORDER BY seq", (row["pk"],))]
        return result

    def list(self):
        with self.transaction(False) as db:
            return [self._view(db, row, False) for row in db.execute("SELECT * FROM tickets ORDER BY pk")]

    def get(self, key):
        with self.transaction(False) as db:
            return self._view(db, self._row(db, key))

    def create(self, values):
        with self.transaction() as db:
            return self._view(db, self._insert(db, values, "human"))

    def _move(self, db, row, ticket, status, reason, actor):
        states = self._states(db)
        guard = {**ticket, "attempts": self._effective_attempts(db, row, ticket)}
        target, reason = advance(guard, status, {k: v["status"] for k, v in states.items()}, reason)
        if ticket["status"] == "done":
            for key, value in states.items():
                if row["id"] in value["depends_on"] and value["status"] in {"ready", "in_progress"}:
                    dependent = self._row(db, key)
                    self._move(db, dependent, value, "needs_human",
                               f"Dependency {row['id']} is no longer done.", "dispatcher")
                    value["updated"] = now()
                    self._save(db, dependent, value)
        if target == "needs_human":
            db.execute("UPDATE approvals SET status = 'expired' WHERE ticket = ? AND status = 'pending'",
                       (row["pk"],))
        self._event(db, row, "transition", actor=actor, source=ticket["status"], target=target, reason=reason)
        ticket["status"] = target
        return target

    def _effective_attempts(self, db, row, ticket):
        attempts = db.execute("""SELECT coalesce(max(json_extract(event, '$.number')), 0) FROM history WHERE ticket = ?
                                 AND json_extract(event, '$.kind') = 'attempt'""", (row["pk"],)).fetchone()[0]
        return max(attempts, ticket["attempts"])

    def _save(self, db, row, ticket):
        db.execute("UPDATE tickets SET data = ?, revision = revision + 1 WHERE pk = ?",
                   (encode(ticket), row["pk"]))

    def edit(self, key, values):
        with self.transaction() as db:
            row = self._row(db, key)
            if row["busy"] or row["revision"] != values.revision:
                raise Conflict("The ticket changed or an agent is working on it. Reload and try again.")
            previous = json.loads(row["data"])
            ticket = values.model_dump(exclude={"id", "revision"})
            requested = ticket["status"]
            ticket["status"] = previous["status"]
            if requested != previous["status"]:
                self._move(db, row, ticket, requested, "Status changed in ticket editor.", "human")
            ticket["created"] = ticket["created"] or previous["created"]
            if not ticket["updated"] or ticket["updated"] == previous["updated"]:
                ticket["updated"] = now()
            if values.id != key:
                if db.execute("SELECT 1 FROM tickets WHERE id = ?", (values.id,)).fetchone():
                    raise Conflict(f"Ticket {values.id} already exists.")
                db.execute("UPDATE tickets SET id = ? WHERE pk = ?", (values.id, row["pk"]))
                for linked in db.execute("SELECT * FROM tickets WHERE pk != ?", (row["pk"],)).fetchall():
                    data = json.loads(linked["data"])
                    if key in data["depends_on"] or data["parent_id"] == key:
                        data["depends_on"] = [values.id if item == key else item for item in data["depends_on"]]
                        if data["parent_id"] == key:
                            data["parent_id"] = values.id
                        data["updated"] = now()
                        self._save(db, linked, data)
                        self._event(db, linked, "reference_renamed", old=key, new=values.id)
            self._validate(db, values.id, ticket)
            self._save(db, row, ticket)
            self._event(db, row, "edited", actor="human",
                        fields=[name for name in ticket if previous[name] != ticket[name]] +
                        (["id"] if values.id != key else []), old_id=key, new_id=values.id)
            if ticket["status"] != previous["status"]:
                db.execute("UPDATE tickets SET requested = 0 WHERE pk = ?", (row["pk"],))
            return self._view(db, self._row(db, values.id))

    def transition(self, key, status, reason):
        with self.transaction() as db:
            row = self._row(db, key)
            if row["busy"] and status != "needs_human":
                raise Conflict("An agent is working on this ticket.")
            ticket = json.loads(row["data"])
            self._move(db, row, ticket, status, reason, "human")
            ticket["updated"] = now()
            self._save(db, row, ticket)
            db.execute("UPDATE tickets SET requested = 0 WHERE pk = ?", (row["pk"],))
            return self._view(db, self._row(db, key))

    def request_triage(self, key):
        with self.transaction() as db:
            row = self._row(db, key)
            if row["busy"] or json.loads(row["data"])["status"] not in {"backlog", "ready"}:
                raise Conflict("Triage can be queued for an idle backlog or ready ticket.")
            db.execute("UPDATE tickets SET requested = 1 WHERE pk = ?", (row["pk"],))
            self._event(db, row, "triage_requested", actor="human")

    def claim(self, enabled):
        with self.transaction() as db:
            for row in db.execute("SELECT * FROM tickets WHERE busy IS NULL ORDER BY requested DESC, pk"):
                ticket = self._view(db, row, False)
                status, assignee = ticket["status"], ticket["assignee"]
                work = assignee is not None and assignee not in {"orchestrator", "reviewer"}
                kind = None
                if row["requested"] and status in {"backlog", "ready"} and "orchestrator" in enabled:
                    kind = "triage"
                elif status == "ready" and not work and "orchestrator" in enabled:
                    kind = "triage"
                elif status in {"ready", "in_progress"} and work and assignee in enabled:
                    kind = "work"
                elif status == "review" and row["work_run"] and "reviewer" in enabled:
                    kind = "review"
                if kind is None:
                    continue
                if kind == "work":
                    effective_attempts = self._effective_attempts(db, row, ticket)
                    if effective_attempts >= 3:
                        self._move(db, row, ticket, "needs_human", "Three work attempts used.", "dispatcher")
                    else:
                        if status == "ready":
                            self._move(db, row, ticket, "in_progress", "Work claimed.", "dispatcher")
                        ticket["attempts"] = effective_attempts + 1
                        self._event(db, row, "attempt", number=ticket["attempts"], assignee=assignee)
                    ticket["updated"] = now()
                    self._save(db, row, {name: ticket[name] for name in TicketFields.model_fields})
                    if ticket["status"] == "needs_human":
                        continue
                job = uuid4().hex
                db.execute("UPDATE tickets SET busy = ?, requested = 0 WHERE pk = ?", (job, row["pk"]))
                current = self._view(db, self._row(db, row["id"]), False)
                return job, kind, current, row["work_run"]
        return None

    def running(self, key, job):
        with self.transaction(False) as db:
            row = self._row(db, key)
            return row["busy"] == job and json.loads(row["data"])["status"] != "needs_human"

    def apply_decision(self, key, job, decision, phase, passed=False):
        with self.transaction() as db:
            row = self._row(db, key)
            ticket = json.loads(row["data"])
            if row["busy"] != job or ticket["status"] == "needs_human":
                return
            action = decision.action
            if action == "escalate":
                self._move(db, row, ticket, "needs_human", decision.reason, "orchestrator")
            elif action == "assign" and phase == "triage" and ticket["status"] in {"backlog", "ready"}:
                ticket["assignee"] = decision.assignee
                if ticket["status"] == "backlog":
                    self._move(db, row, ticket, "ready", decision.reason, "orchestrator")
                self._event(db, row, "assigned", assignee=decision.assignee, reason=decision.reason)
            elif action == "split" and phase == "triage" and ticket["status"] == "backlog":
                children = [self._insert(db, TicketFields(**task.model_dump(), parent_id=key), "orchestrator")["id"]
                            for task in decision.subtasks]
                if len(ticket["depends_on"]) + len(children) > 100:
                    raise Conflict("Splitting would exceed the ticket's dependency limit.")
                ticket["depends_on"].extend(children)
                self._event(db, row, "split", children=children, reason=decision.reason)
            elif action == "request_review" and phase == "handoff":
                self._move(db, row, ticket, "review", decision.reason, "orchestrator")
            elif action == "close" and phase == "verdict" and passed:
                self._move(db, row, ticket, "done", decision.reason, "orchestrator")
            else:
                raise Conflict(f"Action {action} is unavailable during {phase}.")
            ticket["updated"] = now()
            self._save(db, row, ticket)

    def mutate_job(self, key, job, *, status=None, reason="", work_run=None, outputs=()):
        with self.transaction() as db:
            row = self._row(db, key)
            ticket = json.loads(row["data"])
            if row["busy"] != job or ticket["status"] == "needs_human":
                return
            if status:
                self._move(db, row, ticket, status, reason, "dispatcher")
            if work_run:
                db.execute("UPDATE tickets SET work_run = ? WHERE pk = ?", (work_run, row["pk"]))
                ticket["outputs"] = list(dict.fromkeys([*ticket["outputs"], *outputs]))[:100]
                self._event(db, row, "handoff", run=work_run)
            ticket["updated"] = now()
            self._save(db, row, ticket)

    def release(self, key, job):
        with self.transaction() as db:
            row = self._row(db, key)
            db.execute("UPDATE tickets SET busy = NULL WHERE pk = ? AND busy = ?", (row["pk"], job))
            db.execute("UPDATE approvals SET status = 'expired' WHERE job = ? AND status = 'pending'", (job,))

    def recover(self):
        with self.transaction() as db:
            for row in db.execute("SELECT * FROM tickets WHERE busy IS NOT NULL").fetchall():
                ticket = json.loads(row["data"])
                if ticket["status"] != "needs_human":
                    self._move(db, row, ticket, "needs_human", "Server restarted during a job.", "dispatcher")
                ticket["updated"] = now()
                self._save(db, row, ticket)
                db.execute("UPDATE tickets SET busy = NULL WHERE pk = ?", (row["pk"],))
            db.execute("UPDATE approvals SET status = 'expired' WHERE status = 'pending'")
            for row in db.execute("SELECT id,data FROM runs").fetchall():
                record = json.loads(row["data"])
                if record["status"] == "running":
                    record.update(status="interrupted", finished=now(), error="Server restarted.")
                    db.execute("UPDATE runs SET data = ? WHERE id = ?", (encode(record), row["id"]))
                if not (self.logs / (row["id"] + ".jsonl")).is_file() or record["status"] == "interrupted":
                    self._mirror(record)

    def _mirror(self, record):
        file = self.logs / (record["id"] + ".jsonl")
        temporary = file.with_suffix("." + uuid4().hex + ".tmp")
        temporary.write_text(encode(record) + "\n", encoding="utf-8")
        os.replace(temporary, file)

    def save_run(self, key, record, usage=(0, 0, 0)):
        with self.transaction() as db:
            row = self._row(db, key)
            db.execute("""INSERT INTO runs(id,ticket,agent,kind,data) VALUES (?,?,?,?,?)
                          ON CONFLICT(id) DO UPDATE SET data = excluded.data""",
                       (record["id"], row["pk"], record["agent"], record["kind"], encode(record)))
            if usage != (0, 0, 0):
                ticket = json.loads(row["data"])
                ticket["tokens"] += usage[0] + usage[1]
                ticket["token_cost"] += usage[2]
                ticket["updated"] = now()
                self._save(db, row, ticket)
            self._mirror(record)

    def runs(self, key):
        with self.transaction(False) as db:
            row = self._row(db, key)
            return [json.loads(item["data"]) for item in db.execute(
                "SELECT data FROM runs WHERE ticket = ? ORDER BY rowid DESC", (row["pk"],))]

    def run(self, run_id):
        with self.transaction(False) as db:
            row = db.execute("SELECT data FROM runs WHERE id = ?", (run_id,)).fetchone()
            if not row:
                raise Missing("Run was not found.")
            return json.loads(row["data"])

    def used_tokens(self, key, agent):
        with self.transaction(False) as db:
            row = self._row(db, key)
            used = db.execute("""SELECT coalesce(sum(json_extract(data,'$.input_tokens') +
                                 json_extract(data,'$.output_tokens')), 0) FROM runs
                                 WHERE ticket = ? AND agent = ?""", (row["pk"], agent)).fetchone()
            return used[0]

    def record_verdict(self, key, verdict):
        with self.transaction() as db:
            row = self._row(db, key)
            for run in db.execute("SELECT id,data FROM runs WHERE ticket = ?", (row["pk"],)).fetchall():
                record = json.loads(run["data"])
                if record["reviewer_verdict"] is None and record["status"] == "completed":
                    record["reviewer_verdict"] = verdict
                    db.execute("UPDATE runs SET data = ? WHERE id = ?", (encode(record), run["id"]))
                    self._mirror(record)

    def export(self, agent):
        with self.transaction(False) as db:
            runs = db.execute("""SELECT runs.data, tickets.data AS ticket FROM runs
                                 JOIN tickets ON runs.ticket = tickets.pk WHERE runs.agent = ?""", (agent,))
            for item in runs:
                record, ticket = json.loads(item["data"]), json.loads(item["ticket"])
                if ticket["status"] != "done" or record["status"] != "completed":
                    continue
                rejected = db.execute("""SELECT 1 FROM history JOIN runs ON history.ticket = runs.ticket
                                          WHERE runs.id = ? AND json_extract(event,'$.source') = 'review'
                                          AND json_extract(event,'$.target') IN ('in_progress','needs_human')""",
                                      (record["id"],)).fetchone()
                if not rejected and (record.get("reviewer_verdict") or {}).get("verdict") == "pass":
                    discard = set(record.get("retry_messages", []))
                    yield {"messages": [message for index, message in enumerate(record["messages"])
                                        if index not in discard], "tools": record["tools"]}

    def approval(self, key, job, call):
        with self.transaction() as db:
            row = self._row(db, key)
            if row["busy"] != job or json.loads(row["data"])["status"] == "needs_human":
                raise Conflict("This job is no longer active.")
            identifier = uuid4().hex
            db.execute("INSERT INTO approvals VALUES (?,?,?,?, 'pending')",
                       (identifier, row["pk"], job, encode(call)))
            self._event(db, row, "approval_requested", approval=identifier, tool=call["name"])
            return identifier

    def approvals(self):
        with self.transaction(False) as db:
            return [{"id": row["id"], "ticket_id": row["public_id"], **json.loads(row["data"])}
                    for row in db.execute("""SELECT approvals.*, tickets.id AS public_id FROM approvals
                                             JOIN tickets ON tickets.pk = approvals.ticket
                                             WHERE status = 'pending' ORDER BY approvals.rowid""")]

    def approval_status(self, identifier):
        with self.transaction(False) as db:
            row = db.execute("SELECT status FROM approvals WHERE id = ?", (identifier,)).fetchone()
            return row["status"] if row else "expired"

    def expire_approval(self, identifier):
        with self.transaction() as db:
            db.execute("UPDATE approvals SET status = 'expired' WHERE id = ? AND status = 'pending'", (identifier,))

    def decide_approval(self, identifier, decision):
        with self.transaction() as db:
            row = db.execute("""SELECT approvals.status,approvals.job,tickets.pk,tickets.busy,
                                tickets.data FROM approvals JOIN tickets ON tickets.pk = approvals.ticket
                                WHERE approvals.id = ?""", (identifier,)).fetchone()
            if not row:
                raise Missing("Approval was not found.")
            if row["status"] != "pending" or row["job"] != row["busy"] or (
                json.loads(row["data"])["status"] == "needs_human"
            ):
                raise Conflict("This approval is no longer pending.")
            db.execute("UPDATE approvals SET status = ? WHERE id = ?", (decision, identifier))
            self._event(db, row, "approval_decided", approval=identifier, decision=decision, actor="human")
