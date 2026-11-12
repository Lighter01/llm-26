"""Serializable replies/events shared by CLI and experiment adapters."""

from pydantic import Field

from dnd_rag.contracts import Contract


class ContextStats(Contract):
    input_tokens: int | None = None
    agent_limit: int = 11000
    server_window: int = 16384
    compacted: bool = False


class AgentEvent(Contract):
    kind: str
    payload: dict = Field(default_factory=dict)


class AgentReply(Contract):
    text: str
    status: str
    sources: list = Field(default_factory=list)
    context: ContextStats = Field(default_factory=ContextStats)
    trace_id: str | None = None
    usage: dict = Field(default_factory=dict)
    error: dict | None = None
    citation_validation: dict | None = None
