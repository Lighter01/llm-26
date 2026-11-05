"""One runtime and its owned process groups; no global process-name termination."""

import os
import signal
import subprocess

from dnd_rag.contracts import RagError
from dnd_rag.runtime.lock import ProjectLock


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

    def close(self):
        for process in reversed(self.children):
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
        self.children.clear()
        self.lock.__exit__(None, None, None)

    def __exit__(self, *args):
        self.close()
