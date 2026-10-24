# Character Room

A small, private character chat app that runs on your PC. No npm install, Python packages, accounts, or API keys are needed.

## Open the app

Double-click **Start Character Room.cmd** in this folder. It starts the local server, starts Ollama if needed, and opens http://127.0.0.1:8765 in your browser. Clicking the launcher again opens the existing app.

Requires Python 3.10+ and [Ollama](https://ollama.com). Download a model first with `ollama pull qwen3:8b`, or select another downloaded local model under **Settings & backup**. The default is `qwen3:8b`. Cloud models are excluded. The app only contacts Ollama on 127.0.0.1:11434; there are no analytics, external assets, or hosted APIs.

## Make a character

Choose **Create character**. Add a name, a background story, and comma-separated personality tags. You can also set an avatar symbol, color, speaking style, starting scene, and first message. These fields guide every generated reply. Three editable characters are included to get you started.

**Start a conversation** opens a chat; **Continue conversation** resumes the most recent chat with that character. Use **New chat** for another independent conversation. The sidebar lets you return to earlier conversations. You can rename, export, or delete a conversation. Deleting a character also deletes its conversations, after confirmation.

## Character models and specialties

In **Edit character → Model & specialty**, choose any downloaded local Ollama chat model for that character. **Use app default** follows the model selected in Settings & backup. An explicit model choice overrides that default in both individual and group chats. Add an optional **Task specialty** (for example: planning, code review, creative drafting, or checking assumptions) to guide the character alongside their background, tags, and speaking style. A specialty describes their focus; the underlying model determines its capabilities.

The dropdown refreshes from Ollama. It does not download models or connect to cloud providers. Model changes affect future replies; each new saved reply records the model actually used. If a chosen model is missing, select another model and retry the saved message or unfinished group round.

## Group collaboration

Choose **New group** or **Create a group**, give the team a name and a shared task, select **2–6 existing characters**, and arrange their speaking order. Put a reviewer or coordinator last if you want them to bring the contributions together. Groups appear in the library and recent conversations, including on a phone.

Send a message, or use **Start round** to begin with the shared task. Each member contributes once, in order, through its own selected model. Later members receive earlier contributions labeled with the speaker’s name and ID. **Continue round** asks for another pass. Characters can use explicitly granted project tools as described below. Web browsing is not included.

**Team details** shows members, specialties, current models, and controls to edit each character. **Shared task & memory** is sent to every member. Recent context is bounded to about 16,000 characters, while the active user task is retained even in a long round. All messages stay saved locally. Each reply shows its character and actual model, and read-aloud uses that character’s voice. Automatic speech queues enabled characters’ contributions after the round finishes.

Completed contributions are saved immediately. If a later member fails, **Retry reply** resumes the unfinished members without duplicating the user message or completed contributions, including after an app restart. New messages are blocked until the unfinished round is resumed or the conversation is deleted. Changing a missing model in the character editor allows the retry to proceed.

Group membership and speaking order are fixed for each conversation. **New chat** lets you create another group using the same members and task as a starting point. Delete the old group if you no longer need it. A character belonging to a group cannot be deleted until those group conversations are deleted, so shared history cannot be accidentally removed by deleting one member. Character profile edits and model changes still apply to future turns.

## Windows tools and project folders

On the PC, open **Settings & backup → Manage tools** to register a supported adapter, name it, and choose its installed executable or application folder. **Detect location** finds common VS Code, Git, and FreeCAD installations. Built-in file tools need no program location. You can disable a tool globally at any time. Registering a location alone grants no character access.

In **Edit character → Tool permissions**, check only the tools that character may use. Then select an existing project folder when creating a group, or assign one under the chat's **Team details / Character details → Project directory**. Each character's grants apply independently within a group. Without an assigned folder, no project tools are offered. Choose a dedicated work folder separate from Character Room, installed applications, and private app data. Folder selection and permission changes are PC-only; phones can chat using the permissions already granted on the PC.

Supported operations:

- **Read/write files:** list folders, read paginated UTF-8 text, create text/code files, and replace existing files using the SHA-256 from a preceding read. Conflicting edits fail instead of overwriting another contributor's work. Text files are limited to 300 KB.
- **Visual Studio Code:** open an existing project file in the installed `Code.exe`. Characters edit code through the file tools; this adapter does not run code, a terminal, or VS Code tasks. Grant read/write separately when needed. This supports VS Code, not the separate Visual Studio IDE.
- **Local Git:** initialize a repository, inspect status/diffs/recent commits, stage explicit files, and commit. Hooks, external diff programs, remote operations, resets, checkout, linked worktrees, and repositories with execution-capable filter/include configuration are unavailable.
- **Partmap hardware studio:** choose the existing Partmap `dist` folder containing `index.html`, `app.js`, `studio.js`, and `style.css`. Characters read/write validated project JSON through the bundled CLI and can call `custom_app_run` to analyze, validate, or export JSON/CSV/Markdown. **Open Partmap** opens that same file in the studio, with saves back to the assigned folder and periodic refreshes of bot edits. Embedded attachments are unsupported in shared JSON; keep supporting files separately in the project. The original Partmap app files remain unchanged. See [PARTMAP-CLI.md](PARTMAP-CLI.md) for commands and dispatcher details.
- **FreeCAD:** select `freecadcmd.exe`. Characters create native parametric `.FCStd`, `.step`, `.stl`, and `.cad.json` files from boxes, cylinders, spheres, and cones, with positions, rotations, additions, and cuts. Outputs use a new filename stem. This adapter does not accept model-written Python or arbitrary FreeCAD macros.

Project chats use a work-focused prompt; personality affects tone, while fictional scenes do not override real tasks. Before each character's turn, the app checks actual project read access if the character has a file-reading grant, records the result in **Tool activity**, and supplies it to the model. Assigning a project folder limits bot file actions; it does not change Windows permissions or restrict Ollama's own access to its installation and model files.

Models with native tool calling use Ollama's tool protocol. If Ollama reports that the chosen model does not support tools (for example, Gemma 3), the app automatically uses a JSON request/result protocol through the same permission-checked adapters. Your selected model stays unchanged. Compatibility replies are buffered while the JSON is decoded, so text may appear after a short pause. Native tool models such as Qwen 3 generally follow tool requests more reliably. Invalid JSON requests produce an explicit error; malformed output is never executed as code. Other Ollama failures show the model's actual error, including memory/load problems.

Watch **Tool activity** for actual arguments, successes, and errors; a character's prose alone is not evidence of a completed file operation. Each turn allows six model tool cycles and twelve model-requested calls, plus the app's read-access check. Completed actions are audited locally, and identical calls in a resumed round reuse recorded successes. Actions interrupted during execution require reviewing the project before retrying an edit. Existing failed rounds can be resumed with **Retry reply** after upgrading; messages, models, permissions, and project assignments are preserved.

Prefer relative filenames such as `bob_test.txt`. Absolute paths pointing inside the assigned folder are normalized to project-relative paths, including ordinary Windows backslash spellings. Outside paths, parent traversal, links/junctions, hard links, and protected metadata such as `.git`, `.vscode`, and `.env` remain blocked. Git has a dedicated restricted adapter for its metadata. All members share the same project files. **Browse project files** previews text and downloads project artifacts, including generated CAD files. Project assignments cannot change during an unfinished round.

Each saved project reply includes an **App-verified tool record**, generated directly from the audit database. This shows actual operations, errors, and file paths and explicitly reports when no successful file writes were recorded. A model may still produce inaccurate prose; text inside its reply, including invented timestamps or “Tool execution completed” messages, is never treated as evidence or executed as a tool. Genuine requests must use the native or structured JSON tool protocol. A malformed compatibility response gets one format-repair attempt. If writing already succeeded but the closing response remains malformed, the app saves a factual verification notice listing confirmed writes and flags that other work may remain.

These are application-level boundaries, not an operating-system sandbox. Trusted installed programs still run with your Windows account's normal privileges. Grant tools only to characters you trust, use dedicated project folders, and review generated code before running it yourself. Adding another executable path selects a supported adapter; it does not create arbitrary GUI or shell control. Tool registrations, locations, grants, project assignments, and audit history persist in the private local database and are included in local exports, not the public source repository.

## Images and read-aloud voices

Open **Edit character** to choose a PNG, JPG, or WebP image (up to 10 MB). The app crops it to a square, resizes it to 512×512, and stores it in your local database. **Remove image** returns to the avatar symbol. Images are included in your local backups and never committed to this repository.

In the same editor, choose a **Character voice**, adjust the speed, and use **Preview voice**. Check **Automatically read new replies** to hear each completed reply. Every saved character message also has a **Read aloud** button. The playback bar provides Pause/Resume and Stop. Leaving the chat or starting a new message stops playback.

Speech uses the browser’s installed device-local voices, with no cloud TTS service or voice cloning. Available voices differ between your PC and phone. If a saved voice is unavailable on the device you are using, select an available voice or **Default local voice**. If none appear, try Chrome or Edge on Windows or install a speech voice in your device settings. Mobile browsers may require tapping **Read aloud** once before allowing automatic speech. Voice choices, speed, and auto-read settings are saved per character.

## Phone access on your Wi-Fi

1. Keep Character Room running on your PC and connect your phone to the same trusted home network.
2. On the PC, open **Settings & backup → Phone access → Enable phone access**. Choose your home Wi-Fi address. This starts a separate listener bound only to that address on port 8766. The PC-only address on port 8765 stays available.
3. Run **Allow Phone Access.cmd** once and approve the Windows administrator prompt if your firewall blocks access. It adds rules only for Python/Pythonw on your selected Wi-Fi address and TCP port 8766 from your local subnet. It does not open router ports, change your network’s Public/Private category, or publish the app online.
4. On your phone, open the address shown in the settings and enter the displayed access code. The phone sees the same characters, images, chats, and memories as your PC; nothing is copied into a separate library.

Anyone on the local network with the access code can use the library. The connection uses plain HTTP, so use this only on trusted networks. Incorrect code attempts are rate-limited. Phone users cannot reveal the access code, change network access, or stop the server. Use **Turn off phone access** on the PC to stop the listener and invalidate phone sessions.

The enable/disable choice persists across restarts, but a new access code is generated each time the app starts; phones must sign in again. The PC must remain awake. If its network address changes, toggle phone access off and on and use the new displayed address. Guest Wi-Fi or client isolation may block phone-to-PC connections. If multiple addresses appear, use the PC’s Wi-Fi address.

The firewall helper requires Windows administrator permission. To remove its rules later, run PowerShell as administrator and use `Get-NetFirewallRule -Name CharacterRoom-LocalNetwork-8766-* | Remove-NetFirewallRule`. Turning phone access off in the app immediately stops its network listener even when the rules remain installed.

## Local persistence and memory

Messages, character profiles, model choice, and pinned memories are saved automatically in `data/character-room.sqlite3`. They survive browser refreshes and PC restarts. The browser only remembers which conversation to reopen. There is no password or disk encryption in the app; your Windows account and disk permissions protect the database.

The AI sees the character profile, pinned memory, and up to about 16,000 characters of recent conversation, within a 16K-token model context. Older messages remain saved and readable, but are not automatically recalled by the model. Put important lasting facts in **Character details → Pinned memory → Save memory**. Memories belong to each conversation. Character edits affect subsequent replies and the first message in new chats, without rewriting old messages.

Replies stream as they are generated. A user message is saved before generation. If Ollama fails, use **Retry reply** to answer that saved message without duplicating it. Incomplete character replies are not saved. If you close the browser during generation, the server continues trying to finish and save the response.

## Back up or move

Use **Settings & backup → Export all data as JSON** for a readable archive. Individual chats can be exported as text. JSON import is not implemented.

For a restorable backup, stop the server first, then copy the entire `data` folder. To restore, stop the app and replace its `data` folder with your backup. To move the app to another folder or PC, stop it and copy this entire CharacterRoom folder; install Python and Ollama on the other PC and download the same model. Keep the data folder private.

## Stop or restart

Closing the browser does not stop the background server. Restarting Windows stops it; double-click the launcher to start again. To stop just this app, double-click **Stop Character Room.cmd**. This leaves Ollama running for any other apps that use it. For terminal use:

```
python server.py --open
```

Press Ctrl+C to stop a terminal-launched server. You can use `--port 8766` if 8765 is occupied. The main server binds only to 127.0.0.1. Enabling phone access adds a separate authenticated listener on the Wi-Fi address you select.

## Troubleshooting

- If the model is offline, open Ollama and choose **Settings & backup → Refresh**. The first reply can be slower while a model loads.
- If there are no models, run `ollama pull qwen3:8b` in a terminal (downloads several GB), then Refresh. You may select any other installed local chat model.
- If a model cannot load, try a smaller model or close other memory-heavy programs. Generation is allowed up to five minutes between chunks; performance depends on your hardware.
- If the launcher does not open a page, run `python server.py --open` in this folder to see the error. Check whether another program occupies port 8765.
- All files are served from an explicit allowlist. The database and app source are not exposed by the web server.

API implementation follows the [Ollama chat API](https://docs.ollama.com/api/chat) and [model listing API](https://docs.ollama.com/api/tags).

## Tests

Run `python -m unittest discover -s tests -v`. The integration tests use a temporary database and a mocked model response, so they do not require a running Ollama instance or access your saved library.

Optional speech-controller tests run with `node tests/test_speech.cjs`. Node is only needed for these tests, not to run the app.
