"""Open a real native webview and verify browser features and the Python bridge."""

import argparse
import faulthandler
import json
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import chdir
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from queue import Empty, Queue
from threading import Event, Thread
from time import monotonic
from typing import TextIO
from uuid import uuid4

GUI_TIMEOUT_SECONDS = 60

PAGE = """<!doctype html><html lang="ko"><meta charset="utf-8">
<title>UARC GUI verification</title><p>UARC 웹뷰 검증</p><script>
let started = false;
async function report(value) {
  const response = await fetch(CALLBACK, {
    method: 'POST', body: JSON.stringify(value),
    headers: {'Content-Type': 'text/plain;charset=UTF-8'}
  });
  if (!response.ok) throw Error('GUI callback failed: HTTP ' + response.status);
}
report({stage: 'page-loaded'}).catch(error => console.error(String(error)));
async function check() {
  if (started) return;
  started = true;
  let result;
  try {
    await report({stage: 'bridge-ready'});
    if (!window.isSecureContext || typeof crypto.randomUUID !== 'function' ||
        typeof structuredClone !== 'function' || typeof Object.hasOwn !== 'function')
      throw Error('The webview lacks browser features required by the frontend');
    const api = window.pywebview.api;
    const design = structuredClone(await api.get_example_design());
    if (!design.components.length || crypto.randomUUID().length !== 36)
      throw Error('Invalid starting design or browser UUID');
    design.environment.elevation_mode = 'manual';
    const preview = await api.preview_design(JSON.stringify(design));
    if (!(preview.simulation.rocket.radius > 0)) throw Error('Invalid bridge preview');
    result = {ok: true, userAgent: navigator.userAgent};
  } catch (error) {
    result = {ok: false, error: String(error)};
  }
  await report(result);
}
window.addEventListener('pywebviewready', check, {once: true});
if (window.pywebview?.api?.get_example_design) check();
</script></html>"""


def report_server(token: str, reports: Queue) -> ThreadingHTTPServer:
    """Browser-preopened sockets must not block reports or server shutdown."""

    class ReportHandler(BaseHTTPRequestHandler):
        timeout = 3

        def reply(self, status):
            self.send_response(status)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Content-Length", "0")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True

        def do_OPTIONS(self):
            self.reply(204 if self.path == token else 404)

        def do_POST(self):
            if self.path != token:
                self.reply(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 4096:
                    raise ValueError("Invalid callback length")
                report = json.loads(self.rfile.read(length))
                if not isinstance(report, dict) or (
                    type(report.get("ok")) is not bool
                    and report.get("stage") not in ("page-loaded", "bridge-ready")
                ):
                    raise ValueError("Invalid callback report")
            except TimeoutError:
                self.reply(408)
                return
            except (ValueError, UnicodeError):
                self.reply(400)
                return
            self.reply(204)
            reports.put(report)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), ReportHandler)
    server.timeout = 0.2
    # Selector readiness can become stale before accept(); bound the listener too.
    server.socket.settimeout(0.2)
    return server


def launch_desktop(
    command: list[str], root: Path, environment: dict[str, str], log: TextIO
) -> subprocess.Popen:
    if sys.platform == "darwin":
        executable = shutil.which(command[0])
        if executable is None:
            raise FileNotFoundError(command[0])
        # Keep virtualenv/symlink identity: resolve() could select the base Python.
        command = [os.path.abspath(executable), *command[1:]]
        # CPython 3.13 uses posix_spawn on macOS only without cwd/close_fds.
        # Change the harness's cwd before servicing connections; the listener
        # and log descriptors are non-inheritable, and only stdout/stderr are duped.
        with chdir(root):
            return subprocess.Popen(
                command, env=environment, stdout=log, stderr=log, close_fds=False
            )
    return subprocess.Popen(command, cwd=root, env=environment, stdout=log, stderr=log)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", nargs=argparse.REMAINDER, help="UARC launcher command"
    )
    args = parser.parse_args()
    if not args.command:
        parser.error("Pass a launcher, e.g. /path/to/UARC or python -m app.")
    reports = Queue()
    token = "/" + uuid4().hex

    with (
        tempfile.TemporaryDirectory(prefix="uarc gui 한글 ") as temporary,
        report_server(token, reports) as server,
    ):
        root = Path(temporary)
        page = root / "검증 page.html"
        callback = f"http://127.0.0.1:{server.server_port}{token}"
        page.write_text(
            PAGE.replace("CALLBACK", json.dumps(callback)), encoding="utf-8"
        )
        environment = dict(
            os.environ,
            PYTHONPATH="",
            PYTHONDONTWRITEBYTECODE="1",
            PYTHONUTF8="1",
            PYTHONUNBUFFERED="1",
        )
        environment.pop("PYTHONHOME", None)
        stop = Event()
        thread = None

        def serve_reports():
            while not stop.is_set():
                server.handle_request()

        # Keep diagnostics armed through launch, callback waits and cleanup.
        faulthandler.dump_traceback_later(20, repeat=True)
        try:
            with (root / "desktop.log").open("w", encoding="utf-8") as log:
                print(f"GUI launching: {args.command[0]}", flush=True)
                # A Windows SOCKET handle is not a CRT file descriptor.
                if server.socket.get_inheritable() or os.get_inheritable(log.fileno()):
                    raise RuntimeError("GUI harness descriptors must not be inherited.")
                process = launch_desktop(
                    [
                        *args.command,
                        "--frontend",
                        str(page),
                        "--data-dir",
                        str(root / "data"),
                    ],
                    root,
                    environment,
                    log,
                )
                print(f"GUI desktop started: PID {process.pid}", flush=True)
                try:
                    deadline = monotonic() + GUI_TIMEOUT_SECONDS
                    stage = "no JavaScript report"
                    # Start only after exec; HTTP dispatch cannot block supervision.
                    thread = Thread(
                        target=serve_reports, name="uarc-gui-reports", daemon=True
                    )
                    print("GUI starting callback server", flush=True)
                    thread.start()
                    while monotonic() < deadline:
                        try:
                            report = reports.get(timeout=0.2)
                            if "ok" not in report:
                                stage = report["stage"]
                                print(f"GUI stage: {stage}", flush=True)
                                continue
                        except Empty:
                            if process.poll() is None:
                                continue
                            report = {
                                "ok": False,
                                "error": (
                                    f"Webview exited ({process.returncode})"
                                    if process.poll() is not None
                                    else f"No final JavaScript report within {GUI_TIMEOUT_SECONDS} seconds"
                                ),
                                "stage": stage,
                            }
                        break
                    else:
                        report = {
                            "ok": False,
                            "error": f"No final JavaScript report within {GUI_TIMEOUT_SECONDS} seconds",
                            "stage": stage,
                        }
                finally:
                    print("GUI stopping desktop process", flush=True)
                    # No flight is submitted; stop only this test's desktop process.
                    if process.poll() is None:
                        process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=10)
            if not isinstance(report, dict) or report.get("ok") is not True:
                details = (root / "desktop.log").read_text(
                    encoding="utf-8", errors="replace"
                )
                message = f"GUI verification failed: {report}\n{details[-12000:]}"
                print(message, file=sys.stderr, flush=True)
                raise RuntimeError(message)
            print(
                f"GUI verified: native webview, browser features, bridge preview; {report['userAgent']}"
            )
        finally:
            stop.set()
            if thread is not None and thread.ident is not None:
                thread.join(timeout=1)
            print("GUI closing callback server", flush=True)
            faulthandler.cancel_dump_traceback_later()


if __name__ == "__main__":
    main()
