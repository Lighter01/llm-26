import os
import signal
import subprocess
import sys
from pathlib import Path
from time import monotonic, sleep
from types import SimpleNamespace as NS

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


def running(pid):
    try:
        return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[0] != 'Z'
    except FileNotFoundError:
        return False


@pytest.mark.parametrize('wrapper_exits,ignore_term', [(True, False), (False, True)])
def test_close_stops_descendants_when_group_leader_exits(tmp_path, wrapper_exits, ignore_term):
    pid_file = tmp_path / 'descendant.pid'
    script = """
import os,signal,sys,time
from pathlib import Path
if os.fork() == 0:
    if sys.argv[3] == '1':
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    Path(sys.argv[1]).write_text(str(os.getpid()))
    while True:
        time.sleep(.1)
if sys.argv[2] == '1':
    os._exit(0)
while True:
    time.sleep(.1)
"""
    sentinel = subprocess.Popen(
        [sys.executable, '-c', 'import time;time.sleep(30)'], start_new_session=True
    )
    session = RuntimeSession(tmp_path).__enter__()
    leader, descendant = None, None
    try:
        leader = session.spawn(
            [
                sys.executable,
                '-c',
                script,
                str(pid_file),
                str(int(wrapper_exits)),
                str(int(ignore_term)),
            ]
        )
        eventually(pid_file.exists)
        descendant = int(pid_file.read_text())
        if wrapper_exits:
            assert leader.wait(timeout=5) == 0
        session.close()
        eventually(lambda: not running(descendant), timeout=2)
        with ProjectLock(tmp_path):
            pass
        assert sentinel.poll() is None
    finally:
        # RED must not leave the intentionally orphaned/TERM-ignoring descendant alive.
        if descendant is not None and running(descendant):
            os.kill(descendant, signal.SIGKILL)
            eventually(lambda: not running(descendant))
        if leader is not None and leader.poll() is None:
            leader.kill()
            leader.wait(timeout=5)
        session.close()
        sentinel.terminate()
        sentinel.wait(timeout=5)


def test_close_does_not_signal_a_reused_foreign_group_id(tmp_path):
    sentinel = None
    ready = tmp_path / 'foreign.ready'
    script = """
import sys,time
from pathlib import Path
with open(sys.argv[1]):
    Path(sys.argv[2]).touch()
    time.sleep(30)
"""
    try:
        with RuntimeSession(tmp_path) as session:
            sentinel = subprocess.Popen(
                [sys.executable, '-c', script, str(session.lock.path), str(ready)],
                start_new_session=True,
            )
            eventually(ready.exists)
            # A reaped historical leader's PGID can now name an unrelated group.
            # Opening the same lock inode is not ownership of its FLOCK description.
            session.children.append(NS(pid=sentinel.pid, poll=lambda: 0))
        assert sentinel.poll() is None
        with ProjectLock(tmp_path):
            pass
    finally:
        if sentinel is not None:
            sentinel.terminate()
            sentinel.wait(timeout=5)
