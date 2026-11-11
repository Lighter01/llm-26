"""Linux directory exchange for the isolated ingestion CLI; standard library only."""

import ctypes
import os
import re
import stat
import sys


def exchange(parent: str, staged: str, current: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{64}", current):
        raise ValueError("Expected the current build signature")
    if os.path.basename(staged) != staged or not staged.startswith(f".{current}.staging-"):
        raise ValueError("Expected a sibling staging directory for this build")
    descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for name in (staged, current):
            if not stat.S_ISDIR(os.stat(name, dir_fd=descriptor, follow_symlinks=False).st_mode):
                raise ValueError("Exchange requires real directories, without symlinks")
        libc = ctypes.CDLL(None, use_errno=True)
        rename = libc.renameat2
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        if rename(descriptor, os.fsencode(staged), descriptor, os.fsencode(current), 2):
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error))
    finally:
        os.close(descriptor)


if __name__ == "__main__":
    exchange(*sys.argv[1:])
