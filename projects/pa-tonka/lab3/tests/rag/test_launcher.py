from types import SimpleNamespace as NS

import pytest

from dnd_rag.config import RuntimeSettings
from dnd_rag.contracts import RagError
from dnd_rag.runtime import application as launcher
from tests.rag.fixtures import baseline_data, write_yaml


def setup_launcher(tmp_path, monkeypatch, *, reused=False, failure=False):
    config = write_yaml(tmp_path / 'config.yaml', baseline_data())
    profile = write_yaml(tmp_path / 'llm.yaml', {})
    settings = RuntimeSettings(project_root=tmp_path, model_path=tmp_path / 'missing.gguf')
    events, calls = [], []

    def ensure(*args, **kwargs):
        calls.append('ensure_reused' if reused else 'ensure_built')
        if failure:
            raise RagError('build_worker_failed', 'Fixture failure')
        return NS(
            index=NS(index_id='a' * 64, build_id='build1'),
            stages=[],
            action='reused' if reused else 'built',
        )

    monkeypatch.setattr(launcher, 'ensure_index', ensure)
    monkeypatch.setattr(launcher, '_load_retriever', lambda *a: calls.append('cpu') or NS())
    monkeypatch.setattr(launcher, '_preflight_http', lambda *a, **k: None)
    monkeypatch.setattr(
        launcher, '_start_llm', lambda *a: calls.append('llm') or NS(close=lambda: None)
    )
    monkeypatch.setattr(launcher, '_make_app', lambda *a: NS())

    def http(app, settings, session, on_ready):
        on_ready()

    monkeypatch.setattr(launcher, '_serve_http', http)
    monkeypatch.setattr(launcher, '_start_ui', lambda *a: calls.append('ui'))
    return config, profile, settings, events, calls


@pytest.mark.parametrize('reused', [False, True])
def test_cold_demo_start_order(tmp_path, monkeypatch, reused):
    config, profile, settings, events, calls = setup_launcher(tmp_path, monkeypatch, reused=reused)
    launcher.run_demo(config, profile, settings, on_event=events.append)
    assert events == [
        'index_ready',
        'gpu_worker_exited',
        'cpu_query_loaded',
        'llm_ready',
        'api_ready',
        'ui_started',
    ]
    assert calls == ['ensure_reused' if reused else 'ensure_built', 'cpu', 'llm', 'ui']


def test_build_failure_starts_no_llm_or_ui(tmp_path, monkeypatch):
    config, profile, settings, events, calls = setup_launcher(tmp_path, monkeypatch, failure=True)
    with pytest.raises(RagError, match='Fixture failure'):
        launcher.run_demo(config, profile, settings, on_event=events.append)
    assert calls == ['ensure_built'] and events == []


def test_serve_has_no_llama_dependencies(tmp_path, monkeypatch):
    config, _, settings, events, calls = setup_launcher(tmp_path, monkeypatch, reused=True)
    settings = settings.model_copy(
        update={'model_path': tmp_path / 'missing.gguf', 'llama_server_bin': 'missing-llama'}
    )
    launcher.serve_retrieval(config, settings, on_event=events.append)
    assert calls == ['ensure_reused', 'cpu']
    assert events == ['index_ready', 'gpu_worker_exited', 'cpu_query_loaded', 'api_ready']


def test_http_preflight_allows_immediate_restart_after_closed_connection(tmp_path):
    import socket

    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
        listener.listen()
        with socket.create_connection(('127.0.0.1', port)) as client:
            connection, _ = listener.accept()
            connection.close()
            assert client.recv(1) == b''
    settings = RuntimeSettings(
        project_root=tmp_path,
        model_path=tmp_path / 'missing.gguf',
        rag_api_url=f'http://127.0.0.1:{port}',
    )
    launcher._preflight_http(settings, demo=False)


