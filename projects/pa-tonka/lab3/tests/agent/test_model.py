import json

import httpx
import pytest
from langchain_core.messages import HumanMessage

from dnd_rag.config import LLMProfile, load_settings
from dnd_rag.contracts import RagError
from dnd_rag.runtime import llm


def response():
    return {
        'id': 'c1',
        'object': 'chat.completion',
        'created': 0,
        'model': 'dnd-nemotron',
        'choices': [
            {
                'index': 0,
                'message': {'role': 'assistant', 'content': 'ready'},
                'finish_reason': 'stop',
            }
        ],
        'usage': {'prompt_tokens': 37, 'completion_tokens': 2, 'total_tokens': 39},
    }


def test_full_payload_count_matches_generation_including_tools(tmp_path):
    requests = []

    def handle(req):
        body = json.loads(req.content)
        requests.append((req.url.path, body))
        if req.url.path.endswith('/input_tokens'):
            return httpx.Response(200, json={'input_tokens': 37})
        return httpx.Response(200, json=response())

    with httpx.Client(transport=httpx.MockTransport(handle)) as http:
        client = llm.NativeLLM(load_settings(tmp_path), LLMProfile(), http_client=http)
        tool = {
            'type': 'function',
            'function': {
                'name': 'check',
                'description': 'Check a number.',
                'parameters': {
                    'type': 'object',
                    'properties': {'n': {'type': 'integer'}},
                    'required': ['n'],
                },
            },
        }
        bound = client.chat_model.bind_tools([tool])
        message = bound.invoke([HumanMessage(content='Check 2')])
        count_payload = next(b for p, b in requests if p.endswith('/input_tokens'))
        generate_payload = next(b for p, b in requests if p.endswith('/chat/completions'))
        assert count_payload == generate_payload
        assert count_payload['tools'][0]['function']['name'] == 'check'
        assert message.usage_metadata['input_tokens'] == 37
        assert client.last_input_tokens == 37
        client.close()


@pytest.mark.parametrize(
    'thinking,budget,effort', [(False, 0, 'none'), (True, 512, None), (True, 1024, None)]
)
def test_effective_reasoning_options(thinking, budget, effort):
    import dnd_rag.agent.config as config

    p = config.LLMProfile(thinking=thinking, reasoning_budget_tokens=budget)
    assert p.template_options()['chat_template_kwargs']['enable_thinking'] == thinking
    assert p.template_options()['reasoning_budget_tokens'] == budget
    assert p.template_options().get('reasoning_effort') == effort
    assert p.max_output_tokens > budget


def test_unsupported_effort_is_rejected():
    with pytest.raises(ValueError):
        LLMProfile(reasoning_effort='low')


def test_native_counter_failure_is_explicit(tmp_path):
    def handle(req):
        return httpx.Response(200, json={'input_tokens': -1})

    with httpx.Client(transport=httpx.MockTransport(handle)) as http:
        client = llm.NativeLLM(load_settings(tmp_path), LLMProfile(), http_client=http)
        with pytest.raises(RagError, match='input_tokens'):
            client.count_input({'model': 'local', 'messages': [], 'tools': []})


def test_native_usage_parity_mismatch_is_error(tmp_path):
    def handle(req):
        return httpx.Response(
            200, json={'input_tokens': 10} if req.url.path.endswith('/input_tokens') else response()
        )

    with httpx.Client(transport=httpx.MockTransport(handle)) as http:
        client = llm.NativeLLM(load_settings(tmp_path), LLMProfile(), http_client=http)
        with pytest.raises(RagError, match='parity'):
            client.chat_model.invoke('ready')


def test_precomputed_payload_matches_wire_body(tmp_path):
    captured = []

    def handle(req):
        body = json.loads(req.content)
        if req.url.path.endswith('/input_tokens'):
            return httpx.Response(200, json={'input_tokens': 37})
        captured.append(body)
        return httpx.Response(200, json=response())

    with httpx.Client(transport=httpx.MockTransport(handle)) as http:
        client = llm.NativeLLM(load_settings(tmp_path), LLMProfile(), http_client=http)
        messages = [HumanMessage(content='ready')]
        payload = client.payload(messages)
        client.chat_model.invoke(messages)
        assert payload == captured[0]
