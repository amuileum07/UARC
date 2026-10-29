"""Open a real native webview and verify browser features and the Python bridge."""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from queue import Empty, Queue
from threading import Thread
from time import monotonic
from uuid import uuid4

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

    return ThreadingHTTPServer(("127.0.0.1", 0), ReportHandler)


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
        thread = Thread(
            target=server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True
        )
        thread.start()
        try:
            with (root / "desktop.log").open("w", encoding="utf-8") as log:
                print(f"GUI launching: {args.command[0]}", flush=True)
                process = subprocess.Popen(
                    [
                        *args.command,
                        "--frontend",
                        str(page),
                        "--data-dir",
                        str(root / "data"),
                    ],
                    cwd=root,
                    env=environment,
                    stdout=log,
                    stderr=log,
                )
                try:
                    deadline = monotonic() + 60
                    stage = "no JavaScript report"
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
                                    else "No final JavaScript report within 60 seconds"
                                ),
                                "stage": stage,
                            }
                        break
                    else:
                        report = {
                            "ok": False,
                            "error": "No final JavaScript report within 60 seconds",
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
            print("GUI stopping callback server", flush=True)
            server.shutdown()
            thread.join(timeout=5)


if __name__ == "__main__":
    main()
