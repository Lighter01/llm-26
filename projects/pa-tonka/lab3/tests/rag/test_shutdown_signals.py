import os
import signal
import subprocess
import sys
from time import monotonic, sleep

import pytest

from dnd_rag.runtime.lock import ProjectLock
from tests.rag.test_runtime import eventually, running


@pytest.mark.parametrize('registration_signal', [None, 'SIGINT', 'SIGTERM'])
def test_real_signal_cleans_owned_child_and_releases_lock(tmp_path, registration_signal):
    pid_file = tmp_path / 'child.pid'
    script = """
import os,signal,subprocess,sys,time
from pathlib import Path
from dnd_rag.runtime.processes import RuntimeSession
root, pid_file, race = sys.argv[1:]
original = subprocess.Popen
def spawn(*args, **kwargs):
    child = original(*args, **kwargs)
    Path(pid_file).write_text(str(child.pid))
    if race != 'None':
        os.kill(os.getpid(), getattr(signal, race))
    return child
subprocess.Popen = spawn
with RuntimeSession(Path(root)) as runtime:
    runtime.spawn([sys.executable, '-c', 'import time;time.sleep(30)'])
    time.sleep(30)
"""
    sentinel = subprocess.Popen(
        [sys.executable, '-c', 'import time;time.sleep(30)'], start_new_session=True
    )
    parent = subprocess.Popen(
        [sys.executable, '-c', script, str(tmp_path), str(pid_file), str(registration_signal)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    child = None
    try:
        eventually(pid_file.exists)
        child = int(pid_file.read_text())
        if registration_signal is None:
            sleep(0.1)  # The parent has registered the child before ordinary SIGTERM.
            parent.terminate()
        parent.wait(timeout=5)
        deadline = monotonic() + 1
        while running(child) and monotonic() < deadline:
            sleep(0.02)
        assert not running(child), 'Launcher left its child alive after a real signal'
        with ProjectLock(tmp_path):
            pass
        assert sentinel.poll() is None
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait(timeout=5)
        if child is not None and running(child):
            os.kill(child, signal.SIGKILL)
            eventually(lambda: not running(child))
        sentinel.terminate()
        sentinel.wait(timeout=5)


def test_runtime_restores_original_signal_handlers(tmp_path):
    from dnd_rag.runtime.processes import RuntimeSession

    before = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    with RuntimeSession(tmp_path):
        pass
    assert {sig: signal.getsignal(sig) for sig in before} == before
