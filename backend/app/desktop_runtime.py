"""Keep an older Conda C++ runtime from shadowing Linux graphics dependencies."""

import ctypes
import os
import re
import sys
import sysconfig
from pathlib import Path


def _glibcxx_version(library: Path) -> tuple[int, ...]:
    versions = re.findall(rb"GLIBCXX_(\d+\.\d+(?:\.\d+)?)\x00", library.read_bytes())
    return max((tuple(map(int, value.split(b"."))) for value in versions), default=())


def prepare_desktop_runtime() -> None:
    """Select the newer system libstdc++ before importing Qt or numerical modules.

    Conda Python's ELF RPATH can select its old libstdc++ even with no
    LD_LIBRARY_PATH. Loading the system library first fixes host dlopen calls;
    LD_PRELOAD gives QtWebEngine's child processes the same library. This is
    scoped to this desktop process and its children, never the user's shell.
    """
    if sys.platform != "linux" or getattr(sys, "frozen", False):
        return
    base = Path(sys.base_prefix)
    conda_library = base / "lib" / "libstdc++.so.6"
    if not (base / "conda-meta").is_dir() or not conda_library.is_file():
        return
    preload = os.environ.get("LD_PRELOAD", "")
    if "libstdc++" in preload:
        # An explicit user-selected runtime takes precedence.
        return
    multiarch = sysconfig.get_config_var("MULTIARCH")
    candidates = [Path("/usr/lib64/libstdc++.so.6")]
    if multiarch:
        candidates.insert(0, Path("/usr/lib") / multiarch / "libstdc++.so.6")
    system_library = next((path for path in candidates if path.is_file()), None)
    if system_library is None or system_library.resolve() == conda_library.resolve():
        return
    try:
        if _glibcxx_version(system_library) <= _glibcxx_version(conda_library):
            return
        ctypes.CDLL(str(system_library), mode=ctypes.RTLD_GLOBAL)
    except OSError as error:
        raise RuntimeError(
            "Cannot initialize the system C++ runtime for Qt. Recreate the virtual "
            "environment with uv-managed Python instead of Conda Python."
        ) from error
    os.environ["LD_PRELOAD"] = " ".join(filter(None, (str(system_library), preload)))
    print("UARC: using system libstdc++ for Conda desktop rendering.", file=sys.stderr)
