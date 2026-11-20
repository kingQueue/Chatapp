from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

TicketType = Literal["design", "code", "sim", "research", "review"]
Status = Literal["backlog", "ready", "in_progress", "review", "done", "blocked", "needs_human"]
TicketId = Annotated[str, StringConstraints(pattern=r"^T-[0-9]{4,}$", max_length=24)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20000)]
Title = Annotated[Text, StringConstraints(max_length=200)]
AgentName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]{0,63}$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class TicketFields(StrictModel):
    title: Title
    description: str = Field(default="", max_length=40000)
    type: TicketType = "research"
    status: Status = "backlog"
    assignee: AgentName | None = None
    parent_id: TicketId | None = None
    depends_on: list[TicketId] = Field(default_factory=list, max_length=100)
    inputs: list[Text] = Field(default_factory=list, max_length=100)
    outputs: list[Text] = Field(default_factory=list, max_length=100)
    acceptance: list[Text] = Field(default_factory=list, max_length=100)
    attempts: int = Field(default=0, ge=0, le=3)
    token_cost: float = Field(default=0, ge=0, allow_inf_nan=False)
    tokens: int = Field(default=0, ge=0)
    created: str | None = None
    updated: str | None = None

    @staticmethod
    def check_time(value: str) -> None:
        if datetime.fromisoformat(value.replace("Z", "+00:00")).utcoffset() is None:
            raise ValueError("Timestamps must include a time zone.")


class TicketEdit(TicketFields):
    id: TicketId
    revision: int = Field(ge=1)


class Transition(StrictModel):
    status: Status
    reason: Text


class Subtask(StrictModel):
    title: Title
    description: Text
    type: TicketType
    assignee: AgentName | None = None
    acceptance: list[Text] = Field(default_factory=list, max_length=30)


class Decision(StrictModel):
    action: Literal["assign", "split", "request_review", "escalate", "close"]
    ticket_id: TicketId
    assignee: AgentName | None
    reason: Text
    subtasks: list[Subtask] = Field(max_length=10)


class Handoff(StrictModel):
    work_done: Text
    files_produced: list[Text] = Field(max_length=100)
    unresolved_issues: list[Text] = Field(max_length=100)
    next_agent_needs: Text


class Verdict(StrictModel):
    verdict: Literal["pass", "fail"]
    reasons: list[Text] = Field(min_length=1, max_length=100)
