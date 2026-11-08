"""Nonblocking advisory guards for lock-owner cleanup and release mutations."""
from __future__ import annotations

import contextlib
import errno
import os
import threading
from pathlib import Path

_registry_lock = threading.Lock()
_thread_locks: dict[str, threading.Lock] = {}
_CONTENDED_ERRNOS = {errno.EACCES, errno.EAGAIN}


def _lock_is_contended(error: OSError) -> bool:
    if error.errno in _CONTENDED_ERRNOS:
        return True
    return os.name == "nt" and getattr(error, "winerror", None) == 33


def _thread_lock(path: Path) -> threading.Lock:
    key = os.path.normcase(os.path.abspath(path))
    with _registry_lock:
        return _thread_locks.setdefault(key, threading.Lock())


@contextlib.contextmanager
def advisory_guard(path: str | os.PathLike):
    """Yield whether a nonblocking per-path thread and OS lock was acquired."""
    guard_path = Path(path)
    thread_lock = _thread_lock(guard_path)
    if not thread_lock.acquire(blocking=False):
        yield False
        return

    handle = None
    os_locked = False
    try:
        guard_path.parent.mkdir(parents=True, exist_ok=True)
        handle = guard_path.open("a+b")
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if _lock_is_contended(exc):
                yield False
                return
            raise
        os_locked = True

        yield True
    finally:
        if os_locked and handle is not None:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        if handle is not None:
            try:
                handle.close()
            except OSError:
                pass
        thread_lock.release()
