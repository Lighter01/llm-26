"""A stable lock inode, held by inherited open descriptions until all children exit."""

import fcntl
import os
from pathlib import Path

from dnd_rag.contracts import RagError


class ProjectLock:
    def __init__(self, project_root: Path):
        self.path = project_root / '.runtime/project.lock'
        self.fd = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(fd)
            raise RagError('runtime_busy', 'Another project runtime is already active') from exc
        self.fd = fd
        return self

    def __exit__(self, *args):
        if self.fd is not None:
            # LOCK_UN would also unlock a description inherited by a live child.
            os.close(self.fd)
            self.fd = None
