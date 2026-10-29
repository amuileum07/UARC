"""Runtime selection checks without loading graphics libraries into the test host."""

import ctypes
import os
import tempfile
import unittest
from http.client import HTTPConnection
from pathlib import Path
from queue import Queue
from unittest.mock import patch

from app.desktop_runtime import (
    _glibcxx_version,
    open_external_url,
    prepare_desktop_runtime,
)


class DesktopRuntimeTests(unittest.TestCase):
    def test_mac_webview_serves_utf8_assets_without_reverse_dns_in_both_builds(self):
        from webview import http

        make_server = http.make_server
        servers = Queue()

        def record_server(*args, **kwargs):
            server = make_server(*args, **kwargs)
            servers.put(server)
            return server

        for frozen in (False, True):
            with (
                self.subTest(frozen=frozen),
                tempfile.TemporaryDirectory(prefix="uarc 한글 ") as temporary,
                patch("app.desktop_runtime.sys.platform", "darwin"),
                patch("app.desktop_runtime.sys.frozen", frozen, create=True),
                patch.object(http, "WSGIServer", http.WSGIServer),
                patch.object(http, "make_server", side_effect=record_server),
                patch("socket.getfqdn", side_effect=AssertionError("Slow reverse DNS")),
            ):
                entry = Path(temporary) / "index.html"
                content = "<!doctype html><meta charset=utf-8><p>로컬 웹뷰</p>"
                entry.write_text(content, encoding="utf-8")
                prepare_desktop_runtime()
                _, _, web_server = http.BottleServer.start_server([str(entry)], None)
                server = servers.get(timeout=2)
                try:
                    connection = HTTPConnection(*server.server_address, timeout=2)
                    try:
                        connection.request("GET", "/index.html")
                        response = connection.getresponse()
                        self.assertEqual(response.status, 200)
                        self.assertEqual(response.read().decode("utf-8"), content)
                        self.assertEqual(
                            server.base_environ["SERVER_NAME"], "127.0.0.1"
                        )
                        self.assertEqual(
                            server.base_environ["SERVER_PORT"], str(server.server_port)
                        )
                    finally:
                        connection.close()
                finally:
                    server.shutdown()
                    server.server_close()
                    web_server.thread.join(timeout=2)
                self.assertFalse(web_server.thread.is_alive())

    def test_frozen_browser_restores_original_library_path_without_changing_the_host(
        self,
    ):
        for original in (None, "/system/custom/lib"):
            environment = {"LD_LIBRARY_PATH": "/bundle/_internal"}
            if original is not None:
                environment["LD_LIBRARY_PATH_ORIG"] = original
            with (
                self.subTest(original=original),
                patch("app.desktop_runtime.sys.platform", "linux"),
                patch("app.desktop_runtime.sys.frozen", True, create=True),
                patch.dict(os.environ, environment, clear=True),
                patch("app.desktop_runtime.subprocess.Popen") as launch,
            ):
                launch.return_value.poll.return_value = None
                self.assertTrue(open_external_url("https://example.com"))
                child = launch.call_args.kwargs["env"]
                self.assertEqual(child.get("LD_LIBRARY_PATH"), original)
                self.assertEqual(os.environ["LD_LIBRARY_PATH"], "/bundle/_internal")
                launch.assert_called_once()
        with (
            patch("app.desktop_runtime.sys.platform", "linux"),
            patch("app.desktop_runtime.sys.frozen", True, create=True),
            patch("app.desktop_runtime.subprocess.Popen", side_effect=OSError),
        ):
            self.assertFalse(open_external_url("https://example.com"))

    def test_other_browser_launches_keep_the_native_webbrowser(self):
        for platform, frozen in (("linux", False), ("win32", True), ("darwin", True)):
            with (
                self.subTest(platform=platform, frozen=frozen),
                patch("app.desktop_runtime.sys.platform", platform),
                patch("app.desktop_runtime.sys.frozen", frozen, create=True),
                patch("webbrowser.open", return_value=True) as launch,
            ):
                self.assertTrue(open_external_url("https://example.com"))
                launch.assert_called_once_with("https://example.com")

    def test_symbol_versions_compare_numerically(self):
        with tempfile.TemporaryDirectory() as directory:
            library = Path(directory) / "libstdc++.so.6"
            library.write_bytes(b"GLIBCXX_3.4.9\0 GLIBCXX_3.4.30\0 GLIBCXX_3.4\0")
            self.assertEqual(_glibcxx_version(library), (3, 4, 30))

    def test_system_runtime_is_selected_before_child_processes_start(self):
        with (
            patch("app.desktop_runtime.sys.platform", "linux"),
            patch("app.desktop_runtime.sys.frozen", False, create=True),
            patch("app.desktop_runtime.sys.base_prefix", "/test/conda"),
            patch(
                "app.desktop_runtime.sysconfig.get_config_var", return_value="test-gnu"
            ),
            patch.object(Path, "is_dir", return_value=True),
            patch.object(Path, "is_file", return_value=True),
            patch(
                "app.desktop_runtime._glibcxx_version",
                side_effect=[(3, 4, 30), (3, 4, 29)],
            ),
            patch("app.desktop_runtime.ctypes.CDLL") as load,
            patch.dict(os.environ, {"LD_PRELOAD": "/custom/libtrace.so"}),
        ):
            prepare_desktop_runtime()
            load.assert_called_once_with(
                "/usr/lib/test-gnu/libstdc++.so.6", mode=ctypes.RTLD_GLOBAL
            )
            self.assertEqual(
                os.environ["LD_PRELOAD"],
                "/usr/lib/test-gnu/libstdc++.so.6 /custom/libtrace.so",
            )

    def test_windows_and_frozen_linux_skip_cpp_runtime_changes(self):
        for platform, frozen in (("win32", False), ("linux", True)):
            with (
                self.subTest(platform=platform, frozen=frozen),
                patch("app.desktop_runtime.sys.platform", platform),
                patch("app.desktop_runtime.sys.frozen", frozen, create=True),
                patch("app.desktop_runtime.ctypes.CDLL") as load,
            ):
                prepare_desktop_runtime()
                load.assert_not_called()

    def test_non_conda_and_explicit_preload_are_unchanged(self):
        with (
            patch("app.desktop_runtime.sys.platform", "linux"),
            patch("app.desktop_runtime.sys.frozen", False, create=True),
            patch.object(Path, "is_dir", return_value=False),
            patch("app.desktop_runtime.ctypes.CDLL") as load,
        ):
            prepare_desktop_runtime()
            load.assert_not_called()
        with (
            patch("app.desktop_runtime.sys.platform", "linux"),
            patch("app.desktop_runtime.sys.frozen", False, create=True),
            patch.object(Path, "is_dir", return_value=True),
            patch.object(Path, "is_file", return_value=True),
            patch.dict(os.environ, {"LD_PRELOAD": "/custom/libstdc++.so.6"}),
            patch("app.desktop_runtime.ctypes.CDLL") as load,
        ):
            prepare_desktop_runtime()
            load.assert_not_called()

    def test_never_downgrades_runtime_and_reports_load_failures(self):
        for versions, fail in (
            ([(3, 4, 29), (3, 4, 30)], False),
            ([(3, 4, 30), (3, 4, 29)], True),
        ):
            with (
                self.subTest(versions=versions),
                patch("app.desktop_runtime.sys.platform", "linux"),
                patch("app.desktop_runtime.sys.frozen", False, create=True),
                patch("app.desktop_runtime.sys.base_prefix", "/test/conda"),
                patch.object(Path, "is_dir", return_value=True),
                patch.object(Path, "is_file", return_value=True),
                patch("app.desktop_runtime._glibcxx_version", side_effect=versions),
                patch.dict(os.environ, {}, clear=True),
                patch(
                    "app.desktop_runtime.ctypes.CDLL",
                    side_effect=OSError("load failed"),
                ) as load,
            ):
                if fail:
                    with self.assertRaisesRegex(RuntimeError, "uv-managed"):
                        prepare_desktop_runtime()
                else:
                    prepare_desktop_runtime()
                    load.assert_not_called()
                self.assertNotIn("LD_PRELOAD", os.environ)


if __name__ == "__main__":
    unittest.main()
