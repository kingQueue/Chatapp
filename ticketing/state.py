class Conflict(ValueError):
    pass


class Missing(ValueError):
    pass


TRANSITIONS = {
    "backlog": {"ready"},
    "ready": {"in_progress"},
    "in_progress": {"review", "blocked"},
    "review": {"done", "in_progress"},
    "done": set(),
    "blocked": set(),
    "needs_human": set(),
}


def advance(ticket, status, dependencies, reason):
    current = ticket["status"]
    if status == current or (status != "needs_human" and status not in TRANSITIONS[current]):
        raise Conflict(f"Illegal transition from {current} to {status}.")
    if status in {"ready", "in_progress"}:
        unfinished = [key for key in ticket["depends_on"] if dependencies.get(key) != "done"]
        if unfinished:
            raise Conflict("Finish dependencies first: " + ", ".join(unfinished))
        if ticket["attempts"] >= 3:
            return "needs_human", "Three work attempts used. " + reason
    return status, reason
