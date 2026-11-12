import asyncio
import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, convert_to_openai_messages
from langchain_core.tools import tool

from dnd_rag.agent.config import AgentConfig
from dnd_rag.agent.observability import ObservationRecorder
from dnd_rag.config import LLMProfile
from dnd_rag.contracts import RagError
from tests.agent.test_service import ScriptedModel


def setup(tmp_path, *, limit=1024):
    from dnd_rag.agent.memory import build_memory_middleware

    @tool
    def search_rules(query: str) -> str:
        """Search original rules with full schemas."""
        return 'unused'

    model = ScriptedModel(
        replies=[
            AIMessage(content='PARTY: four level6. ACTUAL LOOT:19GP.'),
            AIMessage(content='PARTY: four level6. ACTUAL LOOT:19GP.'),
        ]
    )

    class Native:
        profile = LLMProfile(context_size=16384)
        chat_model = model
        broken = False

        def payload(self, messages, **kwargs):
            return {
                'model': 'local',
                'messages': convert_to_openai_messages(list(messages)),
                **kwargs,
            }

        def count_input(self, payload):
            if self.broken:
                raise RagError('llm_timeout', 'Counter unavailable')
            return len(json.dumps(payload)) // 4

        def ensure_safe(self, payload, count):
            if count + payload.get('max_tokens', 2048) + 256 > 16384:
                raise RagError('context_overflow', 'Too large')

    native = Native()
    events = []
    turn = {'model_calls': 0, 'generations': [], 'phase': 'agent', 'compacted': False}
    config = AgentConfig(context_limit=limit, recent_tokens=256, summary_tokens=256)
    memory = build_memory_middleware(
        native,
        native.profile,
        lambda k, p: events.append((k, p)),
        config=config,
        tools=[search_rules],
        system_prompt='System instruction ' + ('s' * 100),
        recorder=ObservationRecorder(tmp_path),
        turn_getter=lambda: turn,
    )
    return memory, native, model, events, turn


def history():
    return [
        HumanMessage(content='FIRST: party four level6; actual loot19GP.'),
        AIMessage(
            content='', tool_calls=[{'id': 't', 'name': 'search_rules', 'args': {'query': 'rules'}}]
        ),
        ToolMessage(content='MIDDLE ' + ('original source ' * 400), tool_call_id='t'),
        AIMessage(content='LAST accepted encounter.'),
        HumanMessage(content='CURRENT TASK: keep the accepted party and loot.'),
    ]


def test_below_threshold_preserves_full_history_and_full_tools_are_counted(tmp_path):
    memory, native, model, events, turn = setup(tmp_path, limit=11000)
    state = {'messages': history()}
    result = asyncio.run(memory.abefore_model(state, None))
    assert result is None and len(state['messages']) == 5 and not model.seen
    body = memory.payload(state['messages'])
    assert body['tools'][0]['function']['name'] == 'search_rules'
    assert body['messages'][0]['role'] == 'system'


def test_complete_prefix_no_dangling_pairs_and_current_task_protected(tmp_path):
    memory, native, model, events, turn = setup(tmp_path)
    state = {'messages': history()}
    result = asyncio.run(memory.abefore_model(state, None))
    new = result['messages'][1:]
    assert new[-1].content.startswith('CURRENT TASK:')
    assert not any(isinstance(m, ToolMessage) for m in new)
    prompt = str(model.seen[0])
    assert 'FIRST: party four' in prompt and 'MIDDLE' in prompt and 'LAST accepted' in prompt
    assert 'CURRENT TASK:' not in prompt
    assert '19GP' in new[0].content and turn['compacted']
    assert any(
        kind == 'compaction_completed' and payload['after'] < payload['before']
        for kind, payload in events
    )


def test_old_loot_and_previous_summary_reach_second_summary(tmp_path):
    memory, native, model, events, turn = setup(tmp_path)
    first = asyncio.run(memory.abefore_model({'messages': history()}, None))['messages'][1:]
    second = first + [
        AIMessage(content='Large intervening discussion ' + ('evidence ' * 700)),
        HumanMessage(content='New current task: recall first loot.'),
    ]
    result = asyncio.run(memory.abefore_model({'messages': second}, None))
    assert '19GP' in str(model.seen[1]) and '19GP' in result['messages'][1].content
    assert len([k for k, p in events if k == 'compaction_completed']) == 2


def test_current_exchange_too_large_is_diagnostic_and_counter_failure_does_not_trim(tmp_path):
    memory, native, model, events, turn = setup(tmp_path)
    state = {
        'messages': [
            HumanMessage(content='Protected current ' + ('x' * 7000)),
            AIMessage(
                content='',
                tool_calls=[{'id': 't', 'name': 'search_rules', 'args': {'query': 'rule'}}],
            ),
            ToolMessage(content='y' * 4000, tool_call_id='t'),
        ]
    }
    assert asyncio.run(memory.abefore_model(state, None)) is None
    assert len(state['messages']) == 3 and not model.seen
    native.broken = True
    with pytest.raises(RagError, match='Counter unavailable'):
        asyncio.run(memory.abefore_model({'messages': history()}, None))
    assert not model.seen


def test_summary_failure_and_oversize_full_prefix_are_explicit(tmp_path):
    memory, native, model, events, turn = setup(tmp_path)
    model.replies = []
    with pytest.raises(RagError, match='summar'):
        asyncio.run(memory.abefore_model({'messages': history()}, None))
    memory, native, model, events, turn = setup(tmp_path)
    messages = [
        HumanMessage(content='Do not trim ' + ('z' * 80000)),
        AIMessage(content='old answer'),
        HumanMessage(content='current'),
    ]
    with pytest.raises(RagError, match='summary|summar|Too large'):
        asyncio.run(memory.abefore_model({'messages': messages}, None))
    assert not model.seen
