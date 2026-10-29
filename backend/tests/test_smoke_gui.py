"""Offline GUI-report regressions without opening a desktop window."""

import http.client
import io
import json
import os
import runpy
import shlex
import socket
import sys
import tempfile
import threading
import unittest
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from queue import Queue
from threading import Event, Thread
from unittest.mock import patch

SMOKE = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "scripts/smoke_gui.py")
)


@contextmanager
def running_server():
    reports = Queue()
    server = SMOKE["report_server"]("/test-token", reports)
    thread = Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
    )
    thread.start()
    try:
        yield server, reports
    finally:
        server.shutdown()
        thread.join(timeout=1)
        server.server_close()


class GUIReportTests(unittest.TestCase):
    def test_report_server_never_resolves_its_numeric_loopback_address(self):
        with (
            patch("socket.getfqdn", side_effect=AssertionError("Slow reverse DNS")),
            running_server() as (server, reports),
        ):
            connection = http.client.HTTPConnection(*server.server_address, timeout=1)
            try:
                connection.request("POST", "/test-token", '{"stage":"page-loaded"}')
                response = connection.getresponse()
                self.assertEqual(response.status, 204)
                response.read()
                self.assertEqual(reports.get(timeout=1), {"stage": "page-loaded"})
            finally:
                connection.close()

    def test_preopened_idle_socket_does_not_block_reports_or_shutdown(self):
        with running_server() as (server, reports):
            accepted = Event()
            setup = server.RequestHandlerClass.setup

            def record_setup(handler):
                setup(handler)
                accepted.set()

            with (
                patch.object(server.RequestHandlerClass, "setup", record_setup),
                socket.create_connection(server.server_address, timeout=1),
            ):
                self.assertTrue(accepted.wait(timeout=1))
                connection = http.client.HTTPConnection(
                    *server.server_address, timeout=1
                )
                try:
                    payload = {"ok": True, "userAgent": "offline-test"}
                    connection.request("POST", "/test-token", json.dumps(payload))
                    response = connection.getresponse()
                    self.assertEqual(response.status, 204)
                    self.assertEqual(response.read(), b"")
                    self.assertEqual(reports.get(timeout=1), payload)
                finally:
                    connection.close()
                stopped = Thread(target=server.shutdown, daemon=True)
                stopped.start()
                stopped.join(timeout=1)
                self.assertFalse(
                    stopped.is_alive(), "Idle browser socket blocked shutdown"
                )

    def test_partial_request_body_has_a_finite_read_timeout(self):
        with running_server() as (server, reports):
            server.RequestHandlerClass.timeout = 0.1
            with socket.create_connection(server.server_address, timeout=2) as client:
                client.sendall(
                    b"POST /test-token HTTP/1.0\r\nContent-Length: 100\r\n\r\n{"
                )
                response = http.client.HTTPResponse(client)
                response.begin()
                self.assertEqual(response.status, 408)
                self.assertEqual(response.read(), b"")
            self.assertTrue(reports.empty())

    def test_preflight_and_invalid_reports_never_count_as_success(self):
        with running_server() as (server, reports):
            connection = http.client.HTTPConnection(*server.server_address, timeout=1)
            try:
                connection.request("OPTIONS", "/test-token")
                response = connection.getresponse()
                self.assertEqual(response.status, 204)
                self.assertEqual(response.getheader("Access-Control-Allow-Origin"), "*")
                self.assertIn(
                    "POST", response.getheader("Access-Control-Allow-Methods")
                )
                response.read()
                for body, headers in (
                    (b"{}", {"Content-Length": "not-an-integer"}),
                    (b"{}", {"Content-Length": "4097"}),
                    (b"broken", {}),
                    (b"[]", {}),
                    (b'{"stage": {}}', {}),
                ):
                    with self.subTest(body=body, headers=headers):
                        connection.request("POST", "/test-token", body, headers)
                        response = connection.getresponse()
                        self.assertEqual(response.status, 400)
                        response.read()
                self.assertTrue(reports.empty())
            finally:
                connection.close()

    def test_early_exit_keeps_native_logs_and_failure_stage(self):
        output = io.StringIO()
        threads_before = set(threading.enumerate())

        def start(*args, **kwargs):
            self.assertEqual(set(threading.enumerate()), threads_before)
            kwargs["stdout"].write("native loader failure marker\n")
            kwargs["stdout"].flush()
            process = launch.return_value
            process.returncode = 17
            process.poll.return_value = 17
            process.wait.return_value = 17
            return process

        with (
            patch("sys.argv", ["smoke_gui.py", "fake-uarc"]),
            patch("subprocess.Popen", side_effect=start) as launch,
            patch("faulthandler.dump_traceback_later") as watchdog,
            patch("faulthandler.cancel_dump_traceback_later") as cancel_watchdog,
            redirect_stdout(output),
            redirect_stderr(output),
            self.assertRaisesRegex(RuntimeError, r"Webview exited \(17\)"),
        ):
            SMOKE["main"]()
        self.assertIn("native loader failure marker", output.getvalue())
        self.assertIn("no JavaScript report", output.getvalue())
        self.assertIn("GUI closing callback server", output.getvalue())
        watchdog.assert_called_once_with(20, repeat=True)
        cancel_watchdog.assert_called_once_with()
        self.assertEqual(launch.call_args.kwargs["env"]["PYTHONUTF8"], "1")
        launch.return_value.terminate.assert_not_called()

    @unittest.skipUnless(
        hasattr(os, "posix_spawn"), "Requires a POSIX process launcher"
    )
    def test_darwin_launch_uses_real_posix_spawn_and_preserves_cwd_and_fds(self):
        before = Path.cwd()
        with tempfile.TemporaryDirectory(prefix="uarc spawn 한글 ") as temporary:
            root = Path(temporary)
            # Real executable-script launch, including a path with spaces/Unicode.
            launcher = root / "installed uarc"
            code = "import json, os; print(json.dumps({'cwd': os.getcwd()}))"
            launcher.write_text(
                f"#!/bin/sh\nexec {shlex.quote(sys.executable)} -c {shlex.quote(code)}\n",
                encoding="utf-8",
            )
            launcher.chmod(0o755)
            with (
                SMOKE["report_server"]("/token", Queue()) as server,
                (root / "child.log").open("w", encoding="utf-8") as log,
                patch("sys.platform", "darwin"),
                patch("os.posix_spawn", wraps=os.posix_spawn) as spawn,
            ):
                self.assertFalse(os.get_inheritable(server.fileno()))
                self.assertFalse(os.get_inheritable(log.fileno()))
                process = SMOKE["launch_desktop"](
                    [str(launcher)], root, dict(os.environ), log
                )
                self.assertEqual(process.wait(timeout=5), 0)
                spawn.assert_called_once()
            self.assertEqual(Path.cwd(), before)
            result = json.loads((root / "child.log").read_text(encoding="utf-8"))
            self.assertEqual(Path(result["cwd"]).resolve(), root.resolve())

    def test_darwin_failed_spawn_restores_the_parent_cwd(self):
        before = Path.cwd()
        with (
            tempfile.TemporaryDirectory() as temporary,
            (Path(temporary) / "child.log").open("w", encoding="utf-8") as log,
            patch("sys.platform", "darwin"),
            patch("subprocess.Popen", side_effect=OSError("launch failed")),
            self.assertRaisesRegex(OSError, "launch failed"),
        ):
            SMOKE["launch_desktop"](
                [sys.executable], Path(temporary), dict(os.environ), log
            )
        self.assertEqual(Path.cwd(), before)


if __name__ == "__main__":
    unittest.main()
