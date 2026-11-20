import asyncio
from contextlib import suppress
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
from uuid import uuid4

import yaml

from .state import Conflict, Missing
from .store import encode, now
from .wsl_soup import CANCEL

DATASET = re.compile(r"[a-z][a-z0-9_-]{0,63}--[a-f0-9]{32}\.jsonl\Z")
ACTIVE = {"queued", "initializing", "validating", "training", "cancelling"}


def export_dataset(root, store, agent):
    rows = list(store.export(agent))
    if not rows:
        raise Conflict("No completed runs for this agent passed review without rejection.")
    directory = root / "datasets"
    directory.mkdir(parents=True, exist_ok=True)
    file = directory / f"{agent}--{uuid4().hex}.jsonl"
    with file.open("x", encoding="utf-8", newline="\n") as output:
        for row in rows:
            output.write(encode(row) + "\n")
    return file, len(rows)


def merge(base, overrides):
    for name, value in overrides.items():
        if isinstance(value, dict) and isinstance(base.get(name), dict):
            merge(base[name], value)
        else:
            base[name] = value


class Trainer:
    def __init__(self, settings):
        self.settings = settings
        self.directory = settings.root / "training-runs"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.jobs = {}
        self.task = None
        self.process = None
        self.cancel_requested = False

    def recover(self):
        for file in self.directory.glob("*/job.json"):
            job = json.loads(file.read_text(encoding="utf-8"))
            self.jobs[job["id"]] = job
            if job["status"] in ACTIVE:
                if job.get("runtime") == "wsl":
                    (file.parent / CANCEL).touch()
                self.update(job, "interrupted", "The service restarted.")

    def update(self, job, status, error=None):
        job.update(status=status, updated=now(), error=error)
        file = self.directory / job["id"] / "job.json"
        temporary = file.with_suffix(".tmp")
        temporary.write_text(encode(job) + "\n", encoding="utf-8")
        temporary.replace(file)

    def datasets(self):
        return [entry.name for entry in sorted((self.settings.root / "datasets").glob("*.jsonl"))
                if DATASET.fullmatch(entry.name) and entry.is_file() and not entry.is_symlink()]

    def get(self, identifier):
        if identifier not in self.jobs:
            raise Missing("Training job was not found.")
        return self.jobs[identifier]

    def start(self, agent, base, dataset, *, validate_only=False):
        if self.task and not self.task.done():
            raise Conflict("A training job is already active on this PC.")
        if agent not in self.settings.agents:
            raise Missing("Agent was not found.")
        if dataset not in self.datasets() or not dataset.startswith(agent + "--"):
            raise Conflict("Choose an exported dataset for this agent.")
        if not re.fullmatch(r"[\w.-]+(?:/[\w.-]+)?", base, re.ASCII) or any(
                part in {".", ".."} for part in base.split("/")):
            raise Conflict("Use a model ID such as Qwen/Qwen2.5-7B-Instruct.")
        configured = self.settings.soup
        use_wsl = bool(self.settings.soup_wsl_distro)
        if use_wsl and (os.name != "nt" or not configured.startswith("/") or not shutil.which("wsl.exe")):
            raise Conflict("WSL training requires Windows, wsl.exe and an absolute Linux SOUP_EXECUTABLE.")
        executable = configured if use_wsl else shutil.which(configured)
        if not executable and configured == "soup" and os.name == "nt":
            import sys
            candidate = Path(sys.executable).with_name("soup.exe")
            if candidate.is_file():
                executable = str(candidate)
        if not executable:
            raise Conflict("Install soup-cli[train] or set SOUP_EXECUTABLE in .env.")
        identifier = uuid4().hex
        output = self.settings.root / "models" / agent / identifier
        job_dir = self.directory / identifier
        job_dir.mkdir()
        (job_dir / "output.log").touch()
        job = {"id": identifier, "agent": agent, "base_model": base, "dataset": dataset, "validate_only": validate_only,
               "created": now(), "model_path": output.relative_to(self.settings.root).as_posix(),
               "runtime": "wsl" if use_wsl else "native"}
        self.update(job, "queued")
        self.jobs[identifier] = job
        self.cancel_requested = False
        self.task = asyncio.create_task(self.run(job, executable, output))
        return job

    async def command(self, job_dir, executable, *args):
        if self.cancel_requested:
            return
        env = dict(os.environ)
        for agent in self.settings.agents.values():
            for key in (agent.api_key_env, agent.mcp.api_key_env):
                if key:
                    env.pop(key, None)
        env.pop("TICKETS_TOKEN", None)
        env.update(PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8", NO_COLOR="1")
        options = ({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt"
                   else {"start_new_session": True})
        command = [executable, *args]
        if self.settings.soup_wsl_distro:
            wrapper = job_dir / ".soup-wsl.py"
            shutil.copyfile(Path(__file__).with_name("wsl_soup.py"), wrapper)
            command = ["wsl.exe", "--distribution", self.settings.soup_wsl_distro, "--cd", str(job_dir),
                       "--exec", "/usr/bin/python3", wrapper.name, *command]
        with (job_dir / "output.log").open("ab", buffering=0) as log:
            log.write(("$ soup " + " ".join(args) + "\n").encode("utf-8"))
            self.process = await asyncio.create_subprocess_exec(
                *command, cwd=job_dir, env=env,
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, **options)
            try:
                if self.cancel_requested:
                    await self.stop_job_process(job_dir, self.process)
                code = await self.process.wait()
                if code and not self.cancel_requested:
                    raise Conflict(f"Soup {args[0]} exited with code {code}. See the training log.")
            finally:
                self.process = None

    async def run(self, job, executable, output):
        job_dir = self.directory / job["id"]
        try:
            if self.cancel_requested:
                return
            self.update(job, "initializing")
            await self.command(job_dir, executable, "init", "--template", "tool-calling")
            if self.cancel_requested:
                return
            config_path = job_dir / "soup.yaml"
            config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            overrides = yaml.safe_load((self.settings.root / "training.yaml").read_text(encoding="utf-8"))
            merge(config, overrides)
            profile = self.settings.root / "training-profiles" / f"{job['agent']}.yaml"
            if profile.is_file():
                merge(config, yaml.safe_load(profile.read_text(encoding="utf-8")))
            shutil.copyfile(self.settings.root / "datasets" / job["dataset"], job_dir / "dataset.jsonl")
            relative_output = Path(os.path.relpath(output, job_dir)).as_posix()
            config.update(base=job["base_model"], output=relative_output)
            config["data"].update(train="./dataset.jsonl", format="tool-calling")
            with (job_dir / "dataset.jsonl").open(encoding="utf-8") as sample:
                if sum(1 for _ in zip(range(10), sample)) < 10:
                    config["data"]["val_split"] = 0.0
            config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
            self.update(job, "validating")
            await self.command(job_dir, executable, "data", "validate", "dataset.jsonl",
                               "--format", "tool-calling", "--min-valid-fraction", "1")
            if self.cancel_requested:
                return
            validate_only = job["validate_only"]
            self.update(job, "validating" if validate_only else "training")
            await self.command(job_dir, executable, "train", "--config", "soup.yaml",
                               "--dry-run" if validate_only else "--yes")
            if not self.cancel_requested:
                self.update(job, "validated" if validate_only else "completed")
        except Exception as error:
            if not self.cancel_requested:
                self.update(job, "failed", str(error))
        finally:
            if self.cancel_requested:
                self.update(job, "cancelled")

    @staticmethod
    async def stop_process(process):
        if process.returncode is not None:
            return
        if os.name == "nt":
            try:
                killer = await asyncio.create_subprocess_exec(
                    "taskkill.exe", "/PID", str(process.pid), "/T", "/F",
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW)
                await killer.wait()
            finally:
                if process.returncode is None:
                    with suppress(ProcessLookupError):
                        process.kill()
        else:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)

    async def stop_job_process(self, job_dir, process):
        if self.settings.soup_wsl_distro:
            (job_dir / CANCEL).touch()
            try:
                await asyncio.wait_for(process.wait(), timeout=15)
                return
            except TimeoutError:
                pass
        await self.stop_process(process)

    async def cancel(self, identifier):
        job = self.get(identifier)
        if job["status"] not in ACTIVE:
            raise Conflict("The training job has already ended.")
        self.cancel_requested = True
        self.update(job, "cancelling")
        if self.process:
            await self.stop_job_process(self.directory / identifier, self.process)
        return job

    async def shutdown(self):
        if self.task and not self.task.done():
            active = next(job for job in self.jobs.values() if job["status"] in ACTIVE)
            await self.cancel(active["id"])
            await self.task

    async def stream(self, identifier):
        job = self.get(identifier)
        file = self.directory / job["id"] / "output.log"
        with file.open(encoding="utf-8", errors="replace") as log:
            while True:
                content = log.read(16000)
                if content:
                    yield encode({"log": content}) + "\n"
                    continue
                yield encode({"job": job}) + "\n"
                if job["status"] not in ACTIVE:
                    break
                await asyncio.sleep(0.5)
