# Character Room

A small, private character chat app that runs on your PC. No npm install, Python packages, accounts, or API keys are needed.

## Open the app

Double-click **Start Character Room.cmd** in this folder. It starts the local server, starts Ollama if needed, and opens http://127.0.0.1:8765 in your browser. Clicking the launcher again opens the existing app.

Requires Python 3.10+ and [Ollama](https://ollama.com). Download a model first with `ollama pull qwen3:8b`, or select another downloaded local model under **Settings & backup**. The default is `qwen3:8b`. Cloud models are excluded. The app only contacts Ollama on 127.0.0.1:11434; there are no analytics, external assets, or hosted APIs.

## Make a character

Choose **Create character**. Add a name, a background story, and comma-separated personality tags. You can also set an avatar symbol, color, speaking style, starting scene, and first message. These fields guide every generated reply. Three editable characters are included to get you started.

**Start a conversation** opens a chat; **Continue conversation** resumes the most recent chat with that character. Use **New chat** for another independent conversation. The sidebar lets you return to earlier conversations. You can rename, export, or delete a conversation. Deleting a character also deletes its conversations, after confirmation.

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
