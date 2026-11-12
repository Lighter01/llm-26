import asyncio
import json

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from pydantic import Field

from dnd_rag.agent.config import AgentConfig


class ScriptedModel(BaseChatModel):
    replies: list = Field(default_factory=list)
    seen: list = Field(default_factory=list)

    @property
    def _llm_type(self):
        return 'scripted-dm'

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(messages)
        return ChatResult(generations=[ChatGeneration(message=self.replies.pop(0))])


@tool
def double(n: int) -> str:
    """Double an integer."""
    return json.dumps({'result': 2 * n})


def test_sessions_keep_tool_results_and_isolate_new_dialog(tmp_path):
    from dnd_rag.agent.observability import ObservationRecorder
    from dnd_rag.agent.service import AgentService

    model = ScriptedModel(
        replies=[
            AIMessage(content='', tool_calls=[{'id': 't1', 'name': 'double', 'args': {'n': 21}}]),
            AIMessage(content='42; party four.'),
            AIMessage(content='Still four.'),
            AIMessage(content='New conversation.'),
        ]
    )
    service = AgentService(model=model, tools=[double], recorder=ObservationRecorder(tmp_path))

    async def run():
        first = await service.ainvoke('same', 'Remember party four. Double21.', turn_id='one')
        second = await service.ainvoke('same', 'How many?', turn_id='two')
        third = await service.ainvoke('new', 'Hello.', turn_id='three')
        assert first.status == second.status == third.status == 'completed'
        assert any(isinstance(m, ToolMessage) and '42' in m.content for m in model.seen[2])
        assert any('Remember party four.' in str(m.content) for m in model.seen[2])
        assert all('Remember party four.' not in str(m.content) for m in model.seen[3])

    asyncio.run(run())


def test_invalid_tool_call_can_be_corrected_and_limits_are_explicit(tmp_path):
    from dnd_rag.agent.observability import ObservationRecorder
    from dnd_rag.agent.service import AgentService

    model = ScriptedModel(
        replies=[
            AIMessage(
                content='', tool_calls=[{'id': 'bad', 'name': 'double', 'args': {'n': 'bad'}}]
            ),
            AIMessage(content='', tool_calls=[{'id': 'ok', 'name': 'double', 'args': {'n': 3}}]),
            AIMessage(content='6'),
        ]
    )
    service = AgentService(model=model, tools=[double], recorder=ObservationRecorder(tmp_path))
    reply = asyncio.run(service.ainvoke('fix', 'Double3', turn_id='one'))
    assert reply.text == '6' and reply.status == 'completed'
    assert any(isinstance(m, ToolMessage) and m.status == 'error' for m in model.seen[1])
    looping = ScriptedModel(
        replies=[
            AIMessage(content='', tool_calls=[{'id': str(i), 'name': 'double', 'args': {'n': 3}}])
            for i in range(5)
        ]
    )
    service = AgentService(
        model=looping,
        tools=[double],
        recorder=ObservationRecorder(tmp_path),
        config=AgentConfig(max_model_calls=2),
    )
    reply = asyncio.run(service.ainvoke('limit', 'Keep calling', turn_id='one'))
    assert reply.status == 'step_limit' and reply.error
    assert len(looping.seen) == 2


def test_turn_timeout_and_tool_limit_do_not_report_success(tmp_path):
    from dnd_rag.agent.observability import ObservationRecorder
    from dnd_rag.agent.service import AgentService

    class SlowModel(ScriptedModel):
        async def _agenerate(self, *args, **kwargs):
            await asyncio.sleep(1)
            return self._generate(*args, **kwargs)

    slow = AgentService(
        model=SlowModel(),
        tools=[],
        recorder=ObservationRecorder(tmp_path),
        config=AgentConfig(timeout_seconds=0.01),
    )
    reply = asyncio.run(slow.ainvoke('slow', 'Hi', turn_id='one'))
    assert reply.status == 'timeout' and reply.usage['input_tokens'] is None
    calls = [
        AIMessage(content='', tool_calls=[{'id': str(i), 'name': 'double', 'args': {'n': 3}}])
        for i in range(3)
    ]
    limited = AgentService(
        model=ScriptedModel(replies=calls),
        tools=[double],
        recorder=ObservationRecorder(tmp_path),
        config=AgentConfig(max_tool_calls=1),
    )
    reply = asyncio.run(limited.ainvoke('tool-limit', 'Double', turn_id='one'))
    assert reply.status == 'step_limit' and reply.usage['tool_calls'] == 1


def test_nullable_error_field_in_successful_tool_result_is_not_an_error(tmp_path):
    from dnd_rag.agent.observability import ObservationRecorder
    from dnd_rag.agent.service import AgentService

    @tool
    def successful_game() -> str:
        """Return a successful game calculation."""
        return json.dumps({'status': 'success', 'total_xp': 4600, 'error': None})

    model = ScriptedModel(
        replies=[
            AIMessage(content='', tool_calls=[{'id': 'c', 'name': 'successful_game', 'args': {}}]),
            AIMessage(content='4600'),
        ]
    )
    service = AgentService(
        model=model, tools=[successful_game], recorder=ObservationRecorder(tmp_path)
    )
    reply = asyncio.run(service.ainvoke('success', 'Evaluate', turn_id='one'))
    assert reply.status == 'completed'
    assert service.last_records['success']['tools'][0]['status'] == 'completed'
