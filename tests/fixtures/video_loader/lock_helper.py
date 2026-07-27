"""Windows-specific helper to simulate a locked/inaccessible video file.

FILE_LOCKED_OR_INACCESSIBLE (see contracts/video_loader_contract.md) models a
file another process holds open exclusively -- e.g. an antivirus scan or an
in-progress copy. On Windows, OS-level mandatory byte-range locking (via
`msvcrt.locking`) reproduces this deterministically within a single test
process: while the lock is held, another handle attempting to read the locked
byte range raises a PermissionError/OSError -- the same exception loader.py's
locked-file detection (T022) is expected to catch. Windows-only, matching the
project's Windows-first target platform (constitution Non-Negotiables).
"""

from __future__ import annotations

import contextlib
import msvcrt
import os
from pathlib import Path
from typing import Iterator, Union


@contextlib.contextmanager
def locked_file(path: Union[str, Path]) -> Iterator[None]:
    """Hold an exclusive lock on the first bytes of `path` for the `with` block."""
    path = Path(path)
    lock_length = max(path.stat().st_size, 1)
    fd = os.open(str(path), os.O_RDWR)
    try:
        msvcrt.locking(fd, msvcrt.LK_NBLCK, lock_length)
        try:
            yield
        finally:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, lock_length)
    finally:
        os.close(fd)
