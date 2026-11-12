import pytest

from dnd_rag.contracts import RagError


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
