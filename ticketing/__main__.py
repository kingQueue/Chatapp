import argparse

from .config import load_settings
from .state import Conflict
from .store import Store
from .training import export_dataset


def main():
    parser = argparse.ArgumentParser(description="Character Room Tickets tools")
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export", help="Export review-passed runs as Soup JSONL")
    export.add_argument("agent")
    args = parser.parse_args()
    settings = load_settings()
    if args.agent not in settings.agents:
        parser.error("The agent is not in agents.yaml.")
    store = Store(settings.root / "data" / "tickets.sqlite3", settings.root / "data" / "runs")
    try:
        file, rows = export_dataset(settings.root, store, args.agent)
    except Conflict as error:
        parser.exit(1, str(error) + "\n")
    print(f"{rows} examples exported to {file}")


if __name__ == "__main__":
    main()
