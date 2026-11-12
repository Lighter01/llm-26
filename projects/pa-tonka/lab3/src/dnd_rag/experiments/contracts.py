"""Shared adapter contract; dataset contracts are added with the runner."""

from typing import Protocol

from dnd_rag.agent.contracts import AgentReply


class AgentAdapter(Protocol):
    async def ainvoke(
        self, session_id: str, user_text: str, *, turn_id: str, on_event=None
    ) -> AgentReply: ...
