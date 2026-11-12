"""Shared adapter contract; dataset contracts are added with the runner."""

from typing import Protocol

from pydantic import Field

from dnd_rag.agent.contracts import AgentReply
from dnd_rag.contracts import Contract
from dnd_rag.evaluation.evidence import EvidenceSpan


class AgentAdapter(Protocol):
    async def ainvoke(
        self, session_id: str, user_text: str, *, turn_id: str, on_event=None
    ) -> AgentReply: ...


class TurnCase(Contract):
    input: str = Field(min_length=1)
    rubric: list[str] = Field(min_length=1)
    expected_tools: list[str] = Field(default_factory=list)
    checks: dict = Field(default_factory=dict)
    evidence: list[EvidenceSpan] = Field(default_factory=list)


class TaskCase(Contract):
    id: str
    turns: list[TurnCase] = Field(min_length=1)
    metadata: dict
    expected_output: dict | None = None
    evidence: list[EvidenceSpan] = Field(default_factory=list)


class AgentDataset(Contract):
    version: int
    items: list[TaskCase]
    fingerprint: str = ''
    source_path: str = ''
    corpus_hashes: dict = Field(default_factory=dict)


class Scores(Contract):
    values: dict[str, float | None]
    pending: list[str]
    method: dict[str, str]

    @property
    def success(self):
        if any(v == 0 for v in self.values.values()):
            return False
        return None if self.pending else True


class RunSummary(Contract):
    run_id: str
    status: str
    executions: int
    metrics: dict
    trace_links: list[str | None] = Field(default_factory=list)