def test_http_preflight_rejects_foreign_listener(tmp_path):
    import socket

    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        port = listener.getsockname()[1]
        settings = RuntimeSettings(
            project_root=tmp_path,
            model_path=tmp_path / 'missing.gguf',
            rag_api_url=f'http://127.0.0.1:{port}',
        )
        with pytest.raises(RagError) as error:
            launcher._preflight_http(settings, demo=False)
        assert error.value.code == 'http_conflict'
        assert listener.fileno() != -1


def real_server(tmp_path, kind):
    import socket
    import sys

    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    if kind == 'uvicorn':
        (tmp_path / 'probe_api.py').write_text(
            "from fastapi import FastAPI\napp=FastAPI()\n@app.get('/health')\ndef health():return {}\n"
        )
        argv = [
            sys.executable,
            '-m',
            'uvicorn',
            'probe_api:app',
            '--app-dir',
            str(tmp_path),
            '--host',
            '127.0.0.1',
            '--port',
            str(port),
        ]
        path = '/health'
    else:
        script = tmp_path / 'probe_ui.py'
        script.write_text("import streamlit as st\nst.write('Lifecycle probe')\n")
        argv = [
            sys.executable,
            '-m',
            'streamlit',
            'run',
            str(script),
            '--server.address',
            '127.0.0.1',
            '--server.port',
            str(port),
            '--server.headless',
            'true',
            '--server.fileWatcherType',
            'none',
            '--browser.gatherUsageStats',
            'false',
        ]
        path = '/_stcore/health'
    return argv, f'http://127.0.0.1:{port}{path}'


def wait_http(url):
    import httpx

    from tests.rag.test_runtime import eventually

    def ready():
        try:
            return httpx.get(url, timeout=0.5).status_code == 200
        except httpx.TransportError:
            return False

    eventually(ready, timeout=15)


@pytest.mark.parametrize('kind', ['uvicorn', 'streamlit'])
def test_real_child_keeps_lock_after_parent_death(tmp_path, kind):
    import json
    import os
    import signal
    import subprocess
    import sys

    from dnd_rag.runtime.lock import ProjectLock
    from tests.rag.test_runtime import eventually

    argv, url = real_server(tmp_path, kind)
    pid_file = tmp_path / 'pid'
    script = """
import json,sys,time
from pathlib import Path
from dnd_rag.runtime.processes import RuntimeSession
with RuntimeSession(Path(sys.argv[1])) as session:
    child=session.spawn(json.loads(sys.argv[3]))
    Path(sys.argv[2]).write_text(str(child.pid))
    time.sleep(40)
"""
    with (tmp_path / 'child.log').open('w') as log:
        parent = subprocess.Popen(
            [sys.executable, '-c', script, str(tmp_path), str(pid_file), json.dumps(argv)],
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        child_pid = None
        try:
            eventually(pid_file.exists)
            child_pid = int(pid_file.read_text())
            wait_http(url)
            parent.kill()
            parent.wait(timeout=5)
            with pytest.raises(RagError):
                with ProjectLock(tmp_path):
                    pytest.fail('A real child lost the inherited lock')
        finally:
            if parent.poll() is None:
                parent.kill()
                parent.wait(timeout=5)
            if child_pid is not None:
                os.killpg(child_pid, signal.SIGTERM)

    def unlocked():
        try:
            with ProjectLock(tmp_path):
                return True
        except RagError:
            return False

    eventually(unlocked)


@pytest.mark.parametrize('kind', ['uvicorn', 'streamlit'])
def test_real_child_cleanup_preserves_foreign_process(tmp_path, kind):
    import subprocess
    import sys

    from dnd_rag.runtime.processes import RuntimeSession

    argv, url = real_server(tmp_path, kind)
    sentinel = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(40)'])
    try:
        with (tmp_path / 'child.log').open('w') as log:
            with pytest.raises(KeyboardInterrupt):
                with RuntimeSession(tmp_path) as session:
                    child = session.spawn(argv, stdout=log)
                    wait_http(url)
                    raise KeyboardInterrupt
        assert child.poll() is not None
        assert sentinel.poll() is None
    finally:
        sentinel.terminate()
        sentinel.wait(timeout=5)
