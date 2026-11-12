from contextlib import contextmanager
from types import SimpleNamespace as NS

import pytest

from dnd_rag.contracts import RagError


def test_startup_order_and_failure_prevent_downstream_start(tmp_path, monkeypatch):
    from dnd_rag.runtime import application as app

    events = []

    @contextmanager
    def session(*args):
        events.append('lock')
        try:
            yield NS()
        finally:
            events.append('cleanup')

    @contextmanager
    def server(*args, **kwargs):
        events.append('mcp' if kwargs.get('port') == 8765 else 'proxy')
        yield NS()

    monkeypatch.setattr(app, 'RuntimeSession', session)
    monkeypatch.setattr(app, 'ensure_infrastructure', lambda *a: events.append('infra'))
    monkeypatch.setattr(app, 'ensure_game_catalog', lambda *a: events.append('catalog'))
    monkeypatch.setattr(
        app, 'prepare_retriever', lambda *a, **k: events.append('index-worker-exited')
    )
    monkeypatch.setattr(app, 'start_llama', lambda *a: events.append('llama'))
    monkeypatch.setattr(app, 'background_server', server)
    monkeypatch.setattr(app, 'create_mcp_server', lambda *a: NS(streamable_http_app=lambda: None))
    monkeypatch.setattr(app, 'create_codex_proxy', lambda *a, **k: None)
    monkeypatch.setattr(app, 'ObservationRecorder', lambda *a, **k: NS())
    monkeypatch.setattr(app, 'AgentService', lambda **k: NS())
    monkeypatch.setattr(app, 'load_rag_config', lambda *a, **k: NS())
    with app.application_stack(
        NS(project_root=tmp_path), NS(mcp_url='http://127.0.0.1:8765/mcp'), NS()
    ):
        events.append('interface')
    assert events == [
        'lock',
        'infra',
        'catalog',
        'index-worker-exited',
        'llama',
        'mcp',
        'proxy',
        'interface',
        'cleanup',
    ]
    events.clear()

    def failed(*a, **k):
        raise RagError('build_error', 'Worker failed')

    monkeypatch.setattr(app, 'prepare_retriever', failed)
    with pytest.raises(RagError):
        with app.application_stack(
            NS(project_root=tmp_path), NS(mcp_url='http://127.0.0.1:8765/mcp'), NS()
        ):
            pass
    assert events == ['lock', 'infra', 'catalog', 'cleanup']


def test_immediate_restart_ignores_time_wait_but_refuses_foreign_listener():
    import socket

    import httpx
    from fastapi import FastAPI

    from dnd_rag.runtime.application import background_server

    app = FastAPI()

    @app.get('/health')
    def health():
        return {'ok': True}

    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(('127.0.0.1', 0))
    port = listener.getsockname()[1]
    listener.listen()
    with pytest.raises(RagError, match='Cannot bind'):
        with background_server(app, port=port):
            pass
    client = socket.create_connection(('127.0.0.1', port))
    accepted, _ = listener.accept()
    accepted.shutdown(socket.SHUT_WR)
    accepted.close()
    client.recv(1)
    client.close()
    listener.close()
    with background_server(app, port=port):
        assert httpx.get(f'http://127.0.0.1:{port}/health').json() == {'ok': True}
