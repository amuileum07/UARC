"""Open a real native webview and verify browser features and the Python bridge."""

import argparse
import json
import os
import subprocess
import tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from queue import Empty, Queue
from threading import Thread
from time import monotonic
from uuid import uuid4

PAGE = """<!doctype html><html lang="ko"><meta charset="utf-8">
<title>UARC GUI verification</title><p>UARC 웹뷰 검증</p><script>
let started = false;
async function check() {
  if (started) return;
  started = true;
  let result;
  try {
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
  await fetch(CALLBACK, {method: 'POST', body: JSON.stringify(result)});
}
window.addEventListener('pywebviewready', check, {once: true});
if (window.pywebview?.api?.get_example_design) check();
</script></html>"""


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

    class ReportHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            if self.path != token or not 0 < length <= 4096:
                self.send_error(400)
                return
            reports.put(json.loads(self.rfile.read(length)))
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

        def log_message(self, *args):
            pass

    with (
        tempfile.TemporaryDirectory(prefix="uarc gui 한글 ") as temporary,
        HTTPServer(("127.0.0.1", 0), ReportHandler) as server,
    ):
        root = Path(temporary)
        page = root / "검증 page.html"
        callback = f"http://127.0.0.1:{server.server_port}{token}"
        page.write_text(
            PAGE.replace("CALLBACK", json.dumps(callback)), encoding="utf-8"
        )
        environment = dict(os.environ, PYTHONPATH="", PYTHONDONTWRITEBYTECODE="1")
        environment.pop("PYTHONHOME", None)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with (root / "desktop.log").open("w", encoding="utf-8") as log:
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
                    while True:
                        try:
                            report = reports.get(timeout=0.2)
                        except Empty:
                            if process.poll() is None and monotonic() < deadline:
                                continue
                            report = {
                                "ok": False,
                                "error": "Webview exited or timed out",
                            }
                        break
                finally:
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
                raise RuntimeError(
                    f"GUI verification failed: {report}\n{details[-12000:]}"
                )
            print(
                f"GUI verified: native webview, browser features, bridge preview; {report['userAgent']}"
            )
        finally:
            server.shutdown()
            thread.join(timeout=5)


if __name__ == "__main__":
    main()
