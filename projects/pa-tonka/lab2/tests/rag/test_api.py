from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace as NS

import httpx
import pytest
from fastapi.testclient import TestClient

from dnd_rag.api import create_app
from dnd_rag.contracts import RagError, RetrievalResult
from tests.rag.test_qa_service import service


def retrieval_only():
    retriever = NS(
        config=NS(retrieval=NS(limit=10)),
        index=NS(index_id='a' * 64, build_id='build1'),
        readiness=lambda: {'index_ready': True, 'query_encoder_ready': True},
        retrieve=lambda question, limit=None: RetrievalResult(
            question=question,
            index_id='a' * 64,
            build_id='build1',
            mode='dense',
            hits=[],
            timings_ms={'query_embedding': 1.0, 'search': 2.0, 'total': 3.0},
        ),
    )
    return retriever


def qa_client(monkeypatch, tmp_path):
    import dnd_rag.api as api

    monkeypatch.setattr(api, 'ERROR_LOG', tmp_path / 'errors.log')
    rag, calls = service()
    retriever = retrieval_only()
    client = TestClient(create_app(retriever, rag), raise_server_exceptions=False)
    return client, retriever, rag, calls


def test_retrieval_only_contract():
    retriever = retrieval_only()
    with TestClient(create_app(retriever, None)) as client:
        health = client.get('/health')
        assert health.status_code == 200
        assert health.json()['mode'] == 'retrieval_only'
        assert health.json()['retrieval_ready'] is True
        assert health.json()['qa_ready'] is False
        assert client.post('/retrieve', json={'question': 'Q?', 'limit': 3}).status_code == 200
        response = client.post('/ask', json={'question': 'Q?'})
        assert response.status_code == 503 and response.json()['error']['code'] == 'qa_disabled'


@pytest.mark.parametrize(
    'route,body',
    [
        ('/ask', {}),
        ('/ask', {'question': ''}),
        ('/ask', {'question': '  '}),
        ('/ask', {'question': 7}),
        ('/ask', {'question': 'Q?', 'history': []}),
        ('/ask', {'question': 'Q?', 'model': 'other'}),
        ('/retrieve', {'question': 'Q?', 'limit': 0}),
        ('/retrieve', {'question': 'Q?', 'limit': 11}),
        ('/retrieve', {'question': 'Q?', 'limit': 1.0}),
        ('/retrieve', {'question': 'Q?', 'limit': True}),
    ],
)
def test_bad_input_error_envelope(route, body, monkeypatch, tmp_path):
    client, *_ = qa_client(monkeypatch, tmp_path)
    response = client.post(route, json=body)
    assert response.status_code == 422
    assert set(response.json()) == {'error'}
    assert response.json()['error']['code'].startswith('invalid_')


@pytest.mark.parametrize(
    'error,status',
    [
        (RagError('embedding_input_too_long', 'Too long'), 422),
        (RagError('context_budget_exceeded', 'Shorten your question'), 422),
        (RagError('index_not_ready', 'Index unavailable'), 503),
        (RagError('qdrant_unavailable', 'Service unavailable'), 503),
        (RagError('llm_timeout', 'Generation timed out'), 504),
        (httpx.ReadTimeout('Timeout'), 504),
        (RuntimeError('PRIVATE STACK DETAIL'), 500),
    ],
)
def test_api_error_envelope(error, status, monkeypatch, tmp_path):
    client, _, rag, _ = qa_client(monkeypatch, tmp_path)

    def fail(question):
        raise error

    rag.ask = fail
    response = client.post('/ask', json={'question': 'Q?'})
    assert response.status_code == status
    assert set(response.json()) == {'error'}
    assert 'PRIVATE STACK DETAIL' not in response.text
    if status == 500:
        assert 'PRIVATE STACK DETAIL' in (tmp_path / 'errors.log').read_text()
    # Errors release the gate too.
    assert client.post('/ask', json={'question': 'Again?'}).status_code == status


def test_readiness_distinguishes_dependencies(monkeypatch, tmp_path):
    client, retriever, rag, _ = qa_client(monkeypatch, tmp_path)
    assert client.get('/health').json()['qa_ready'] is True
    rag.llm.is_ready = lambda: False
    response = client.get('/health')
    assert response.status_code == 200 and response.json()['qa_ready'] is False
    assert client.post('/ask', json={'question': 'Q?'}).status_code == 503
    assert client.post('/retrieve', json={'question': 'Q?'}).status_code == 200
    retriever.readiness = lambda: {'index_ready': False, 'query_encoder_ready': True}
    response = client.get('/health')
    assert response.status_code == 503 and response.json()['retrieval_ready'] is False
    assert client.post('/retrieve', json={'question': 'Q?'}).status_code == 503


def test_second_generation_is_busy(monkeypatch, tmp_path):
    client, _, rag, _ = qa_client(monkeypatch, tmp_path)
    entered, release = Event(), Event()
    original = rag.ask

    def blocked(question):
        entered.set()
        assert release.wait(5)
        return original(question)

    rag.ask = blocked
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(client.post, '/ask', json={'question': 'First?'})
        try:
            assert entered.wait(5)
            second = client.post('/ask', json={'question': 'Second?'})
            assert second.status_code == 429 and second.json()['error']['code'] == 'qa_busy'
            assert client.post('/retrieve', json={'question': 'Other?'}).status_code == 200
        finally:
            release.set()
        assert first.result().status_code == 200


def test_stateless_ask(monkeypatch, tmp_path):
    client, _, _, calls = qa_client(monkeypatch, tmp_path)
    for question in ('First secret question?', 'Second current question?'):
        assert client.post('/ask', json={'question': question}).status_code == 200
    assert len(calls) == 2
    second_prompt = str(calls[1][0])
    assert 'Second current question?' in second_prompt
    assert 'First secret question?' not in second_prompt
    assert 'The supported rule [1]' not in second_prompt
