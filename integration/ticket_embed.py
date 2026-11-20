"""Run the Tickets ASGI application inside Character Room's HTTP server."""
from contextlib import ExitStack, contextmanager
import logging
from pathlib import Path
import sys
from urllib.parse import unquote, urlsplit


LOGGER = logging.getLogger(__name__)
_runtime = None
_error = "Tickets are starting up."


@contextmanager
def running():
    global _runtime, _error
    with ExitStack() as stack:
        try:
            parent = Path(__file__).resolve().parent
            default_root = parent.parent if parent.name == "integration" else parent
            locator = default_root / "ticketing-project.txt"
            project = locator.read_text(encoding="utf-8").strip() if locator.is_file() else str(default_root)
            if project not in sys.path:
                sys.path.insert(0, project)
            from anyio.from_thread import start_blocking_portal
            from ticketing.app import create_app
            from ticketing.config import load_settings

            app = create_app(load_settings())
            portal = stack.enter_context(start_blocking_portal(name="character-room-tickets"))
            stack.enter_context(portal.wrap_async_context_manager(app.router.lifespan_context(app)))
        except Exception:
            stack.close()
            _error = "Tickets could not start. Check the Character Room console and ticket configuration."
            LOGGER.exception("Tickets startup failed")
        else:
            _runtime = (portal, app)
        try:
            yield
        finally:
            _runtime = None


def handle(handler):
    target = urlsplit(handler.path)
    if target.path != "/tickets" and not target.path.startswith("/tickets/"):
        return False
    if not handler.valid_host():
        handler.output({"detail": "Invalid host."}, 403)
        return True
    if not handler.authenticated():
        handler.output({"detail": "Sign into Character Room first."}, 401)
        return True
    if target.path == "/tickets":
        handler.send_response(307)
        handler.send_header("Location", "/tickets/")
        handler.send_header("Content-Length", "0")
        handler.end_headers()
        return True
    if handler.headers.get("Transfer-Encoding"):
        handler.output({"detail": "Use a fixed-length request body."}, 400)
        return True
    try:
        size = int(handler.headers.get("Content-Length", "0"))
        if size < 0:
            raise ValueError("Negative content length")
    except ValueError:
        handler.output({"detail": "Invalid content length."}, 400)
        return True
    if size > 4 * 1024 * 1024:
        handler.output({"detail": "Ticket request body is too large."}, 413)
        return True
    runtime = _runtime
    if runtime is None:
        handler.output({"detail": _error}, 503)
        return True

    body = handler.rfile.read(size) if size else b""
    if len(body) != size:
        return True
    path = target.path.removeprefix("/tickets")
    scope = {
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "type": "http", "method": handler.command, "scheme": "http",
        "http_version": handler.request_version.removeprefix("HTTP/"),
        "root_path": "", "path": unquote(path), "raw_path": path.encode("latin-1"),
        "query_string": target.query.encode("latin-1"),
        "headers": [(name.lower().encode("ascii"), value.encode("latin-1"))
                    for name, value in handler.headers.items()],
        "client": handler.client_address, "server": handler.server.server_address,
    }
    portal, app = runtime
    try:
        portal.call(serve, app, scope, body, handler)
    except OSError:
        # A browser may disconnect while reading a training log.
        pass
    except Exception:
        LOGGER.exception("Tickets request failed")
    return True


async def serve(app, scope, body, handler):
    import asyncio

    pending_request = True
    response_finished = asyncio.Event()

    async def receive():
        nonlocal pending_request
        if pending_request:
            pending_request = False
            return {"type": "http.request", "body": body, "more_body": False}
        await response_finished.wait()
        return {"type": "http.disconnect"}

    def write(message):
        if message["type"] == "http.response.start":
            handler.send_response(message["status"])
            for name, value in message["headers"]:
                handler.send_header(name.decode("ascii"), value.decode("latin-1"))
            handler.send_header("Connection", "close")
            handler.close_connection = True
            handler.end_headers()
        elif message.get("body") and handler.command != "HEAD":
            handler.wfile.write(message["body"])

    async def send(message):
        await asyncio.to_thread(write, message)
        if message["type"] == "http.response.body" and not message.get("more_body", False):
            response_finished.set()

    try:
        await app(scope, receive, send)
    finally:
        response_finished.set()
