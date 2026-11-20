import asyncio
import json
import os
from pathlib import Path
import re

import httpx

from . import freecad
from .store import encode

MAX_TEXT = 24000
BUILTINS = {
    "read_text": ("Read a UTF-8 file in your permitted local directories.", {"path": {"type": "string"}}),
    "write_research_note": ("Create a new Markdown note under research/.",
                            {"path": {"type": "string"}, "content": {"type": "string"}}),
}


class ToolError(ValueError):
    pass


class Tools:
    def __init__(self, client, root, agent, store, ticket, job):
        self.client, self.root, self.agent, self.store = client, root, agent, store
        self.ticket, self.job = ticket, job
        self.session = None
        self.version = "2025-06-18"
        self.number = 0
        self.functions = {}
        self.discovered = set()
        self.destructive = set()

    def _headers(self):
        headers = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": self.version}
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        key_name = self.agent.mcp.api_key_env
        if key_name:
            key = os.getenv(key_name)
            if not key:
                raise ToolError(f"Set {key_name} before using this MCP endpoint.")
            headers["Authorization"] = f"Bearer {key}"
        return headers

    async def _rpc(self, method, params, notification=False):
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        if not notification:
            self.number += 1
            payload["id"] = self.number
        async with self.client.stream("POST", self.agent.mcp.endpoint, headers=self._headers(), json=payload) as reply:
            reply.raise_for_status()
            self.session = reply.headers.get("Mcp-Session-Id", self.session)
            if notification:
                return None
            if "text/event-stream" in reply.headers.get("content-type", ""):
                data = []
                async for line in reply.aiter_lines():
                    if line.startswith("data:"):
                        data.append(line[5:].lstrip())
                    if not line and data:
                        message = json.loads("\n".join(data))
                        data.clear()
                        if message.get("id") == self.number:
                            break
                else:
                    raise ToolError("MCP stream ended before its response.")
            else:
                await reply.aread()
                message = reply.json()
        if message.get("id") != self.number or "error" in message or "result" not in message:
            raise ToolError(f"MCP {method} did not return a successful JSON-RPC response.")
        return message["result"]

    def _add(self, name, description, schema):
        self.functions[name] = {"type": "function", "function": {
            "name": name, "description": description, "parameters": schema,
        }}

    async def describe(self):
        allowed = set(self.agent.allowed_mcp_tools)
        for name, (description, properties) in BUILTINS.items():
            if name in allowed:
                self._add(name, description, {"type": "object", "properties": properties,
                                              "required": list(properties), "additionalProperties": False})
        if freecad.NAME in allowed:
            self.functions[freecad.NAME] = freecad.schema()
        remote = (allowed & self.agent.mcp.tools.keys()) - BUILTINS.keys() - {freecad.NAME}
        if remote:
            if not self.agent.mcp.endpoint:
                raise ToolError("Configure the MCP endpoint for the allowed remote tools.")
            result = await self._rpc("initialize", {"protocolVersion": self.version, "capabilities": {},
                                                    "clientInfo": {"name": "Character Room Tickets", "version": "1"}})
            self.version = result["protocolVersion"]
            await self._rpc("notifications/initialized", {}, notification=True)
            params = {}
            for _ in range(20):
                page = await self._rpc("tools/list", params)
                for tool in page["tools"]:
                    name = tool["name"]
                    if name in remote and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name):
                        self._add(name, tool.get("description", ""), tool["inputSchema"])
                        self.discovered.add(name)
                        if (tool.get("annotations") or {}).get("destructiveHint") is True:
                            self.destructive.add(name)
                if not page.get("nextCursor"):
                    break
                params = {"cursor": page["nextCursor"]}
            if remote - self.discovered:
                raise ToolError("Configured MCP tools were unavailable: " + ", ".join(sorted(remote - self.discovered)))
        return list(self.functions.values())

    async def close(self):
        if self.session:
            try:
                await self.client.delete(self.agent.mcp.endpoint, headers=self._headers(), timeout=5)
            except (httpx.HTTPError, ValueError):
                # Session cleanup does not change the outcome of the run.
                pass

    def _path(self, value):
        if not isinstance(value, str) or not value or "\x00" in value:
            raise ToolError("Provide a file path.")
        candidate = (self.root / value).resolve()
        allowed = [(self.root / entry).resolve() for entry in self.agent.allowed_file_paths]
        if not any(candidate.is_relative_to(base) for base in allowed):
            raise ToolError("File is outside this agent's allowed paths.")
        return candidate

    async def _approve(self, name, args):
        identifier = self.store.approval(self.ticket, self.job, {"name": name, "arguments": args})
        try:
            async with asyncio.timeout(900):
                while self.store.running(self.ticket, self.job):
                    status = self.store.approval_status(identifier)
                    if status != "pending":
                        return status == "approved"
                    await asyncio.sleep(0.5)
        except TimeoutError:
            self.store.expire_approval(identifier)
        return False

    async def call(self, name, args):
        if name not in self.functions or not isinstance(args, dict):
            raise ToolError("The tool or its arguments are not allowed.")
        if not self.store.running(self.ticket, self.job):
            raise ToolError("This job is no longer active.")
        if name == freecad.NAME:
            project = self._path(f"freecad-project/{self.ticket}")
            stem = args.get("output")
            if not isinstance(stem, str) or not stem or Path(stem).is_absolute():
                raise ToolError("Choose a relative output stem inside this ticket's project.")
            output = (project / stem).resolve()
            if not output.is_relative_to(project) or output == project or ".work" in output.relative_to(project).parts:
                raise ToolError("The output stem is outside the ticket's model directory.")
            result = await asyncio.to_thread(freecad.generate, project, args)
            return {**result, "files": [(project / file).relative_to(self.root).as_posix()
                                         for file in result["files"]]}
        if name in BUILTINS:
            if set(args) != set(BUILTINS[name][1]):
                raise ToolError("Unexpected arguments.")
            file = self._path(args["path"])
            if name == "read_text":
                if not file.is_file():
                    raise ToolError("Choose an existing regular file.")
                with file.open(encoding="utf-8") as source:
                    return {"text": source.read(MAX_TEXT), "truncated": bool(source.read(1))}
            research = self.root / "research"
            if not file.is_relative_to(research) or file.suffix.lower() != ".md":
                raise ToolError("Write new .md files inside research/.")
            content = args["content"]
            if not isinstance(content, str) or not 0 < len(content) <= MAX_TEXT:
                raise ToolError("Supply a nonempty note of at most 24,000 characters.")
            file.parent.mkdir(parents=True, exist_ok=True)
            with file.open("x", encoding="utf-8") as destination:
                destination.write(content)
            return {"path": file.relative_to(self.root).as_posix()}
        rule = self.agent.mcp.tools[name]
        args = args.copy()
        for field in rule.path_arguments:
            if field in args:
                args[field] = str(self._path(args[field]))
        if (rule.effect == "destructive" or name in self.destructive) and not await self._approve(name, args):
            raise ToolError("The call was not approved.")
        if not self.store.running(self.ticket, self.job):
            raise ToolError("This job is no longer active.")
        result = await self._rpc("tools/call", {"name": name, "arguments": args})
        serialized = encode(result)
        return result if len(serialized) <= MAX_TEXT else {"preview": serialized[:MAX_TEXT], "truncated": True}
