"""Socket-handle and bounded-supervision checks without a native GUI."""

import errno
import io
import os
import runpy
import socket
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from queue import Queue
from time import monotonic
from unittest.mock import Mock, patch

SMOKE = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "scripts/smoke_gui.py")
)


class GUIPortabilityTests(unittest.TestCase):
    def test_windows_socket_handle_is_not_passed_to_crt_fd_api(self):
        server = SMOKE["report_server"]("/test-token", Queue())
        self.addCleanup(server.server_close)
        handle = server.fileno()
        socket_flag_value = server.socket.get_inheritable()
        real_get_inheritable = os.get_inheritable

        def crt_only(descriptor):
            if descriptor == handle:
                raise OSError(errno.EBADF, "SOCKET is not a CRT file descriptor")
            return real_get_inheritable(descriptor)

        process = Mock(pid=1234, returncode=17)
        process.poll.return_value = 17
        process.wait.return_value = 17
        output = io.StringIO()
        with (
            patch("sys.argv", ["smoke_gui.py", "fake-uarc"]),
            patch("sys.platform", "win32"),
            patch.dict(SMOKE["main"].__globals__, {"report_server": lambda *_: server}),
            patch("os.get_inheritable", side_effect=crt_only),
            patch.object(
                socket.socket,
                "get_inheritable",
                autospec=True,
                return_value=socket_flag_value,
            ) as socket_flag,
            patch("subprocess.Popen", return_value=process) as launch,
            patch("faulthandler.dump_traceback_later"),
            patch("faulthandler.cancel_dump_traceback_later"),
            redirect_stdout(output),
            redirect_stderr(output),
            self.assertRaisesRegex(RuntimeError, r"Webview exited \(17\)"),
        ):
            SMOKE["main"]()
        socket_flag.assert_called_once_with(server.socket)
        launch.assert_called_once()

    def test_stale_selector_readiness_cannot_block_accept(self):
        class ReadySelector:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                pass

            def register(self, *_):
                pass

            def select(self, _timeout):
                return [(None, 1)]

        errors = Queue()
        with SMOKE["report_server"]("/test-token", Queue()) as server:

            def handle_once():
                try:
                    server.handle_request()
                except Exception as error:
                    errors.put(error)

            worker = threading.Thread(target=handle_once, daemon=True)
            with patch("socketserver._ServerSelector", ReadySelector):
                worker.start()
                worker.join(timeout=1)
                stalled = worker.is_alive()
                if stalled:
                    # Release even the old blocking accept so a failing test
                    # never leaves a live request supervisor behind.
                    with socket.create_connection(server.server_address, timeout=1):
                        pass
                worker.join(timeout=1)
            self.assertFalse(worker.is_alive(), "Request worker did not clean up")
            self.assertTrue(errors.empty(), list(errors.queue))
            self.assertFalse(stalled, "Selector readiness caused an unbounded accept")

    def test_stuck_callback_cannot_override_gui_deadline(self):
        server = SMOKE["report_server"]("/test-token", Queue())
        self.addCleanup(server.server_close)
        supervisor = threading.current_thread()
        release = threading.Event()
        entered = threading.Event()
        workers = []

        def stuck_callback():
            worker = threading.current_thread()
            if worker is supervisor:
                raise RuntimeError("Callback handling ran on the GUI supervisor")
            workers.append(worker)
            entered.set()
            release.wait()

        process = Mock(pid=1234, returncode=None)
        process.poll.return_value = None
        process.wait.return_value = 0
        output = io.StringIO()
        started = monotonic()
        try:
            with (
                patch("sys.argv", ["smoke_gui.py", "fake-uarc"]),
                patch.dict(
                    SMOKE["main"].__globals__,
                    {
                        "report_server": lambda *_: server,
                        "GUI_TIMEOUT_SECONDS": 0.2,
                    },
                ),
                patch.object(server, "handle_request", side_effect=stuck_callback),
                patch("subprocess.Popen", return_value=process),
                patch("faulthandler.dump_traceback_later"),
                patch("faulthandler.cancel_dump_traceback_later"),
                redirect_stdout(output),
                redirect_stderr(output),
                self.assertRaisesRegex(RuntimeError, "No final JavaScript report"),
            ):
                SMOKE["main"]()
            self.assertLess(monotonic() - started, 2)
            self.assertTrue(entered.is_set())
            process.terminate.assert_called_once()
            process.wait.assert_called_once_with(timeout=10)
            self.assertTrue(all(worker.daemon for worker in workers))
        finally:
            release.set()
            for worker in workers:
                worker.join(timeout=1)
        self.assertFalse(any(worker.is_alive() for worker in workers))


if __name__ == "__main__":
    unittest.main()
