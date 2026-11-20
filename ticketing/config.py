import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from dotenv import load_dotenv
from pydantic import Field, HttpUrl, TypeAdapter, model_validator

from .schema import AgentName, StrictModel

ROOT = Path(__file__).resolve().parent.parent


class MCPTool(StrictModel):
    effect: Literal["read", "write", "destructive"]
    path_arguments: list[str] = Field(default_factory=list)


class MCP(StrictModel):
    endpoint: str | None = None
    api_key_env: str | None = None
    tools: dict[str, MCPTool] = Field(default_factory=dict)


class Agent(StrictModel):
    enabled: bool = False
    base_url: str
    api_key_env: str | None = None
    model: str | None = Field(default=None, min_length=1)
    model_path: str | None = Field(default=None, min_length=1)
    training_base_model: str | None = Field(default=None, min_length=1)
    system_prompt: str = Field(min_length=1)
    allowed_mcp_tools: list[str] = Field(default_factory=list)
    allowed_file_paths: list[str] = Field(default_factory=list)
    token_budget: int = Field(ge=100)
    input_usd_per_million: float = Field(default=0, ge=0, allow_inf_nan=False)
    output_usd_per_million: float = Field(default=0, ge=0, allow_inf_nan=False)
    mcp: MCP = Field(default_factory=MCP)

    @model_validator(mode="after")
    def check_model(self):
        if not self.model and not self.model_path:
            raise ValueError("Specify a model name or a model_path.")
        return self

    @property
    def model_id(self):
        return self.model or self.model_path


class AgentConfig(StrictModel):
    agents: dict[AgentName, Agent]


@dataclass
class Settings:
    root: Path
    token: str
    dispatch: bool
    soup: str
    agents: dict[str, Agent]
    soup_wsl_distro: str | None = None


def load_settings(root=ROOT):
    root = Path(root).resolve()
    load_dotenv(root / ".env")
    config = AgentConfig.model_validate(yaml.safe_load((root / "agents.yaml").read_text(encoding="utf-8")))
    url_validator = TypeAdapter(HttpUrl)
    for agent in config.agents.values():
        url_validator.validate_python(agent.base_url)
        if agent.mcp.endpoint:
            url_validator.validate_python(agent.mcp.endpoint)
    return Settings(root, os.getenv("TICKETS_TOKEN", ""),
                    os.getenv("TICKETS_DISPATCH", "").lower() in {"1", "true", "yes"},
                    os.getenv("SOUP_EXECUTABLE", "soup"), config.agents,
                    os.getenv("SOUP_WSL_DISTRO") or None)
