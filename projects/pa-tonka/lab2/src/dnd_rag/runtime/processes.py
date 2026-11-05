"""One runtime and its owned process groups; no global process-name termination."""

import os
import signal
import subprocess
from pathlib import Path
from time import monotonic, sleep

from dnd_rag.contracts import RagError
from dnd_rag.runtime.lock import ProjectLock


def _flock_record(path):
    try:
        for line in path.read_text().splitlines():
            fields = line.split()
            if fields[:1] == ['lock:'] and fields[2:3] == ['FLOCK']:
                return fields[2:]
    except OSError:
        pass
    return None


class RuntimeSession:
    def __init__(self, project_root):
        self.project_root = project_root
        self.lock = ProjectLock(project_root)
        self.children = []

    def __enter__(self):
        self.lock.__enter__()
        return self

    def require_active(self):
        if self.lock.fd is None:
            raise RagError('runtime_inactive', 'Runtime session must hold the project lock')

    def spawn(self, argv, *, env=None, stdout=None):
        self.require_active()
        child_env = {**os.environ, **(env or {}), 'DND_RAG_LOCK_FD': str(self.lock.fd)}
        process = subprocess.Popen(
            list(argv),
            cwd=self.project_root,
            env=child_env,
            pass_fds=(self.lock.fd,),
            start_new_session=True,
            stdout=stdout,
            stderr=subprocess.STDOUT if stdout is not None else None,
        )
        self.children.append(process)
        return process

    def _owned_groups(self):
        # An unreaped live leader still owns its PID. Once it exits, a saved PGID
        # alone is unsafe: it can eventually be reused by an unrelated process.
        alive = {process.pid for process in self.children if process.poll() is None}
        pending = {process.pid for process in self.children} - alive
        if not pending:
            return alive
        marker = _flock_record(Path(f'/proc/self/fdinfo/{self.lock.fd}'))
        if marker is None:
            raise RagError('runtime_cleanup_failed', 'Cannot verify the inherited runtime lock')
        for stat in Path('/proc').glob('[0-9]*/stat'):
            try:
                fields = stat.read_text().rsplit(')', 1)[1].split()
                group = int(fields[2])
                if group not in pending or fields[0] == 'Z':
                    continue
                # A shared FLOCK record proves inheritance of this open lock
                # description; merely opening the same lock pathname does not.
                if any(_flock_record(fd) == marker for fd in (stat.parent / 'fdinfo').glob('*')):
                    alive.add(group)
                    pending.remove(group)
            except (OSError, ValueError, IndexError):
                continue  # A process can exit while /proc is being inspected.
        return alive

    def _signal_groups(self, sig):
        for group in self._owned_groups():
            try:
                os.killpg(group, sig)
            except ProcessLookupError:
                pass

    def _wait_groups(self, timeout):
        deadline = monotonic() + timeout
        while self._owned_groups():
            if monotonic() >= deadline:
                return False
            sleep(0.03)
        return True

    def close(self):
        self._signal_groups(signal.SIGTERM)
        if not self._wait_groups(5):
            self._signal_groups(signal.SIGKILL)
            if not self._wait_groups(5):
                # Keep the parent's lock while shutdown is unconfirmed.
                raise RagError('runtime_cleanup_failed', 'Owned process groups did not stop')
        self.children.clear()
        self.lock.__exit__(None, None, None)

    def __exit__(self, *args):
        self.close()
