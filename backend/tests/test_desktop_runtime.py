"""Runtime selection checks without loading graphics libraries into the test host."""

import ctypes
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.desktop_runtime import _glibcxx_version, prepare_desktop_runtime


class DesktopRuntimeTests(unittest.TestCase):
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

    def test_other_platforms_and_frozen_bundles_are_unchanged(self):
        for platform, frozen in (("win32", False), ("darwin", False), ("linux", True)):
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
