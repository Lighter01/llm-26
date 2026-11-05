import os
import signal
import subprocess
import sys
from time import monotonic, sleep

import pytest

from dnd_rag.contracts import RagError
from dnd_rag.runtime.lock import ProjectLock
from dnd_rag.runtime.processes import RuntimeSession


def eventually(predicate, timeout=8):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if predicate():
            return
        sleep(0.03)
    raise AssertionError('Condition not reached')


def test_second_runtime_refused_before_side_effects(tmp_path):
    with RuntimeSession(tmp_path):
        with pytest.raises(RagError, match='[Rr]untime'):
            with RuntimeSession(tmp_path):
                pytest.fail('Second runtime entered')
    with RuntimeSession(tmp_path):
        pass


def test_interrupt_only_owned_children(tmp_path):
    sentinel = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(30)'])
    try:
        with pytest.raises(KeyboardInterrupt):
            with RuntimeSession(tmp_path) as session:
                child = session.spawn([sys.executable, '-c', 'import time;time.sleep(30)'])
                raise KeyboardInterrupt
        assert child.poll() is not None
        assert sentinel.poll() is None
        with ProjectLock(tmp_path):
            pass
    finally:
        sentinel.terminate()
        sentinel.wait(timeout=5)


def test_parent_death_child_keeps_lock(tmp_path):
    pid_file = tmp_path / 'child.pid'
    script = """
import sys,time
from pathlib import Path
from dnd_rag.runtime.processes import RuntimeSession
with RuntimeSession(Path(sys.argv[1])) as session:
    child=session.spawn([sys.executable,'-c','import time;time.sleep(30)'])
    Path(sys.argv[2]).write_text(str(child.pid))
    time.sleep(30)
"""
    parent = subprocess.Popen([sys.executable, '-c', script, str(tmp_path), str(pid_file)])
    child_pid = None
    try:
        eventually(pid_file.exists)
        child_pid = int(pid_file.read_text())
        parent.kill()
        parent.wait(timeout=5)
        with pytest.raises(RagError):
            with ProjectLock(tmp_path):
                pytest.fail('Parent death released inherited lock')
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait(timeout=5)
        if child_pid is not None:
            os.kill(child_pid, signal.SIGTERM)

    def reacquire():
        try:
            with ProjectLock(tmp_path):
                return True
        except RagError:
            return False

    eventually(reacquire)
