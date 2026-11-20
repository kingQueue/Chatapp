import asyncio
import json
import tempfile
import unittest
from pathlib import Path

import httpx

from ticketing.config import Agent, MCP, MCPTool, Settings
from ticketing.schema import TicketFields
from ticketing.store import Store, encode
from ticketing.tools import ToolError, Tools
from ticketing.worker import Worker, validate_decision


class DispatcherTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        agent = Agent(enabled=True, base_url="http://model.local/v1", model="model", system_prompt="Test",
                      token_budget=30000, input_usd_per_million=1, output_usd_per_million=2)
        research = agent.model_copy(update={"allowed_file_paths": ["research"],
                                           "allowed_mcp_tools": ["write_research_note"]})
        settings = Settings(root, "unused", True, "soup",
                            {"orchestrator": agent, "reviewer": agent, "research_agent": research})
        self.store = Store(root / "db.sqlite3", root / "runs")
        self.worker = Worker(settings, self.store)
        self.ticket = self.store.create(TicketFields(title="Test", acceptance=["One file"]))
        self.key = self.ticket["id"]

    @staticmethod
    def reply(message):
        return httpx.Response(200, json={"choices": [{"message": message}],
                                        "usage": {"prompt_tokens": 100, "completion_tokens": 20}})

    def decision(self, action, assignee=None):
        return {"action": action, "ticket_id": self.key, "assignee": assignee,
                "reason": "Expected action", "subtasks": []}

    def test_orchestrator_json_schema(self):
        value = self.decision("assign", "research_agent")
        workers = {"research_agent"}
        self.assertEqual(validate_decision(encode(value), self.ticket, "triage", workers).assignee, "research_agent")
        invalid = [
            "not JSON",
            encode({**value, "ticket_id": "T-0002"}),
            encode({**value, "extra": 17}),
            encode({**value, "reason": " "}),
            encode({**value, "assignee": "reviewer"}),
            encode(self.decision("close")),
            encode(self.decision("split")),
            encode(value).replace('"action":', '"action":"escalate","action":'),
        ]
        for text in invalid:
            with self.subTest(text=text), self.assertRaises(ValueError):
                validate_decision(text, self.ticket, "triage", workers)

    async def test_retry_tool_handoff_review_and_export(self):
        responses = iter([
            {"content": "Invalid"},
            {"content": encode(self.decision("assign", "research_agent"))},
            {"content": None, "tool_calls": [{"id": "c1", "function": {
                "name": "write_research_note", "arguments": encode({"path": "research/note.md", "content": "Notes"}),
            }}]},
            {"content": encode({"work_done": "Notes", "files_produced": ["research/note.md"],
                                "unresolved_issues": [], "next_agent_needs": "Review the note"})},
            {"content": encode(self.decision("request_review"))},
            {"content": encode({"verdict": "pass", "reasons": ["The note met acceptance."]})},
            {"content": encode(self.decision("close"))},
        ])
        self.store.request_triage(self.key)
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: self.reply(next(responses)))) as client:
            for state in ["ready", "review", "done"]:
                await self.worker.dispatch(client, *self.store.claim(self.worker.enabled))
                self.assertEqual(self.store.get(self.key)["status"], state)
        ticket = self.store.get(self.key)
        self.assertEqual(ticket["attempts"], 1)
        self.assertEqual(ticket["tokens"], 840)
        self.assertAlmostEqual(ticket["token_cost"], 0.00098)
        row, = self.store.export("research_agent")
        self.assertEqual([item["role"] for item in row["messages"]], ["system", "user", "assistant", "tool", "assistant"])
        self.assertEqual(row["messages"][3]["tool_call_id"], "c1")
        self.assertEqual(len(list(self.store.export("orchestrator"))), 3)
        self.assertEqual(len(list(self.store.logs.glob("*.jsonl"))), 5)
        self.assertEqual((self.worker.settings.root / "research" / "note.md").read_text(), "Notes")

    async def test_invalid_retry_escalates(self):
        self.store.request_triage(self.key)
        calls = []

        def invalid(request):
            calls.append(request)
            return self.reply({"content": "Still invalid"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(invalid)) as client:
            await self.worker.dispatch(client, *self.store.claim(self.worker.enabled))
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.store.get(self.key)["status"], "needs_human")
        self.assertEqual(self.store.runs(self.key)[0]["status"], "failed")

    async def test_destructive_mcp_call_requires_one_approval(self):
        work = self.store.create(TicketFields(title="Tool test", assignee="research_agent"))
        key = work["id"]
        self.store.transition(key, "ready", "Start test")
        job, _, _, _ = self.store.claim(self.worker.enabled)
        agent = self.worker.settings.agents["research_agent"].model_copy(update={
            "allowed_mcp_tools": ["remove_fixture"],
            "mcp": MCP(endpoint="http://mcp.local", tools={"remove_fixture": MCPTool(effect="destructive")}),
        })
        remote_calls = []

        def mcp(request):
            data = json.loads(request.content)
            mode = data["method"]
            if mode == "initialize":
                result = {"protocolVersion": "2025-06-18"}
            elif mode == "tools/list":
                result = {"tools": [{"name": "remove_fixture", "inputSchema": {"type": "object"}}]}
            elif mode == "tools/call":
                remote_calls.append(data["params"])
                result = {"content": []}
            else:
                return httpx.Response(202)
            return httpx.Response(200, json={"id": data["id"], "result": result})

        async with httpx.AsyncClient(transport=httpx.MockTransport(mcp)) as client:
            tools = Tools(client, self.worker.settings.root, agent, self.store, key, job)
            await tools.describe()
            for decision in ("denied", "approved"):
                invocation = asyncio.create_task(tools.call("remove_fixture", {"name": decision}))
                await asyncio.sleep(0)
                self.assertFalse(remote_calls)
                approval, = self.store.approvals()
                self.assertEqual(approval["arguments"], {"name": decision})
                self.store.decide_approval(approval["id"], decision)
                if decision == "denied":
                    with self.assertRaisesRegex(ToolError, "not approved"):
                        await invocation
                else:
                    await invocation
                    self.assertEqual(remote_calls, [{"name": "remove_fixture", "arguments": {"name": decision}}])
