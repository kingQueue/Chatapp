# Character Room Tickets

Tickets is a local workspace for robotics work in Character Room. Character Room serves the board and API at `/tickets/` on the same address as its homepage. The ticket code, worker configuration and data live in this project directory.

## Start on the PC

If Tickets is already installed, open **Start Character Room.cmd** and select **Tickets** at the top of the homepage. Enter the value of `TICKETS_TOKEN` from this project's `.env`. The token stays in the tab's memory, so reloading or selecting **Lock** asks for it again.

To set up a fresh copy in PowerShell:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe install_character_room.py "C:\path\to\CharacterRoom"
```

The installer creates `.env` with a random token if the file is absent and updates the Character Room launcher to use this Python environment. Restart Character Room after installation. The desktop URL is `http://127.0.0.1:8765/` by default.

To populate an empty board with three linked example tickets, run `.venv\Scripts\python.exe seed.py`.

## Open it from your phone

On trusted home Wi-Fi, use **Enable phone access** in Character Room settings. Open the address shown there, sign into Character Room, then tap **Tickets** and enter the ticket token. If Windows Firewall blocks the connection, run Character Room's **Allow Phone Access.cmd** to authorize the installed Python runtime on your local subnet.

For remote access, use Tailscale subnet routing to reach the Character Room phone-access address from an authorized tailnet device. Route only the required LAN address and restrict access in your tailnet policy. Keep router port forwarding and Tailscale Funnel off. [Tailscale subnet routing documentation](https://tailscale.com/docs/features/subnet-routers)

The initial link returns a 401 bearer challenge with an unlock form. The board, assets and every API call require the `Authorization: Bearer <token>` header. The token goes in the header rather than a URL or cookie.

## Tickets and agent work

- **Board and editor** group cards by status, with search and status filters. Open a card to edit fields, acceptance criteria, relationships and metadata. History is append-only and agent run logs are viewable in the ticket.
- **State machine** follows backlog → ready → in progress → review → done. In-progress work can become blocked. A rejection returns work to in progress if another attempt is available. Any status can be escalated to Needs human. A third attempt can pass review, and a third rejection escalates. Blocked and Needs human tickets remain in their recorded state. Create a linked follow-up to resume work.
- **Dependency checks** require every dependency to be done before a card can enter Ready. Invalid transitions, missing references, cycles and outdated edits return clear errors.
- **Needs human** shows escalated tickets and pending destructive tool requests. Approve or deny the specific call and arguments. A pending approval expires when the job ends or after 15 minutes.
- **Dispatcher** selects ready work with an enabled assignee or asks the orchestrator to assign an unassigned ticket. Use **Queue triage** on a backlog ticket to let the orchestrator assign, split or escalate it. A split creates linked backlog subtasks. Complete them before moving the parent to Ready.
- **Handoff and review** require the worker to report work done, produced files, open issues and what the next agent needs. The orchestrator sees the handoff and ticket summary. The reviewer checks acceptance criteria and returns a verdict with reasons. The dispatcher validates each requested state change.

## Configure agents

In `agents.yaml`, set `enabled: true` for agents you want to run. Set `TICKETS_DISPATCH=true` in `.env` and restart Character Room. Manual use works with dispatch off, which is the initial setting.

Set each agent's `base_url` to an OpenAI-compatible endpoint ending in `/v1`, and set its `model` to the name served there. For a metered provider, put the API key in `.env`, reference the variable name via `api_key_env`, and set input/output USD per million tokens in `agents.yaml`. For local Ollama or llama.cpp, use the local service URL and a tool-capable model for tool agents. Provider usage is used when available. Otherwise the app marks token usage and cost as estimates. The token budget is cumulative per agent and ticket, including previous attempts.

| Agent | Configuration |
| --- | --- |
| `orchestrator` | Validates assignment, split, handoff, escalation and close decisions. Retries invalid JSON once before escalation. |
| `cad_agent` | Uses the local FreeCAD adapter and Qwen3-Coder 30B. Optionally configure Photocraft in `mcp.endpoint` and `mcp.tools` with tool effects and any path arguments. See [FreeCAD Designer](FREECAD.md). |
| `research_agent` | Reads local UTF-8 references from allowed directories and creates new Markdown notes in `research/`. Add reference directories to its allowlist as needed. |
| `reviewer` | Returns pass or fail and reasons against acceptance criteria. Grant read access to artifact directories it should inspect. |

`allowed_file_paths` accepts project-relative or absolute allowlisted directories on the PC. Remote MCP servers enforce their own filesystem permissions. Register only trusted tools and classify destructive actions accordingly. Prompts, ticket context and tool results are sent to the endpoint chosen for the agent. JSONL traces may contain your project data.

## Training with Soup

Install the training runtime in the environment that will execute Soup:

```powershell
.venv\Scripts\python.exe -m pip install "soup-cli[train]==0.78.0"
```

If using another environment, point `SOUP_EXECUTABLE` in `.env` at its executable. Consult the Soup installation guide for the GPU backend supported by your hardware. [Soup project and installation](https://github.com/MakazhanAlpamys/Soup)

1. In **Training**, select an agent and click **Export reviewed runs**. Or run `python -m ticketing export research_agent`. Each dataset contains completed runs from done tickets that received a passing reviewer verdict and had no rejection. Rows preserve the OpenAI-style messages, tool schemas, calls and results.
2. Enter a base model ID, select that agent's dataset and click **Start training**. The service initializes the Soup tool-calling template, applies the editable settings in `training.yaml` and validates every row with Soup before invoking training.
3. Select a job to watch its status and live log. **Cancel training** terminates the active subprocess. One training job runs at a time. Training settings start at 4-bit LoRA, batch size 1 and a 2,048-token context for the assumed 24–32 GB VRAM and 64 GB RAM.
4. Outputs go under `models/<agent>/<version>/`. Record the version path in the agent's optional `model_path` entry, load the artifact in your inference server, then set `base_url` and `model` to that server's advertised endpoint and model name. If the server advertises the artifact path itself as its model ID, omit `model` to send `model_path` as the ID.

## Layout and verification

| Location | Contents |
| --- | --- |
| `ticketing/` | FastAPI app, state machine, SQLite store, worker, MCP client, training runner and build-free UI |
| `integration/`, `install_character_room.py` | Character Room top tab and in-process FastAPI integration |
| `agents.yaml`, `training.yaml`, `.env.example` | Agent permissions, training defaults and local settings |
| `data/tickets.sqlite3`, `data/runs/` | Ticket database and per-run JSONL records, including reviewer verdicts |
| `datasets/`, `training-runs/`, `models/` | Exports, job configs and logs, and trained artifacts |
| `seed.py`, `tests/` | Seed tickets and regression tests |

Run `.venv\Scripts\python.exe -m unittest discover -s tests -v`. Tests use disposable databases and mock provider responses.
