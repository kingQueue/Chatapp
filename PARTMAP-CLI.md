# Partmap CLI and character dispatcher

`parts_cli.py` is a Python-standard-library command-line interface for the same Partmap project JSON used by **Open Partmap**. Run it from this Character Room folder. It needs Python 3.10+, with no Ollama SDK or additional packages.

```powershell
python .\parts_cli.py --workspace "C:\Projects\rover" validate --path parts.json
python .\parts_cli.py --workspace "C:\Projects\rover" analyze --path parts.json
python .\parts_cli.py --workspace "C:\Projects\rover" read --path parts.json
python .\parts_cli.py --workspace "C:\Projects\rover" export --path parts.json --format csv --output exports\parts.csv
python .\parts_cli.py --workspace "C:\Projects\rover" export --path parts.json --format markdown --output exports\handoff.md
```

The workspace must already exist and be separate from Character Room's installation/data. All source, input and output files stay inside it. Existing output files require `--expected-sha256 HASH`, obtained by reading the file first. Exports cannot overwrite the source project. Without `--output`, export returns its content in the stdout JSON object.

Create a new project from an existing JSON input file inside the workspace:

```powershell
python .\parts_cli.py --workspace "C:\Projects\rover" write --path parts.json --input proposed-parts.json
```

`write --input -` reads the project object from standard input. When updating an existing project, pass `--expected-sha256` from `read`. Writes are validated and read back from disk. The project uses `schemaVersion: "1.0"`, `name`, and `nodes`; each node needs `id`, `name`, `category`, `quantity`, and `parent` (null for a root). Supported categories are board, sensor, motor, power, peripheral, printed, fastener and mechanical. Pins, connections, hardware/firmware notes, hierarchy, and readiness use the existing Partmap fields. Embedded attachments are unsupported by the shared-file bridge.

Commands emit one machine-readable JSON object to stdout: `{ "ok": true, "command": "analyze", "result": {...} }`. Errors emit `{ "ok": false, "error": "..." }` and exit with status 1. `validate` checks project structure and references. `analyze` summarizes categories, quantities, readiness and wiring and reports unlisted pin references; it does not certify electrical compatibility. CSV export protects cells that would otherwise be interpreted as spreadsheet formulas.

## Connecting characters

In **Settings → Manage tools**, keep the **Partmap hardware studio** adapter pointed at the original Partmap `dist` folder. Grant that tool to a character, then assign a project directory to the chat. Existing Partmap grants automatically expose the CLI operations. The CLI is bundled with Character Room, so its location is fixed; the configured `dist` location is used for the visual studio.

The model sees these operations (the prefix follows the registered tool ID):

| Operation | Arguments | Effect |
| --- | --- | --- |
| `partmap__parts_read` | `path` | CLI reads and validates project JSON, returning its SHA-256. |
| `partmap__parts_write` | `path`, `project`, optional `expected_sha256` | CLI creates/updates project JSON and verifies saved bytes. |
| `partmap__custom_app_run` | `command`, optional `args` string array | CLI `validate`, `analyze`, or `export`. |

Example model tool request, compatible with the supplied dispatcher pattern:

```json
{"command":"export","args":["--path","parts.json","--format","csv","--output","exports/parts.csv"]}
```

`args` contains individual option/value strings, not a shell command. A character cannot change the workspace, substitute an executable, or launch another command through this operation. For scripts calling the CLI directly, `--request` accepts `{"command":"write","arguments":{"path":"parts.json","project":{"name":"Rover","nodes":[]}}}` on stdin; the character dispatcher reserves this internal mode.

## Windows application dispatcher

`ToolService.dispatch` in `tool_runtime.py` is the central dispatcher. It checks the character's current grants, the global tool switch, the registered adapter and its allowed operations, and the assigned project directory before executing anything. It launches the fixed Partmap CLI with `shell=False`, a timeout, UTF-8 JSON input/output, and Python isolated mode. Arguments are never evaluated as code. The existing Ollama loop supplies only granted schemas, executes returned tool requests through this dispatcher, and sends actual results back to the same model, using native or Gemma-compatible JSON tool calling.

The other configured applications use the same dispatcher: VS Code opens existing project files, local Git supports status/diff/log/init/stage/commit with hooks disabled, and FreeCAD creates native/STEP/STL models from structured geometry. File editing uses the file adapter. Arbitrary terminal commands, model-written FreeCAD macros and remote Git commands are not added by this CLI integration. Character grants in the UI remain the authorization mechanism; no blocking terminal `input()` prompt is needed for the background app or phone clients.

All model-triggered calls appear in **Tool activity** and the reply's **App-verified tool record**, including CLI export paths and write verification. Partmap continues to load/save the same project file, so CLI changes appear in its viewer. Standalone manual CLI calls do not impersonate a character or add chat audit records.
