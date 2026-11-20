"""Install the embedded Tickets workspace into an existing Character Room."""
import argparse
import os
from pathlib import Path
import secrets
import sys
from uuid import uuid4

from ticketing.config import ROOT, load_settings


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError("This Character Room build has an unexpected layout. No app files were updated.")
    return source.replace(old, new, 1)


def write_atomically(path, text, encoding="utf-8"):
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        temporary.write_text(text, encoding=encoding)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("room", type=Path)
    args = parser.parse_args()
    room = args.room.resolve()
    server_file = room / "server.py"
    index_file = room / "static" / "index.html"
    server = server_file.read_text(encoding="utf-8")
    index = index_file.read_text(encoding="utf-8")
    if "import ticket_proxy\n" in server:
        server = server.replace("ticket_proxy", "ticket_embed")
    elif "import ticket_embed\n" not in server:
        server = replace_once(server, "import tool_runtime\n", "import tool_runtime\nimport ticket_embed\n")
        for method in ("GET", "POST"):
            anchor = f"    def do_{method}(self):\n"
            server = replace_once(server, anchor, anchor + "        if ticket_embed.handle(self):\n            return\n")
        insert = ("    def do_PUT(self):\n        if not ticket_embed.handle(self):\n"
                  "            self.send_error(501, 'Unsupported method')\n\n")
        server = replace_once(server, "    def do_POST(self):\n", insert + "    def do_POST(self):\n")
    if "with ticket_embed.running():" not in server:
        # Start before the phone listener and stop after both existing listeners close.
        anchor = "    if not args.db:AUTO_WIRE.register(args.port)\n"
        if anchor not in server:
            anchor = "    try:\n        config = json.loads((DB_PATH.parent / 'network.json')"
        first = server.index(anchor)
        last = server.index("\n\nif __name__", first)
        section = server[first:last]
        scoped = "".join("    " + line if line.strip() else line for line in section.splitlines(keepends=True))
        server = server[:first] + "    with ticket_embed.running():\n" + scoped + server[last:]

    old_link = ('  <a class="nav" id="tickets-nav" href="/tickets/" target="_blank" '
                'rel="noopener noreferrer"><span aria-hidden="true">▤</span> Tickets</a>\n')
    index = index.replace(old_link, "")
    if 'id="tickets-tab"' not in index:
        tabs = ('<nav class="room-tabs" aria-label="Character Room sections">'
                '<a href="/" aria-current="page">Characters</a>'
                '<a href="/tickets/" id="tickets-tab">Tickets</a></nav>')
        index = replace_once(index, '<header class="topbar"><span>Your characters, your stories.</span>',
                             '<header class="topbar">' + tabs)
    compile(server, str(server_file), "exec")

    stylesheet = room / "static" / "style.css"
    css = stylesheet.read_text(encoding="utf-8")
    if "/* Character Room section tabs */" not in css:
        css += """
/* Character Room section tabs */
.room-tabs{display:flex;align-items:center;gap:4px;font-size:clamp(12px,1.5vw,14px)}
.room-tabs a{display:inline-flex;align-items:center;min-height:44px;padding:0 12px;border-radius:9px;
  color:var(--muted);text-decoration:none;font-weight:600;white-space:nowrap}
.room-tabs a[aria-current="page"]{background:#30283f;color:#dbccf8}
.room-tabs a:hover,.room-tabs a:focus-visible{color:#ede5ff;background:#30283f}
@media(max-width:430px){.room-tabs a{padding:0 9px}}
"""

    firewall = room / "Allow Phone Access.ps1"
    firewall_source = firewall.read_text(encoding="utf-8") if firewall.is_file() else None
    if firewall_source and "ticketing-python.txt" not in firewall_source:
        firewall_source = replace_once(
            firewall_source, "$pythonPath = (Get-Command python.exe).Source\n",
            "$runtimeFile = Join-Path $PSScriptRoot 'ticketing-python.txt'\n"
            "$pythonPath = if (Test-Path -LiteralPath $runtimeFile) {\n"
            "    (Get-Content -LiteralPath $runtimeFile -Raw -Encoding UTF8).Trim()\n"
            "} else { (Get-Command python.exe).Source }\n")
        firewall_source = replace_once(
            firewall_source, "    if (-not (Get-NetFirewallRule",
            "    if (Test-Path -LiteralPath $runtimeFile) { $ruleName += '-embedded' }\n"
            "    if (-not (Get-NetFirewallRule")

    if not (ROOT / ".env").exists():
        example = (ROOT / ".env.example").read_text(encoding="utf-8")
        with (ROOT / ".env").open("x", encoding="utf-8") as file:
            file.write(example.replace("TICKETS_TOKEN=", "TICKETS_TOKEN=" + secrets.token_urlsafe(32), 1))
    settings = load_settings()
    if len(settings.token) < 24 or not settings.token.isascii() or any(c.isspace() for c in settings.token):
        raise ValueError("Configure a valid ticket token in .env first.")
    python = str(Path(sys.executable)).replace("%", "%%")
    windowless = Path(sys.executable).with_name("pythonw.exe")
    command = (f'start "" "{str(windowless).replace("%", "%%")}" "%~dp0server.py" --open %*\n'
               if windowless.is_file() else f'"{python}" "%~dp0server.py" --open %*\n')
    launcher = ("@echo off\n"
                'cd /d "%~dp0"\n' + command)
    embed_source = ("from integration.ticket_embed import handle, running\n" if room == ROOT else
                    (ROOT / "integration" / "ticket_embed.py").read_text(encoding="utf-8"))
    write_atomically(room / "ticket_embed.py", embed_source)
    write_atomically(room / "ticketing-project.txt", str(ROOT) + "\n")
    write_atomically(room / "ticketing-python.txt", sys._base_executable + "\n")
    write_atomically(room / "Start Character Room.cmd", launcher)
    if firewall_source is not None:
        write_atomically(firewall, firewall_source)
    write_atomically(server_file, server)
    write_atomically(index_file, index)
    write_atomically(stylesheet, css)
    old_launcher = room / "Start Ticket Service.cmd"
    if old_launcher.is_file() and "-m ticketing" in old_launcher.read_text(encoding="utf-8"):
        old_launcher.unlink()
    old_proxy = room / "ticket_proxy.py"
    if old_proxy.is_file() and "Same-origin bridge from Character Room" in old_proxy.read_text(encoding="utf-8"):
        old_proxy.unlink()
        (room / "ticketing-port.txt").unlink(missing_ok=True)
    print(f"Installed embedded Tickets in {room}. Restart Character Room to load the top tab.")


if __name__ == "__main__":
    main()
