"""Direct native output capture; keep fatal tracebacks on a stable file descriptor."""

import ctypes
import errno
import faulthandler
import io
import os
import sys
from contextlib import contextmanager, suppress
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import Lock


def _flush_c_stdio():
    with suppress(OSError, AttributeError):
        ctypes.CDLL("ucrtbase" if os.name == "nt" else None).fflush(None)


@contextmanager
def capture_output(path: Path):
    """Yield an idempotent stream restore callback; retain fatal traces until exit."""
    original = sys.stdout, sys.stderr
    missing = set()
    saved = {}
    streams = []
    lock = Lock()
    fault_enabled = False
    previous_fault = faulthandler.is_enabled()

    def restore(*_):
        with lock:
            for stream in streams:
                # A full disk must not prevent restoring the host's descriptors.
                with suppress(OSError, ValueError):
                    stream.flush()
            _flush_c_stdio()
            sys.stdout, sys.stderr = original
            for descriptor, previous in saved.items():
                os.dup2(previous, descriptor)
                os.close(previous)
            saved.clear()

    try:
        # Reserve missing standard descriptors before opening the log or making
        # backups, so a windowed executable cannot reuse fd 1/2 for those files.
        for descriptor in (1, 2):
            try:
                os.fstat(descriptor)
            except OSError as error:
                if error.errno != errno.EBADF:
                    raise
                temporary = os.open(os.devnull, os.O_WRONLY)
                if temporary != descriptor:
                    os.dup2(temporary, descriptor)
                    os.close(temporary)
                missing.add(descriptor)
        for stream in original:
            if stream is not None:
                with suppress(OSError, ValueError):
                    stream.flush()
        _flush_c_stdio()
        with path.open("xb", buffering=0) as log:
            try:
                for descriptor in (1, 2):
                    saved[descriptor] = os.dup(descriptor)
                    os.dup2(log.fileno(), descriptor)
                    # Cached console handlers follow fd 1/2 back to the console
                    # (or devnull) after startup, rather than retaining the log.
                    streams.append(
                        io.TextIOWrapper(
                            io.FileIO(descriptor, "w", closefd=False),
                            encoding="utf-8",
                            errors="backslashreplace",
                            line_buffering=True,
                            write_through=True,
                        )
                    )
                sys.stdout, sys.stderr = streams
                faulthandler.enable(file=log)
                fault_enabled = True
                yield restore
            finally:
                restore()
                if fault_enabled:
                    faulthandler.disable()
                if previous_fault and 2 not in missing:
                    faulthandler.enable(file=2)
    finally:
        for descriptor in missing:
            os.close(descriptor)


@contextmanager
def desktop_native_output(directory: Path):
    """Rotate between launches only; a fatal handler must never hold a rotated fd."""
    directory = directory.expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "native.log"
    if path.exists() or path.is_symlink():
        handler = RotatingFileHandler(path, backupCount=3, delay=True)
        try:
            handler.doRollover()
        finally:
            handler.close()
    with capture_output(path) as restore:
        print(f"Native desktop startup pid={os.getpid()}", flush=True)
        yield restore
