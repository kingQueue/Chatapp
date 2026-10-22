# Character Room

A small, private character chat app that runs on your PC. No npm install, Python packages, accounts, or API keys are needed.

## Open the app

Double-click **Start Character Room.cmd** in this folder. It starts the local server, starts Ollama if needed, and opens http://127.0.0.1:8765 in your browser. Clicking the launcher again opens the existing app.

Requires Python 3.10+ and [Ollama](https://ollama.com). Download a model first with `ollama pull qwen3:8b`, or select another downloaded local model under **Settings & backup**. The default is `qwen3:8b`. Cloud models are excluded. The app only contacts Ollama on 127.0.0.1:11434; there are no analytics, external assets, or hosted APIs.

## Make a character

Choose **Create character**. Add a name, a background story, and comma-separated personality tags. You can also set an avatar symbol, color, speaking style, starting scene, and first message. These fields guide every generated reply. Three editable characters are included to get you started.

**Start a conversation** opens a chat; **Continue conversation** resumes the most recent chat with that character. Use **New chat** for another independent conversation. The sidebar lets you return to earlier conversations. You can rename, export, or delete a conversation. Deleting a character also deletes its conversations, after confirmation.

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

Press Ctrl+C to stop a terminal-launched server. You can use `--port 8766` if 8765 is occupied. The server binds only to 127.0.0.1, not your Wi-Fi/LAN address.

## Troubleshooting

- If the model is offline, open Ollama and choose **Settings & backup → Refresh**. The first reply can be slower while a model loads.
- If there are no models, run `ollama pull qwen3:8b` in a terminal (downloads several GB), then Refresh. You may select any other installed local chat model.
- If a model cannot load, try a smaller model or close other memory-heavy programs. Generation is allowed up to five minutes between chunks; performance depends on your hardware.
- If the launcher does not open a page, run `python server.py --open` in this folder to see the error. Check whether another program occupies port 8765.
- All files are served from an explicit allowlist. The database and app source are not exposed by the web server.

API implementation follows the [Ollama chat API](https://docs.ollama.com/api/chat) and [model listing API](https://docs.ollama.com/api/tags).

## Tests

Run `python -m unittest discover -s tests -v`. The integration tests use a temporary database and a mocked model response, so they do not require a running Ollama instance or access your saved library.
