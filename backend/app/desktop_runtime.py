"""Prepare platform runtimes before starting the native webview."""

import ctypes
import logging
import os
import re
import subprocess
import sys
import sysconfig
import webbrowser
from pathlib import Path
from socketserver import TCPServer
from urllib.parse import quote
from wsgiref.simple_server import WSGIServer


class _LoopbackWSGIServer(WSGIServer):
    def server_bind(self):
        if self.server_address[0] not in {"127.0.0.1", "::1"}:
            return super().server_bind()
        # HTTPServer's getfqdn(loopback) can stall for 30+ s on macOS 15.
        # Binding an explicit loopback IP needs no reverse DNS lookup.
        TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]
        self.setup_environ()


def encode_webview_url(window, renderer: str) -> None:
    """Cocoa's NSURL needs an encoded URL, including non-ASCII local filenames."""
    if renderer == "wkwebview" and window.real_url:
        # Keep RFC 3986 delimiters and existing escapes; encode Unicode/spaces.
        window.real_url = quote(window.real_url, safe=":/?#[]@!$&'()*+,;=%")


def log_webview_document(window) -> None:
    """Debug the document actually loaded, including a failed navigation's page."""
    details = window.evaluate_js(
        "({url: location.href, title: document.title, ready: document.readyState, "
        "bridge: typeof window.pywebview?.api?.get_example_design, "
        "probe: window.__uarcGuiStage || null})"
    )
    logging.getLogger("pywebview").debug("Loaded document: %s", details)


def open_external_url(url: str) -> bool:
    """Keep frozen Linux libraries out of the system browser's environment."""
    if sys.platform != "linux" or not getattr(sys, "frozen", False):
        return webbrowser.open(url)
    environment = dict(os.environ)
    original = environment.get("LD_LIBRARY_PATH_ORIG")
    if original is None:
        environment.pop("LD_LIBRARY_PATH", None)
    else:
        environment["LD_LIBRARY_PATH"] = original
    try:
        process = subprocess.Popen(
            ["xdg-open", url],
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return False
    return process.poll() in (None, 0)


def _glibcxx_version(library: Path) -> tuple[int, ...]:
    versions = re.findall(rb"GLIBCXX_(\d+\.\d+(?:\.\d+)?)\x00", library.read_bytes())
    return max((tuple(map(int, value.split(b"."))) for value in versions), default=())


def prepare_desktop_runtime() -> None:
    """Prepare the Mac loopback server or select the newer Linux libstdc++.

    Mac's local HTTP server must not depend on reverse DNS before listening.

    Conda Python's ELF RPATH can select its old libstdc++ even with no
    LD_LIBRARY_PATH. Loading the system library first fixes host dlopen calls;
    LD_PRELOAD gives QtWebEngine's child processes the same library. This is
    scoped to this desktop process and its children, never the user's shell.
    """
    if sys.platform == "darwin":
        from webview import http

        # pywebview 6.2.1 starts this server asynchronously, before listening.
        # A slow DNS lookup otherwise makes WKWebView's first navigation fail.
        # Replace only its WSGI class; retain Bottle routing and bridge endpoints.
        http.WSGIServer = _LoopbackWSGIServer
        return
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
