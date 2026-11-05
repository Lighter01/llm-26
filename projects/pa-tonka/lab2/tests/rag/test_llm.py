import json
from types import SimpleNamespace as NS

import httpx
import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from dnd_rag.config import LLMProfile, load_settings
from dnd_rag.contracts import RagError
from dnd_rag.rag.llm import LLMClient
from dnd_rag.runtime import llama


def profile(**changes):
    return LLMProfile(
        gpu_layers=99,
        batch_size=512,
        ubatch_size=128,
        cache_type_k='q8_0',
        cache_type_v='q8_0',
        **changes,
    )


def chat_response():
    return {
        'id': 'chat1',
        'object': 'chat.completion',
        'created': 0,
        'model': 'dnd-nemotron',
        'choices': [
            {
                'index': 0,
                'message': {'role': 'assistant', 'content': 'A supported answer [1].'},
                'finish_reason': 'stop',
            }
        ],
        'usage': {'prompt_tokens': 17, 'completion_tokens': 8, 'total_tokens': 25},
        'timings': {'prompt_n': 17, 'prompt_ms': 10.0, 'predicted_n': 8, 'predicted_ms': 20.0},
    }


def transport(requests, *, timeout=False):
    def handle(request):
        requests.append(
            (request.url.path, json.loads(request.content) if request.content else None)
        )
        if timeout:
            raise httpx.ReadTimeout('test timeout', request=request)
        if request.url.path == '/apply-template':
            return httpx.Response(200, json={'prompt': 'FULL CHAT TEMPLATE'})
        if request.url.path == '/tokenize':
            return httpx.Response(200, json={'tokens': list(range(17))})
        if request.url.path == '/v1/chat/completions':
            return httpx.Response(200, json=chat_response())
        if request.url.path == '/health':
            return httpx.Response(200, json={'status': 'ok'})
        raise AssertionError(request.url.path)

    return httpx.MockTransport(handle)


def test_chat_and_count_share_template_options(tmp_path):
    settings = load_settings(tmp_path)
    requests = []
    with httpx.Client(transport=transport(requests)) as http:
        client = LLMClient(settings, profile(), http_client=http)
        messages = [SystemMessage(content='Use sources.'), HumanMessage(content='What is AC?')]
        assert client.count_input_tokens(messages) == 17
        result = client.generate(messages, max_tokens=1536)
        native = next(b for p, b in requests if p == '/apply-template')
        chat = next(b for p, b in requests if p == '/v1/chat/completions')
        tokens = next(b for p, b in requests if p == '/tokenize')
        assert native['messages'] == chat['messages']
        assert (
            native['chat_template_kwargs']
            == chat['chat_template_kwargs']
            == {'enable_thinking': False}
        )
        assert native['reasoning_effort'] == chat['reasoning_effort'] == 'none'
        assert tokens == {
            'content': 'FULL CHAT TEMPLATE',
            'add_special': True,
            'parse_special': True,
        }
        assert chat['stream'] is False
        assert chat.get('max_completion_tokens', chat.get('max_tokens')) == 1536
        assert result.input_tokens == 17 and result.output_tokens == 8
        assert result.finish_reason == 'stop'
        assert result.server_timings['prompt_ms'] == 10.0
        assert result.text == 'A supported answer [1].'


def test_timeouts_are_errors(tmp_path):
    with httpx.Client(transport=transport([], timeout=True)) as http:
        client = LLMClient(load_settings(tmp_path), profile(), http_client=http)
        with pytest.raises(RagError) as error:
            client.count_input_tokens([HumanMessage(content='Q?')])
        assert error.value.code == 'llm_timeout'
        with pytest.raises(RagError) as error:
            client.generate([HumanMessage(content='Q?')], max_tokens=10)
        assert error.value.code == 'llm_timeout'


def startup_inputs(tmp_path, monkeypatch, *, foreign=False, never_ready=False):
    settings = load_settings(tmp_path).model_copy(
        update={'llama_server_bin': '/bin/true', 'model_path': tmp_path / 'model.gguf'}
    )
    settings.model_path.write_bytes(b'GGUF')
    state = {'started': foreign, 'spawns': []}

    def handle(request):
        if request.url.path == '/health':
            if not state['started']:
                raise httpx.ConnectError('not running', request=request)
            return httpx.Response(503 if never_ready else 200, json={'status': 'ok'})
        if request.url.path == '/props':
            return httpx.Response(
                200,
                json={
                    'model_path': '/foreign.gguf' if foreign else str(settings.model_path),
                    'default_generation_settings': {'n_ctx': 8192},
                    'total_slots': 1,
                    'chat_template': 'template',
                    'build_info': 'b11046-60081bb2b',
                },
            )
        return transport([]).handle_request(request)

    http = httpx.Client(transport=httpx.MockTransport(handle))

    def spawn(argv, **kwargs):
        state['started'] = True
        state['spawns'].append(argv)
        return NS(pid=123, poll=lambda: None)

    session = NS(require_active=lambda: None, spawn=spawn)
    monkeypatch.setattr(llama, 'binary_version', lambda *a: 'b11046-60081bb2b')
    return settings, http, session, state


def test_client_does_not_spawn_per_generate(tmp_path, monkeypatch):
    settings, http, session, state = startup_inputs(tmp_path, monkeypatch)
    with http:
        client = llama.start_llama(settings, profile(), session, http_client=http)
        for _ in range(2):
            client.generate([HumanMessage(content='Q?')], max_tokens=10)
    assert len(state['spawns']) == 1
    argv = state['spawns'][0]
    assert argv[argv.index('--ctx-size') + 1] == '8192'
    assert argv[argv.index('--parallel') + 1] == '1'
    assert argv[argv.index('--fit') + 1] == 'off'
    assert '--no-context-shift' in argv and '--no-cache-prompt' in argv
    assert argv[argv.index('--reasoning') + 1] == 'off'


def test_foreign_server_not_killed(tmp_path, monkeypatch):
    settings, http, session, state = startup_inputs(tmp_path, monkeypatch, foreign=True)
    with http, pytest.raises(RagError) as error:
        llama.start_llama(settings, profile(), session, http_client=http)
    assert error.value.code == 'llm_conflict'
    assert state['spawns'] == []


def test_startup_timeout_distinct(tmp_path, monkeypatch):
    settings, http, session, state = startup_inputs(tmp_path, monkeypatch, never_ready=True)
    with http, pytest.raises(RagError) as error:
        llama.start_llama(
            settings, profile(startup_timeout_seconds=0.01), session, http_client=http
        )
    assert error.value.code == 'llm_startup_timeout'
