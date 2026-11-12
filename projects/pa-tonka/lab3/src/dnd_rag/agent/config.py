"""Agent limits and shared local model profile."""

from pydantic import Field

from dnd_rag.config import ConfigModel, LLMProfile, load_llm_profile

__all__ = ['AgentConfig', 'LLMProfile', 'load_llm_profile']


class AgentConfig(ConfigModel):
    context_limit: int = Field(default=8192, ge=1024)
    recent_tokens: int = Field(default=2048, ge=256)
    summary_tokens: int = Field(default=1024, ge=128)
    max_model_calls: int = Field(default=12, gt=0)
    max_tool_calls: int = Field(default=16, gt=0)
    timeout_seconds: float = Field(default=300.0, gt=0)
    mcp_url: str = 'http://127.0.0.1:8765/mcp'
