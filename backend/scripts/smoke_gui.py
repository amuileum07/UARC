"""Open a real native webview and verify browser features and the Python bridge."""

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import chdir, closing
from pathlib import Path
from time import monotonic, sleep
from typing import TextIO
from uuid import uuid4

GUI_TIMEOUT_SECONDS = 60

PAGE = """<!doctype html><html lang="ko"><meta charset="utf-8">
<title>UARC GUI verification</title><p>UARC 웹뷰 검증</p><script>
window.__uarcGuiStage = 'page-loaded';
let started = false;
async function check() {
  if (started) return;
  started = true;
  const api = window.pywebview.api;
  window.__uarcGuiStage = 'getting-example';
  const design = await api.get_example_design();
  design.environment.elevation_mode = 'manual';
  async function report(value) {
    window.__uarcGuiStage = value.stage || (value.ok ? 'passed' : 'failed');
    const proof = {token: TOKEN, ...value};
    if (proof.error) proof.error = proof.error.slice(0, 64);
    // A design name is limited to 128 characters, including JSON escaping.
    while (JSON.stringify(proof).length > 128 && proof.error?.length)
      proof.error = proof.error.slice(0, -1);
    await api.save_design(JSON.stringify({...design, name: JSON.stringify(proof)}));
  }
  try {
    await report({stage: 'bridge-ready'});
    if (!window.isSecureContext || typeof crypto.randomUUID !== 'function' ||
        typeof structuredClone !== 'function' || typeof Object.hasOwn !== 'function')
      throw Error('The webview lacks browser features required by the frontend');
    const preview = await api.preview_design(JSON.stringify(structuredClone(design)));
    if (!design.components.length || crypto.randomUUID().length !== 36 ||
        !(preview.simulation.rocket.radius > 0)) throw Error('Invalid bridge preview');
    await report({ok: true});
  } catch (error) {
    await report({ok: false, error: String(error)});
  }
}
window.addEventListener('pywebviewready', () => check().catch(console.error), {once: true});
if (window.pywebview?.api?.get_example_design) check().catch(console.error);
</script></html>"""


def saved_reports(data: Path, token: str) -> list[dict]:
    """Observe committed save_design calls, using only this test's application data."""
    database = data / "uarc.sqlite3"
    if not database.is_file():
        return []
    try:
        with closing(
            sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=0.2)
        ) as connection:
            names = connection.execute("SELECT name FROM designs").fetchall()
    except sqlite3.OperationalError as error:
        if str(error) not in {"no such table: designs", "database is locked"}:
            raise
        return []  # Initialization or a write transaction is still in progress.
    reports = []
    for (name,) in names:
        try:
            report = json.loads(name)
        except (ValueError, TypeError):
            continue
        if (
            isinstance(report, dict)
            and report.get("token") == token
            and (
                type(report.get("ok")) is bool or report.get("stage") == "bridge-ready"
            )
        ):
            reports.append(report)
    return reports


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
        # The log is non-inheritable; no harness worker threads precede launch.
        with chdir(root):
            return subprocess.Popen(
                command, env=environment, stdout=log, stderr=log, close_fds=False
            )
    return subprocess.Popen(command, cwd=root, env=environment, stdout=log, stderr=log)


def stop_desktop(process: subprocess.Popen) -> None:
    if process.poll() is None:
        if sys.platform == "win32":
            # Installed uarc.exe is a launcher with a Python child. Killing only
            # the launcher leaves that child holding the application's owner lock.
            result = subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
            )
            if result.returncode and process.poll() is None:
                raise RuntimeError(
                    f"Cannot stop GUI process tree: {result.stdout}\n{result.stderr}"
                )
        else:
            process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, help="Preserve diagnostics in a new directory"
    )
    parser.add_argument(
        "command", nargs=argparse.REMAINDER, help="UARC launcher command"
    )
    args = parser.parse_args()
    if not args.command:
        parser.error("Pass a launcher, e.g. /path/to/UARC or python -m app.")
    deadline = monotonic() + GUI_TIMEOUT_SECONDS
    token = uuid4().hex
    with tempfile.TemporaryDirectory(prefix="uarc gui 한글 ") as temporary:
        root = Path(temporary)
        if args.output is not None:
            root = args.output.resolve()
            root.mkdir(parents=True, exist_ok=False)
        page = root / "검증 page.html"
        page.write_text(PAGE.replace("TOKEN", json.dumps(token)), encoding="utf-8")
        data = root / "data"
        environment = dict(
            os.environ,
            PYTHONPATH="",
            PYTHONDONTWRITEBYTECODE="1",
            PYTHONUTF8="1",
            PYTHONUNBUFFERED="1",
            PYWEBVIEW_LOG="DEBUG",
        )
        environment.pop("PYTHONHOME", None)
        with (root / "desktop.log").open("w", encoding="utf-8") as log:
            print(f"GUI launching: {args.command[0]}", flush=True)
            if os.get_inheritable(log.fileno()):
                raise RuntimeError("GUI harness log must not be inherited.")
            process = launch_desktop(
                [*args.command, "--frontend", str(page), "--data-dir", str(data)],
                root,
                environment,
                log,
            )
            print(f"GUI desktop started: PID {process.pid}", flush=True)
            stage = "no committed bridge report"
            report = None
            try:
                with (root / "desktop.log").open(
                    encoding="utf-8", errors="replace"
                ) as desktop_log:
                    while monotonic() < deadline:
                        details = desktop_log.read(12000)
                        if details:
                            print(details, file=sys.stderr, end="", flush=True)
                        for value in saved_reports(data, token):
                            if "ok" in value:
                                report = value
                                break
                            if stage != value["stage"]:
                                stage = value["stage"]
                                print(f"GUI stage: {stage}", flush=True)
                        if report is not None:
                            break
                        if process.poll() is not None:
                            report = {
                                "ok": False,
                                "error": f"Webview exited ({process.returncode})",
                            }
                            break
                        sleep(0.2)
                    else:
                        report = {
                            "ok": False,
                            "error": f"No final bridge report within {GUI_TIMEOUT_SECONDS} seconds",
                        }
            finally:
                print("GUI stopping desktop process", flush=True)
                stop_desktop(process)
        if report.get("ok") is not True:
            details = (root / "desktop.log").read_text(
                encoding="utf-8", errors="replace"
            )
            message = (
                f"GUI verification failed at {stage}: {report}\n{details[-12000:]}"
            )
            print(message, file=sys.stderr, flush=True)
            raise RuntimeError(message)
        assert "Bridge completed method=save_design" in (data / "uarc.log").read_text(
            encoding="utf-8"
        )
        print(
            "GUI verified: native webview, browser features, bridge preview, saved design."
        )


if __name__ == "__main__":
    main()
