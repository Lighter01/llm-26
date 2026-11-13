"""One runtime and its owned process groups; no global process-name termination."""

import os
import signal
import subprocess
import threading
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


def owned_process_groups(leaders, ownership_fd):
    """Verify original groups using a live leader or its inherited open FLOCK."""
    alive = {pid for pid, live in leaders.items() if live}
    pending = set(leaders) - alive
    if not pending:
        return alive
    marker = _flock_record(Path(f'/proc/self/fdinfo/{ownership_fd}'))
    if marker is None:
        raise RagError('runtime_cleanup_failed', 'Cannot verify the inherited ownership lock')
    for stat in Path('/proc').glob('[0-9]*/stat'):
        try:
            fields = stat.read_text().rsplit(')', 1)[1].split()
            group = int(fields[2])
            if group not in pending or fields[0] == 'Z':
                continue
            # Opening the same pathname is insufficient: this FLOCK description
            # must have been inherited from the owning launcher.
            if any(_flock_record(fd) == marker for fd in (stat.parent / 'fdinfo').glob('*')):
                alive.add(group)
                pending.remove(group)
        except (OSError, ValueError, IndexError):
            continue
    return alive


class RuntimeSession:
    def __init__(self, project_root):
        self.project_root = project_root
        self.lock = ProjectLock(project_root)
        self.children = []
        self._handlers = {}
        self._deferring = 0
        self._pending_signal = None

    def __enter__(self):
        self.lock.__enter__()
        if threading.current_thread() is threading.main_thread():
            for sig in (signal.SIGINT, signal.SIGTERM):
                self._handlers[sig] = signal.getsignal(sig)
                signal.signal(sig, self._handle_signal)
        return self

    def _handle_signal(self, sig, frame):
        if self._deferring:
            self._pending_signal = sig
        else:
            self._raise_signal(sig)

    @staticmethod
    def _raise_signal(sig):
        if sig == signal.SIGINT:
            raise KeyboardInterrupt
        raise SystemExit(128 + sig)

    def _dispatch_pending(self):
        if not self._deferring and self._pending_signal is not None:
            sig, self._pending_signal = self._pending_signal, None
            self._raise_signal(sig)

    def require_active(self):
        if self.lock.fd is None:
            raise RagError('runtime_inactive', 'Runtime session must hold the project lock')

    def spawn(self, argv, *, env=None, stdout=None):
        self.require_active()
        child_env = {**os.environ, **(env or {}), 'DND_RAG_LOCK_FD': str(self.lock.fd)}
        # Defer Python signal handling, not the OS signal mask: children retain
        # normal TERM/INT handling, even when interrupted during Popen itself.
        self._deferring += 1
        try:
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
        finally:
            self._deferring -= 1
            self._dispatch_pending()

    def _owned_groups(self):
        return owned_process_groups(
            {process.pid: process.poll() is None for process in self.children}, self.lock.fd
        )

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
        self._deferring += 1
        try:
            self._signal_groups(signal.SIGTERM)
            if not self._wait_groups(5):
                self._signal_groups(signal.SIGKILL)
                if not self._wait_groups(5):
                    # Keep the parent's lock while shutdown is unconfirmed.
                    raise RagError('runtime_cleanup_failed', 'Owned process groups did not stop')
            self.children.clear()
            self.lock.__exit__(None, None, None)
        finally:
            for sig, previous in self._handlers.items():
                signal.signal(sig, previous)
            self._handlers.clear()
            self._deferring -= 1
            self._dispatch_pending()

    def __exit__(self, *args):
        self.close()
