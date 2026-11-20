import asyncio
from contextlib import asynccontextmanager, suppress
from pathlib import Path
import secrets
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import Field

from .schema import AgentName, StrictModel, TicketEdit, TicketFields, TicketId, Transition
from .state import Conflict, Missing
from .store import Store
from .training import Trainer, export_dataset
from .worker import Worker

UI = Path(__file__).parent / "ui"


class ApprovalDecision(StrictModel):
    decision: Literal["approved", "denied"]


class TrainingRequest(StrictModel):
    agent: AgentName
    base_model: str = Field(min_length=1, max_length=200)
    dataset: str = Field(min_length=1, max_length=120)
    validate_only: bool = False


def create_app(settings):
    if len(settings.token) < 24 or not settings.token.isascii() or any(c.isspace() for c in settings.token):
        raise ValueError("Set TICKETS_TOKEN in .env to at least 24 ASCII characters with no spaces.")
    store = Store(settings.root / "data" / "tickets.sqlite3", settings.root / "data" / "runs")
    trainer = Trainer(settings)
    worker = Worker(settings, store)

    @asynccontextmanager
    async def lifespan(app):
        store.recover()
        trainer.recover()
        task = asyncio.create_task(worker.run()) if settings.dispatch else None
        try:
            yield
        finally:
            if task:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            await trainer.shutdown()

    app = FastAPI(title="Character Room Tickets", docs_url=None, redoc_url=None, openapi_url=None,
                  lifespan=lifespan, redirect_slashes=False)

    @app.middleware("http")
    async def authenticate(request: Request, call_next):
        authorization = request.headers.get("authorization", "").encode("latin-1")
        expected = b"Bearer " + settings.token.encode("ascii")
        nonce = secrets.token_urlsafe(24)
        if secrets.compare_digest(authorization, expected):
            response = await call_next(request)
        elif request.method == "GET" and request.url.path == "/":
            page = (UI / "login.html").read_text(encoding="utf-8").replace("{{NONCE}}", nonce)
            response = HTMLResponse(page, status_code=401)
        else:
            response = JSONResponse({"detail": "A valid ticket bearer token is required."}, status_code=401)
        if response.status_code == 401:
            response.headers["WWW-Authenticate"] = 'Bearer realm="Character Room Tickets"'
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; "
            "connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'"
        )
        return response

    @app.exception_handler(Conflict)
    async def conflict(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(Missing)
    async def missing(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.get("/", response_class=HTMLResponse)
    @app.get("/ui", response_class=HTMLResponse)
    def interface():
        return (UI / "board.html").read_text(encoding="utf-8")

    @app.get("/ui.js")
    def javascript():
        return FileResponse(UI / "board.js", media_type="text/javascript")

    @app.get("/ui.css")
    def stylesheet():
        return FileResponse(UI / "board.css", media_type="text/css")

    @app.get("/api/settings")
    def configuration():
        return {"dispatch": settings.dispatch, "agents": {
            name: {"enabled": agent.enabled, "model": agent.model_id,
                   "training_base_model": agent.training_base_model} for name, agent in settings.agents.items()
        }}

    @app.get("/api/tickets")
    def list_tickets():
        return store.list()

    @app.post("/api/tickets", status_code=201)
    def create_ticket(fields: TicketFields):
        return store.create(fields)

    @app.get("/api/tickets/{key}")
    def ticket(key: TicketId):
        return store.get(key)

    @app.put("/api/tickets/{key}")
    def edit_ticket(key: TicketId, fields: TicketEdit):
        return store.edit(key, fields)

    @app.post("/api/tickets/{key}/transition")
    def transition(key: TicketId, fields: Transition):
        return store.transition(key, fields.status, fields.reason)

    @app.post("/api/tickets/{key}/triage", status_code=202)
    def triage(key: TicketId):
        if not settings.dispatch or "orchestrator" not in worker.enabled:
            raise Conflict("Enable the dispatcher and orchestrator before queuing triage.")
        store.request_triage(key)
        return {"queued": True}

    @app.get("/api/tickets/{key}/runs")
    def runs(key: TicketId):
        return store.runs(key)

    @app.get("/api/approvals")
    def approvals():
        return store.approvals()

    @app.post("/api/approvals/{identifier}")
    def approve(identifier: str, fields: ApprovalDecision):
        store.decide_approval(identifier, fields.decision)
        return {"decision": fields.decision}

    @app.post("/api/datasets/{agent}", status_code=201)
    def build_dataset(agent: AgentName):
        if agent not in settings.agents:
            raise Missing("Agent was not found.")
        file, rows = export_dataset(settings.root, store, agent)
        return {"dataset": file.name, "rows": rows}

    @app.get("/api/datasets")
    def datasets():
        return trainer.datasets()

    @app.get("/api/datasets/{dataset}")
    def download_dataset(dataset: str):
        if dataset not in trainer.datasets():
            raise Missing("Dataset was not found.")
        return FileResponse(settings.root / "datasets" / dataset, media_type="application/x-ndjson",
                            filename=dataset)

    @app.get("/api/training")
    async def training_jobs():
        return sorted(trainer.jobs.values(), key=lambda job: job["created"], reverse=True)

    @app.post("/api/training", status_code=202)
    async def start_training(fields: TrainingRequest):
        return trainer.start(fields.agent, fields.base_model, fields.dataset, validate_only=fields.validate_only)

    @app.post("/api/training/{identifier}/cancel")
    async def cancel_training(identifier: str):
        return await trainer.cancel(identifier)

    @app.get("/api/training/{identifier}/stream")
    async def stream_training(identifier: str):
        trainer.get(identifier)
        return StreamingResponse(trainer.stream(identifier), media_type="application/x-ndjson")

    return app
