"""Unavailable is not absent: no GPU/server management on uncertain HTTP state."""

import errno
import socket
from types import SimpleNamespace as NS

import httpcore
import httpx
import pytest
from qdrant_client.http.exceptions import ResponseHandlingException

from dnd_rag.config import LLMProfile, load_settings
from dnd_rag.contracts import RagError
from dnd_rag.indexing.store import QdrantStore
from dnd_rag.runtime import application, llama


def failure(kind, request=None):
    if kind == 'timeout':
        return httpx.ReadTimeout('read timed out', request=request)
    if kind == 'protocol':
        return httpx.RemoteProtocolError('incomplete response', request=request)
    error = httpx.ConnectError('connection failed', request=request)
    if kind in ('dns', 'refused'):
        source = (
            ConnectionRefusedError(errno.ECONNREFUSED, 'connection refused')
            if kind == 'refused'
            else socket.gaierror(socket.EAI_NONAME, 'cannot resolve host')
        )
        # httpcore keeps the original OSError in args rather than __cause__.
        error.__cause__ = httpcore.ConnectError(source)
    return error


@pytest.mark.parametrize('kind', ['timeout', 'protocol', 'dns', 'unknown_connect'])
def test_gpu_preflight_does_not_treat_transport_failure_as_absence(tmp_path, monkeypatch, kind):
    def get(*args, **kwargs):
        raise failure(kind)

    monkeypatch.setattr(application.httpx, 'get', get)
    with pytest.raises(RagError) as error:
        application._check_gpu_conflict(load_settings(tmp_path))
    assert error.value.code == 'llm_preflight_failed'


def test_gpu_preflight_allows_confirmed_connection_refusal(tmp_path, monkeypatch):
    def get(*args, **kwargs):
        raise failure('refused')

    monkeypatch.setattr(application.httpx, 'get', get)
    application._check_gpu_conflict(load_settings(tmp_path))


@pytest.mark.parametrize('suffix', ['/v1', '/v1/'])
@pytest.mark.parametrize('status', [200, 503, 404])
def test_gpu_preflight_checks_native_health_for_both_url_spellings(
    tmp_path, monkeypatch, suffix, status
):
    paths = []

    def handle(request):
        paths.append(request.url.path)
        return httpx.Response(status)

    settings = load_settings(tmp_path).model_copy(
        update={'llm_base_url': 'http://127.0.0.1:8080' + suffix}
    )
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        monkeypatch.setattr(application.httpx, 'get', client.get)
        with pytest.raises(RagError) as error:
            application._check_gpu_conflict(settings)
    assert error.value.code == 'gpu_conflict'
    assert paths == ['/health']


@pytest.mark.parametrize('kind', ['timeout', 'protocol', 'dns', 'unknown_connect'])
def test_llama_preflight_does_not_start_after_uncertain_response(tmp_path, monkeypatch, kind):
    def handle(request):
        raise failure(kind, request)

    monkeypatch.setattr(
        llama, 'server_argv', lambda *args: pytest.fail('Uncertain endpoint permitted launch')
    )
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(RagError) as error:
            llama.start_llama(
                load_settings(tmp_path),
                LLMProfile(),
                NS(require_active=lambda: None),
                http_client=client,
            )
    assert error.value.code == 'llm_preflight_failed'


@pytest.mark.parametrize('kind', ['timeout', 'protocol', 'dns', 'unknown_connect'])
def test_qdrant_preflight_does_not_compose_after_uncertain_response(tmp_path, monkeypatch, kind):
    def info():
        raise ResponseHandlingException(failure(kind))

    settings = load_settings(tmp_path)
    store = QdrantStore(settings, client=NS(info=info))
    monkeypatch.setattr(application, 'QdrantStore', lambda *args: store)

    def no_compose(*args, **kwargs):
        __tracebackhide__ = True  # Do not print the subprocess environment on the RED run.
        pytest.fail('Unexpected Compose')

    monkeypatch.setattr(application.subprocess, 'run', no_compose)
    with pytest.raises(RagError) as error:
        application.ensure_qdrant(settings, NS(require_active=lambda: None))
    assert error.value.code == ('qdrant_timeout' if kind == 'timeout' else 'qdrant_unavailable')


def test_qdrant_compose_still_starts_confirmed_absent_local_server(tmp_path, monkeypatch):
    calls = []

    def info():
        if not calls:
            raise ResponseHandlingException(failure('refused'))
        return NS(version='1.20.0')

    settings = load_settings(tmp_path)
    store = QdrantStore(settings, client=NS(info=info))
    monkeypatch.setattr(application, 'QdrantStore', lambda *args: store)

    def compose(argv, **kwargs):
        calls.append(argv)
        return NS(returncode=0)

    monkeypatch.setattr(application.subprocess, 'run', compose)
    assert application.ensure_qdrant(settings, NS(require_active=lambda: None)) is store
    assert len(calls) == 1 and calls[0][-3:] == ['up', '-d', 'qdrant']
