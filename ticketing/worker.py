import asyncio
import json
import logging
import os
from uuid import uuid4

import httpx

from . import freecad
from .schema import Decision, Handoff, Verdict
from .state import Conflict
from .store import encode, now
from .tools import ToolError, Tools

LOGGER = logging.getLogger(__name__)
CHOICES = {"triage": {"assign", "split", "escalate"},
           "handoff": {"request_review", "escalate"},
           "verdict": {"close", "escalate"}}


def unique_object(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError(f"Duplicate JSON field: {name}")
        result[name] = value
    return result


def parse_json(text):
    return json.loads(text, object_pairs_hook=unique_object)


def validate_decision(text, ticket, phase, workers):
    decision = Decision.model_validate(parse_json(text))
    if decision.ticket_id != ticket["id"]:
        raise ValueError("Decision ticket_id must match the active ticket.")
    action = decision.action
    if action not in CHOICES[phase] or (action == "split" and ticket["status"] != "backlog"):
        raise ValueError(f"Action {action} is unavailable during {phase} for {ticket['status']}.")
    if action == "assign" and decision.assignee not in workers:
        raise ValueError("Assign to an enabled work agent.")
    if action != "assign" and decision.assignee is not None:
        raise ValueError("Use null for assignee unless the action is assign.")
    if bool(decision.subtasks) != (action == "split"):
        raise ValueError("Provide subtasks only for split, with at least one subtask.")
    if any(task.assignee is not None and task.assignee not in workers for task in decision.subtasks):
        raise ValueError("Subtask assignees must be enabled work agents.")
    return decision


def approximate_tokens(value):
    return max(1, (len(encode(value).encode("utf-8")) + 2) // 3)


class Worker:
    def __init__(self, settings, store):
        self.settings, self.store = settings, store
        self.enabled = {name for name, agent in settings.agents.items() if agent.enabled}
        self.workers = self.enabled - {"orchestrator", "reviewer"}

    async def run(self):
        async with httpx.AsyncClient(timeout=httpx.Timeout(180, connect=10), trust_env=False) as client:
            jobs = set()
            try:
                while True:
                    for task in {task for task in jobs if task.done()}:
                        jobs.remove(task)
                        task.result()
                    while len(jobs) < 4:
                        claim = self.store.claim(self.enabled)
                        if claim is None:
                            break
                        jobs.add(asyncio.create_task(self.dispatch(client, *claim)))
                    await asyncio.sleep(0.5)
            finally:
                for task in jobs:
                    task.cancel()
                await asyncio.gather(*jobs, return_exceptions=True)

    async def dispatch(self, client, job, kind, ticket, work_run):
        key = ticket["id"]
        try:
            if kind == "triage":
                await self.decide(client, job, ticket, "triage")
            elif kind == "work":
                handoff, run = await self.complete(client, job, ticket, ticket["assignee"], kind, {
                    "ticket": ticket, "prior_review": (self.store.run(work_run)["reviewer_verdict"] if work_run else None),
                }, Handoff, lambda text: Handoff.model_validate(parse_json(text)))
                if freecad.NAME in self.settings.agents[ticket["assignee"]].allowed_mcp_tools:
                    produced = {file for item in run["tool_results"]
                                if isinstance(item["result"], dict) and item["result"].get("shape_validated") is True
                                for file in item["result"]["files"]}
                    if not produced or set(handoff.files_produced) != produced:
                        raise Conflict("CAD handoff must list the files returned by a successful FreeCAD run.")
                self.store.mutate_job(key, job, work_run=run["id"], outputs=handoff.files_produced)
                if "orchestrator" in self.enabled:
                    await self.decide(client, job, ticket, "handoff", handoff=handoff.model_dump())
                else:
                    self.store.mutate_job(key, job, status="review", reason="Agent handoff received.")
            else:
                handoff = self.store.run(work_run)["result"]
                verdict, _ = await self.complete(client, job, ticket, "reviewer", kind, {
                    "ticket": ticket, "handoff": handoff,
                }, Verdict, lambda text: Verdict.model_validate(parse_json(text)))
                self.store.record_verdict(key, verdict.model_dump())
                if verdict.verdict == "fail":
                    self.store.mutate_job(key, job, status="in_progress", reason=" | ".join(verdict.reasons))
                elif "orchestrator" in self.enabled:
                    await self.decide(client, job, ticket, "verdict", handoff=handoff, verdict=verdict.model_dump())
                    self.store.record_verdict(key, verdict.model_dump())
                else:
                    self.store.mutate_job(key, job, status="done", reason=" | ".join(verdict.reasons))
        except asyncio.CancelledError:
            self.store.mutate_job(key, job, status="needs_human", reason="Dispatcher stopped during this job.")
            raise
        except Exception as error:
            LOGGER.warning("Ticket %s job %s failed: %s", key, kind, self.describe_error(error))
            self.store.mutate_job(key, job, status="needs_human", reason=self.describe_error(error))
        finally:
            self.store.release(key, job)

    @staticmethod
    def describe_error(error):
        if isinstance(error, httpx.HTTPStatusError):
            return f"Provider or MCP endpoint returned HTTP {error.response.status_code}."
        if isinstance(error, httpx.RequestError):
            return f"Provider or MCP connection failed ({type(error).__name__})."
        return (str(error) or type(error).__name__)[:2000]

    async def decide(self, client, job, ticket, phase, **context):
        key = ticket["id"]
        current = self.store.get(key)
        if not self.store.running(key, job):
            return
        summary = {field: current[field] for field in
                   ("id", "title", "description", "type", "status", "assignee", "acceptance", "attempts")}
        dependencies = [{"id": key, "status": self.store.get(key)["status"]} for key in current["depends_on"]]
        actions = CHOICES[phase].copy()
        if current["status"] != "backlog":
            actions.discard("split")
        elif any(item["status"] != "done" for item in dependencies):
            actions.discard("assign")
        decision, _ = await self.complete(client, job, current, "orchestrator", phase, {
            "ticket": summary, "dependencies": dependencies, "available_actions": sorted(actions),
            "available_workers": sorted(self.workers), **context,
        }, Decision, lambda text: self.available_decision(text, current, phase, actions), retries=1)
        self.store.apply_decision(key, job, decision, phase, passed=(phase == "verdict"))

    def available_decision(self, text, ticket, phase, actions):
        decision = validate_decision(text, ticket, phase, self.workers)
        if decision.action not in actions:
            raise ValueError("Choose an action available for the ticket's dependency states.")
        return decision

    async def complete(self, client, job, ticket, name, kind, context, schema, validate, retries=0):
        key, agent = ticket["id"], self.settings.agents[name]
        messages = [
            {"role": "system", "content": agent.system_prompt + "\nReturn only JSON matching this schema after any tool use:\n"
             + encode(schema.model_json_schema())},
            {"role": "user", "content": encode(context)},
        ]
        logged_ticket = {key: value for key, value in ticket.items() if key != "history"}
        record = {"id": uuid4().hex, "ticket": logged_ticket, "agent": name, "kind": kind,
                  "status": "running", "started": now(), "messages": messages, "tools": [],
                  "tool_calls": [], "tool_results": [], "reviewer_verdict": None,
                  "input_tokens": 0, "output_tokens": 0, "cost_usd": 0, "estimated_usage": False}
        self.store.save_run(key, record)
        tools = Tools(client, self.settings.root, agent, self.store, key, job)
        try:
            functions = [] if name == "orchestrator" else await tools.describe()
            record["tools"] = functions
            for _ in range(16):
                if not self.store.running(key, job):
                    raise Conflict("This job is no longer active.")
                payload = {"model": agent.model_id, "messages": messages}
                if functions:
                    payload["tools"] = functions
                estimated_input = approximate_tokens({"messages": messages, "tools": functions})
                remaining = agent.token_budget - self.store.used_tokens(key, name)
                maximum_output = min(4096, remaining - estimated_input)
                if maximum_output < 1:
                    raise Conflict(f"{name} has used its token budget for this ticket.")
                payload["max_tokens"] = maximum_output
                headers = {}
                if agent.api_key_env:
                    secret = os.getenv(agent.api_key_env)
                    if not secret:
                        raise Conflict(f"Set {agent.api_key_env} before enabling {name}.")
                    headers["Authorization"] = f"Bearer {secret}"
                response = await client.post(agent.base_url.rstrip("/") + "/chat/completions",
                                             json=payload, headers=headers)
                response.raise_for_status()
                body = response.json()
                source = body["choices"][0]["message"]
                message = {"role": "assistant", "content": source.get("content")}
                if source.get("tool_calls"):
                    message["tool_calls"] = [
                        {"id": call["id"], "type": "function", "function": {
                            "name": call["function"]["name"], "arguments": call["function"]["arguments"],
                        }} for call in source["tool_calls"]
                    ]
                messages.append(message)
                usage = body.get("usage") or {}
                reported_input, reported_output = usage.get("prompt_tokens"), usage.get("completion_tokens")
                has_usage = all(type(value) is int and value >= 0 for value in (reported_input, reported_output))
                input_tokens, output_tokens = ((reported_input, reported_output) if has_usage else
                                              (estimated_input, approximate_tokens(message)))
                cost = (input_tokens * agent.input_usd_per_million +
                        output_tokens * agent.output_usd_per_million) / 1_000_000
                record["input_tokens"] += input_tokens
                record["output_tokens"] += output_tokens
                record["cost_usd"] += cost
                record["estimated_usage"] |= not has_usage
                self.store.save_run(key, record, (input_tokens, output_tokens, cost))
                if input_tokens + output_tokens > remaining:
                    raise Conflict(f"{name} exceeded the ticket budget reported by the provider.")
                if "tool_calls" in message:
                    for call in message["tool_calls"]:
                        await self.execute_tool(key, record, tools, call)
                    continue
                try:
                    result = validate(message["content"])
                except (ValueError, TypeError) as error:
                    if not retries:
                        raise Conflict(f"{name} did not return valid {schema.__name__} JSON: {error}") from error
                    retries -= 1
                    record.setdefault("retry_messages", []).extend([len(messages) - 1, len(messages)])
                    messages.append({"role": "user", "content": "Invalid response. Return only corrected JSON. "
                                     + str(error)[:1500]})
                    continue
                if kind == "review":
                    record["reviewer_verdict"] = result.model_dump()
                record.update(status="completed", result=result.model_dump())
                return result, record
            raise Conflict(f"{name} reached the tool round limit.")
        except asyncio.CancelledError:
            record.update(status="interrupted", error="Dispatcher stopped.")
            raise
        except Exception as error:
            record.update(status="failed", error=self.describe_error(error))
            raise
        finally:
            record["finished"] = now()
            self.store.save_run(key, record)
            await tools.close()

    async def execute_tool(self, key, record, tools, call):
        name = call["function"]["name"]
        record["tool_calls"].append(call)
        self.store.save_run(key, record)
        arguments = parse_json(call["function"]["arguments"])
        if not isinstance(arguments, dict):
            raise Conflict("The model emitted tool arguments that are not a JSON object.")
        try:
            result = await tools.call(name, arguments)
        except (ToolError, Conflict, ValueError, OSError, httpx.HTTPError) as error:
            result = {"error": self.describe_error(error)}
        record["tool_results"].append({"tool_call_id": call["id"], "result": result})
        record["messages"].append({"role": "tool", "tool_call_id": call["id"], "content": encode(result)})
        self.store.save_run(key, record)
