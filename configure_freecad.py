"""Provision a FreeCAD character and its dedicated project in local Character Room."""
import argparse
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4

from ticketing.config import ROOT
from ticketing.freecad import TOOL_ID, NAME

CHARACTER = "FreeCAD Designer"
CHAT = "FreeCAD Workbench"
BASE_MODEL = "qwen3-coder:30b"


def request(origin, path, data=None, timeout=20):
    body = None if data is None else json.dumps(data).encode("utf-8")
    return urlopen(Request(origin + path, data=body, headers={
        "Content-Type": "application/json", "X-Character-Room": "1",
    }), timeout=timeout)


def api(origin, path, data=None):
    with request(origin, path, data) as response:
        return json.load(response)


def configure(origin, model, project_override=None):
    state = api(origin, "/api/state")
    registry = api(origin, "/api/tools")["tools"]
    available = api(origin, "/api/models")["models"]
    if model not in available:
        raise ValueError(f"Download or import {model} into Ollama first.")
    discovery = api(origin, "/api/tools", {"action": "discover"})["locations"]["freecad"]
    registered = next((entry for entry in registry if entry["id"] == TOOL_ID), None)
    if registered and registered["adapter"] != "freecad":
        raise ValueError(f"The tool ID {TOOL_ID} is already used by another adapter.")
    location = registered["location"] if registered else discovery
    if not location:
        raise ValueError("Install FreeCAD on this PC before provisioning this character.")
    if not registered:
        api(origin, "/api/tools", {"id": TOOL_ID, "name": "FreeCAD", "adapter": "freecad",
                                  "location": location, "enabled": True})
    elif not registered["enabled"]:
        raise ValueError("Enable the existing FreeCAD Workbench tool in Character Room settings.")
    character = next((entry for entry in state["characters"] if entry["name"] == CHARACTER), None)
    if character:
        character_id = character["id"]
        api(origin, f"/api/characters/{character_id}", {"model": model, "tool_ids": [TOOL_ID]})
    else:
        character_id = api(origin, "/api/characters", {
            "name": CHARACTER, "avatar": "⬡", "color": "blue", "model": model, "tool_ids": [TOOL_ID],
            "subtitle": "Editable 3D models in FreeCAD",
            "background": "You build original editable FreeCAD models and export manufacturing geometry.",
            "specialty": "Use the FreeCAD tool for modeling requests. Use millimetres and declarative primitives. "
                         "Use a new models/ output stem, extend cutters for through holes, and act when the "
                         "request is sufficiently specified. Report actual file paths from successful tools.",
            "style": "Brief and technical. State design assumptions and any limitations.",
        })["id"]
    existing = next((entry for entry in state["chats"]
                     if entry["character_id"] == character_id and entry["title"] == CHAT), None)
    previous_project = existing.get("project_dir") if existing else None
    project = Path(project_override or previous_project or (ROOT.parent / f"{ROOT.name}-freecad-project")).resolve()
    project.mkdir(parents=True, exist_ok=True)
    chat_id = existing["id"] if existing else api(origin, "/api/chats", {"character_id": character_id})["id"]
    api(origin, f"/api/chats/{chat_id}", {"title": CHAT, "project_dir": str(project)})
    return chat_id, project


def smoke(origin, chat_id, project):
    stem = "models/validation-spacer-" + uuid4().hex[:6]
    prompt = (f"Make a cylindrical spacer in FreeCAD, 20 mm outer diameter, 8 mm thick, with a centred "
              f"6 mm diameter through hole. Create the files now with output stem {stem}. "
              "Use a cutter that starts below and ends above the solid. Report what the tool saved.")
    confirmed = False
    with request(origin, f"/api/chats/{chat_id}/reply", {"message": prompt}, timeout=600) as response:
        for line in response:
            event = json.loads(line)
            if event.get("type") == "tool_result" and event.get("name") == NAME:
                print(f"FreeCAD tool: {event.get('status')}", flush=True)
                confirmed |= event.get("status") == "success"
            if event.get("type") == "error":
                print(f"Character reply error: {event.get('message') or event.get('error')}", flush=True)
    native = project / (stem + ".FCStd")
    if not confirmed or not native.is_file():
        raise RuntimeError("Character Room did not report successful creation of the requested model.")
    print(f"Verified native model: {native}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", default="http://127.0.0.1:8765")
    parser.add_argument("--model", default=BASE_MODEL)
    parser.add_argument("--project", type=Path, help="Dedicated folder outside the Character Room installation.")
    parser.add_argument("--smoke", action="store_true", help="Ask the configured character to make a spacer.")
    args = parser.parse_args()
    target = urlsplit(args.origin)
    if target.scheme != "http" or target.hostname not in {"127.0.0.1", "localhost"} or target.path not in {"", "/"}:
        parser.error("Use the local Character Room address.")
    try:
        chat, project = configure(args.origin.rstrip("/"), args.model, args.project)
        print(f"{CHARACTER} is ready in the {CHAT} conversation ({args.model}).", flush=True)
        if args.smoke:
            smoke(args.origin.rstrip("/"), chat, project)
    except HTTPError as error:
        parser.exit(1, error.read().decode("utf-8", errors="replace") + "\n")


if __name__ == "__main__":
    main()
