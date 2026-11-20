from ticketing.config import load_settings
from ticketing.schema import TicketFields
from ticketing.store import Store


def main():
    root = load_settings().root
    store = Store(root / "data" / "tickets.sqlite3", root / "data" / "runs")
    if store.list():
        print("Sample tickets are only added to an empty board.")
        return
    research = store.create(TicketFields(
        title="Compare encoder options for a bench axis", assignee="research_agent",
        description="Compare three encoders for a low-speed robotics test rig.",
        acceptance=["Cite manufacturer specifications", "Compare resolution, voltage and interface"],
    ))
    store.create(TicketFields(
        title="Draft bench-axis sensor bracket", type="design", assignee="cad_agent",
        depends_on=[research["id"]], acceptance=["Document mounting dimensions and clearance"],
    ))
    store.transition(research["id"], "ready", "Sample research ticket is ready to start.")
    sample = store.create(TicketFields(
        title="Confirm preferred simulation stack", type="sim",
        description="Choose the simulator to use for initial bench-axis studies.",
        acceptance=["Record the simulator and version"],
    ))
    store.transition(sample["id"], "needs_human", "Choose a simulator before agents continue.")
    print("Added three example ticket cards.")


if __name__ == "__main__":
    main()
