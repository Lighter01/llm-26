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


def test_interrupted_tool_exchange_is_closed_before_next_user_turn(tmp_path):
    from dnd_rag.agent.observability import ObservationRecorder
    from dnd_rag.agent.service import AgentService

    model = ScriptedModel(
        replies=[
            AIMessage(content='', tool_calls=[{'id': 'done', 'name': 'double', 'args': {'n': 3}}]),
            AIMessage(
                content='', tool_calls=[{'id': 'not-run', 'name': 'double', 'args': {'n': 9}}]
            ),
            AIMessage(content='The interrupted call was not executed.'),
        ]
    )
    service = AgentService(
        model=model,
        tools=[double],
        recorder=ObservationRecorder(tmp_path),
        config=AgentConfig(max_tool_calls=1),
    )

    async def run():
        assert (
            await service.ainvoke('same', 'Double repeatedly', turn_id='one')
        ).status == 'step_limit'
        assert (
            await service.ainvoke('same', 'What happened?', turn_id='two')
        ).status == 'completed'

    asyncio.run(run())
    messages = model.seen[-1]
    closures = [m for m in messages if isinstance(m, ToolMessage) and m.tool_call_id == 'not-run']
    assert len(closures) == 1 and closures[0].status == 'error'
    assert 'unavailable' in closures[0].content.lower()


def test_truncated_final_answer_is_incomplete_with_partial_text_and_consumed_usage(tmp_path):
    from dnd_rag.agent.observability import ObservationRecorder
    from dnd_rag.agent.service import AgentService

    model = ScriptedModel(
        replies=[
            AIMessage(
                content='The partial answer',
                response_metadata={'finish_reason': 'length'},
                usage_metadata={'input_tokens': 100, 'output_tokens': 20, 'total_tokens': 120},
            )
        ]
    )
    service = AgentService(model=model, tools=[], recorder=ObservationRecorder(tmp_path))
    reply = asyncio.run(service.ainvoke('scope', 'Explain', turn_id='one'))
    assert reply.status == 'incomplete' and reply.error['code'] == 'generation_truncated'
    assert reply.text == 'The partial answer' and reply.usage['output_tokens'] == 20


def test_parallel_tool_timeout_preserves_already_completed_loot_result(tmp_path):
    from dnd_rag.agent.observability import ObservationRecorder
    from dnd_rag.agent.service import AgentService

    @tool
    async def actual_loot() -> str:
        """Return one actual random payout."""
        return json.dumps({'coins': {'gp': 19}})

    @tool
    async def slow_lookup() -> str:
        """A separate slow lookup."""
        await asyncio.sleep(3)
        return '{}'

    model = ScriptedModel(
        replies=[
            AIMessage(
                content='',
                tool_calls=[
                    {'id': 'loot', 'name': 'actual_loot', 'args': {}},
                    {'id': 'slow', 'name': 'slow_lookup', 'args': {}},
                ],
            ),
            AIMessage(content='The recorded purse is 19 gp.'),
        ]
    )
    service = AgentService(
        model=model,
        tools=[actual_loot, slow_lookup],
        recorder=ObservationRecorder(tmp_path),
        config=AgentConfig(timeout_seconds=0.5),
    )

    async def run():
        first = await service.ainvoke('scope', 'Loot and look up', turn_id='one')
        assert first.status == 'timeout'
        assert service.last_records['scope']['tools'][0]['result'] == {'coins': {'gp': 19}}
        second = await service.ainvoke(
            'scope', 'Recall actual payout; do not reroll', turn_id='two'
        )
        assert second.status == 'completed'
        messages = {m.tool_call_id: m for m in model.seen[-1] if isinstance(m, ToolMessage)}
        assert messages['loot'].status == 'success'
        assert json.loads(messages['loot'].content) == {'coins': {'gp': 19}}
        assert messages['slow'].status == 'error' and 'unavailable' in messages['slow'].content

    asyncio.run(run())


def test_timeout_during_later_generation_does_not_claim_complete_usage(tmp_path):
    from dnd_rag.agent.observability import ObservationRecorder
    from dnd_rag.agent.service import AgentService

    known = {'input_tokens': 100, 'output_tokens': 20, 'total_tokens': 120}

    class SlowSecondModel(ScriptedModel):
        async def _agenerate(self, messages, *args, **kwargs):
            if not self.replies:
                await asyncio.sleep(3)
            return self._generate(messages, *args, **kwargs)

    model = SlowSecondModel(
        replies=[
            AIMessage(
                content='',
                tool_calls=[{'id': 'done', 'name': 'double', 'args': {'n': 3}}],
                usage_metadata=known,
            )
        ]
    )
    service = AgentService(
        model=model,
        tools=[double],
        recorder=ObservationRecorder(tmp_path),
        config=AgentConfig(timeout_seconds=0.5),
    )
    reply = asyncio.run(service.ainvoke('scope', 'Compute and explain', turn_id='one'))
    assert reply.status == 'timeout' and reply.usage['model_calls'] == 2
    assert reply.usage['input_tokens'] is None and reply.usage['output_tokens'] is None
    assert service.last_records['scope']['generations'] == [known]
