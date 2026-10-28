"""Offline Windows setup checks; never download or install on the test host."""

import base64
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from threading import get_ident
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app import windows_runtime as runtime


class WindowsRuntimeTests(unittest.TestCase):
    def test_other_platforms_and_installed_runtimes_do_not_show_setup(self):
        with (
            patch.object(runtime.sys, "platform", "linux"),
            patch.object(runtime, "missing_dependencies") as detect,
            patch.object(runtime, "_show_setup") as dialog,
        ):
            self.assertTrue(runtime.ensure_windows_runtime())
            detect.assert_not_called()
            dialog.assert_not_called()
        with (
            patch.object(runtime.sys, "platform", "win32"),
            patch.object(runtime, "missing_dependencies", return_value=[]),
            patch.object(runtime, "_show_setup") as dialog,
        ):
            self.assertTrue(runtime.ensure_windows_runtime())
            dialog.assert_not_called()

    def test_missing_runtime_requires_dialog_consent_before_installing(self):
        for accepted in (False, True):
            with (
                self.subTest(accepted=accepted),
                patch.object(runtime.sys, "platform", "win32"),
                patch.object(
                    runtime, "missing_dependencies", return_value=[runtime.WEBVIEW]
                ),
                patch.object(runtime, "_show_setup", return_value=accepted) as dialog,
                patch.object(runtime, "_download") as download,
            ):
                self.assertEqual(runtime.ensure_windows_runtime(), accepted)
                dialog.assert_called_once_with([runtime.WEBVIEW])
                download.assert_not_called()

    def test_both_registry_views_are_checked_and_access_denial_is_not_absence(self):
        fake = SimpleNamespace(
            KEY_READ=1,
            KEY_WOW64_32KEY=2,
            KEY_WOW64_64KEY=4,
            HKEY_LOCAL_MACHINE=10,
            OpenKey=MagicMock(),
            QueryValueEx=MagicMock(return_value=(528040, 4)),
        )
        with patch.dict("sys.modules", winreg=fake):
            fake.OpenKey.side_effect = [FileNotFoundError(), MagicMock()]
            self.assertEqual(
                runtime._registry_values("HKEY_LOCAL_MACHINE", "key", "Release"),
                [528040],
            )
            self.assertEqual([c.args[-1] for c in fake.OpenKey.call_args_list], [3, 5])
            fake.OpenKey.side_effect = PermissionError("denied")
            with self.assertRaisesRegex(RuntimeError, "권한"):
                runtime._registry_values("HKEY_LOCAL_MACHINE", "key", "Release")

    def test_detection_handles_per_user_machine_empty_old_and_new_versions(self):
        for release, user, machine, expected in (
            ([528040], ["145.0.1.0"], [], []),
            ([394802], [], ["145.0.1.0"], []),
            ([], [], [], [runtime.DOTNET, runtime.WEBVIEW]),
            (
                [394271],
                ["0.0.0.0", "", "invalid", 123],
                [],
                [runtime.DOTNET, runtime.WEBVIEW],
            ),
            ([528040], ["85.9.999.0"], [], [runtime.WEBVIEW]),
            ([528040], ["86.0.621.999"], [], [runtime.WEBVIEW]),
            ([528040], ["86.0.622.0"], [], []),
            (["528040", True], ["145.0.1.0"], [], [runtime.DOTNET]),
        ):
            with (
                self.subTest(release=release, user=user, machine=machine),
                patch.object(
                    runtime, "_registry_values", side_effect=[release, user, machine]
                ),
            ):
                self.assertEqual(runtime.missing_dependencies(), expected)

    def test_download_is_https_bounded_and_must_be_an_executable(self):
        with tempfile.TemporaryDirectory() as temporary:
            for url, data, limit, error in (
                ("https://download.microsoft.com/setup.exe", b"MZvalid", 100, None),
                ("http://download.microsoft.com/setup.exe", b"MZvalid", 100, "주소"),
                ("https://download.microsoft.com/setup.exe", b"MZtoolarge", 5, "크기"),
                (
                    "https://download.microsoft.com/setup.exe",
                    b"<html>proxy",
                    100,
                    "설치 파일",
                ),
                ("https://download.microsoft.com/setup.exe", b"", 100, "설치 파일"),
            ):
                response = io.BytesIO(data)
                response.geturl = lambda url=url: url
                destination = Path(temporary) / "setup.exe"
                with (
                    self.subTest(url=url, data=data),
                    patch.object(runtime, "urlopen", return_value=response) as request,
                    patch.object(runtime, "MAX_DOWNLOAD_BYTES", limit),
                ):
                    if error:
                        with self.assertRaisesRegex(RuntimeError, error):
                            runtime._download(runtime.WEBVIEW, destination)
                    else:
                        runtime._download(runtime.WEBVIEW, destination)
                        self.assertEqual(destination.read_bytes(), data)
                    request.assert_called_once_with(runtime.WEBVIEW.url, timeout=30)

    def test_powershell_checks_authenticode_before_launch_and_keeps_paths_as_data(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.dict(os.environ, {"SYSTEMROOT": temporary}),
            patch.object(runtime.sys, "frozen", False, create=True),
            patch.object(
                runtime.subprocess, "CREATE_NO_WINDOW", 0x08000000, create=True
            ),
            patch.object(runtime.subprocess, "Popen") as spawn,
        ):
            installer = Path(temporary) / "spaces & ' ; runtime.exe"
            spawn.return_value.wait.return_value = 0
            self.assertEqual(runtime._run_installer(runtime.WEBVIEW, installer), 0)
            command = spawn.call_args.args[0]
            script = base64.b64decode(command[-1]).decode("utf-16le")
            self.assertLess(
                script.index("Get-AuthenticodeSignature"), script.index("Start-Process")
            )
            self.assertIn("$signature.Status -ne 'Valid'", script)
            self.assertIn("O=Microsoft Corporation", script)
            self.assertNotIn(str(installer), script)
            environment = spawn.call_args.kwargs["env"]
            self.assertEqual(environment["UARC_SETUP_PATH"], str(installer))
            self.assertEqual(environment["UARC_SETUP_ADMIN"], "0")
            self.assertEqual(environment["UARC_SETUP_ARGUMENTS"], "/silent /install")
            runtime._run_installer(runtime.DOTNET, installer)
            self.assertEqual(spawn.call_args.kwargs["env"]["UARC_SETUP_ADMIN"], "1")
            self.assertIn(
                "/norestart", spawn.call_args.kwargs["env"]["UARC_SETUP_ARGUMENTS"]
            )

    def test_frozen_launch_resets_dll_search_path_and_restores_it_after_spawn(self):
        with tempfile.TemporaryDirectory() as temporary:
            bundled = Path(temporary) / "bundle"
            system_path = Path(temporary) / "system-tools"
            kernel = MagicMock()
            kernel.SetDllDirectoryW.return_value = 1
            for fails in (False, True):
                with (
                    self.subTest(fails=fails),
                    patch.dict(
                        os.environ,
                        {
                            "SYSTEMROOT": temporary,
                            "PATH": os.pathsep.join(
                                [str(bundled), str(bundled / "dlls"), str(system_path)]
                            ),
                        },
                    ),
                    patch.object(runtime.sys, "frozen", True, create=True),
                    patch.object(runtime.sys, "_MEIPASS", str(bundled), create=True),
                    patch.object(
                        runtime.ctypes, "WinDLL", return_value=kernel, create=True
                    ),
                    patch.object(
                        runtime.subprocess, "CREATE_NO_WINDOW", 0, create=True
                    ),
                    patch.object(
                        runtime.subprocess,
                        "Popen",
                        side_effect=OSError("failed") if fails else None,
                    ) as spawn,
                ):
                    if fails:
                        with self.assertRaises(OSError):
                            runtime._run_installer(
                                runtime.WEBVIEW, Path(temporary) / "setup.exe"
                            )
                    else:
                        spawn.return_value.wait.return_value = 0
                        runtime._run_installer(
                            runtime.WEBVIEW, Path(temporary) / "setup.exe"
                        )
                        self.assertEqual(
                            spawn.call_args.kwargs["env"]["PATH"], str(system_path)
                        )
                    self.assertEqual(
                        kernel.SetDllDirectoryW.call_args_list[-2].args, (None,)
                    )
                    self.assertEqual(
                        kernel.SetDllDirectoryW.call_args_list[-1].args, (str(bundled),)
                    )

    def test_install_rechecks_presence_and_cleans_temporary_files(self):
        downloaded = []

        def fake_download(dependency, path):
            path.write_bytes(b"MZtest")
            downloaded.append(path)

        with (
            patch.object(
                runtime, "missing_dependencies", side_effect=[[runtime.WEBVIEW], [], []]
            ),
            patch.object(runtime, "_download", side_effect=fake_download),
            patch.object(runtime, "_run_installer", return_value=0) as install,
        ):
            runtime.install_dependencies([runtime.WEBVIEW], lambda _: None)
            install.assert_called_once()
        self.assertEqual(len(downloaded), 1)
        self.assertFalse(downloaded[0].parent.exists())
        with (
            patch.object(runtime, "missing_dependencies", return_value=[]),
            patch.object(runtime, "_download") as download,
        ):
            runtime.install_dependencies([runtime.WEBVIEW], lambda _: None)
            download.assert_not_called()

    def test_install_rejects_signature_failure_nonzero_exit_and_false_success(self):
        for code, message in (
            (9001, "서명"),
            (9002, "권한"),
            (42, "42"),
            (0, "확인하지"),
        ):
            with (
                self.subTest(code=code),
                patch.object(
                    runtime, "missing_dependencies", return_value=[runtime.WEBVIEW]
                ),
                patch.object(runtime, "_download"),
                patch.object(runtime, "_run_installer", return_value=code),
                self.assertRaisesRegex(RuntimeError, message),
            ):
                runtime.install_dependencies([runtime.WEBVIEW], lambda _: None)

    def test_restart_stops_before_launch_or_installing_the_next_runtime(self):
        for code in (3010, 1641):
            with (
                self.subTest(code=code),
                patch.object(
                    runtime,
                    "missing_dependencies",
                    return_value=[runtime.DOTNET, runtime.WEBVIEW],
                ),
                patch.object(runtime, "_download"),
                patch.object(runtime, "_run_installer", return_value=code) as install,
            ):
                with self.assertRaisesRegex(runtime.RestartRequiredError, "다시 시작"):
                    runtime.install_dependencies(
                        [runtime.DOTNET, runtime.WEBVIEW], lambda _: None
                    )
                install.assert_called_once()


@unittest.skipUnless(sys.platform == "win32", "Requires a real Windows Tk desktop")
class WindowsSetupDialogTests(unittest.TestCase):
    def run_dialog(self, interaction, installer):
        import tkinter as tk
        from tkinter import ttk

        root = tk.Tk()
        failures = []
        expired = []

        def buttons():
            panel = root.winfo_children()[0]
            return {
                child.cget("text"): child
                for child in panel.winfo_children()
                if isinstance(child, ttk.Button)
            }

        def checked_interaction():
            try:
                interaction(root, buttons)
            except Exception as error:
                failures.append(error)
                root.destroy()

        def timeout():
            expired.append(True)
            root.destroy()

        root.after(50, checked_interaction)
        root.after(5000, timeout)
        with (
            patch("tkinter.Tk", return_value=root),
            patch.object(
                runtime, "install_dependencies", side_effect=installer
            ) as install,
        ):
            ready = runtime._show_setup([runtime.WEBVIEW])
        self.assertFalse(expired, "Setup UI did not complete")
        if failures:
            raise failures[0]
        return ready, install

    def test_checkbox_and_cancel_do_not_install(self):
        from tkinter import ttk

        def interaction(root, buttons):
            choices = [
                x
                for x in root.winfo_children()[0].winfo_children()
                if isinstance(x, ttk.Checkbutton)
            ]
            self.assertEqual(len(choices), 1)
            choices[0].invoke()
            self.assertTrue(buttons()["설치 후 실행"].instate(["disabled"]))
            buttons()["설치 후 실행"].invoke()
            buttons()["취소"].invoke()

        ready, install = self.run_dialog(interaction, lambda *_: None)
        self.assertFalse(ready)
        install.assert_not_called()

    def test_success_runs_installation_off_the_ui_thread(self):
        threads = []

        def installer(dependencies, progress):
            threads.append(get_ident())
            progress("설치 중")

        ready, install = self.run_dialog(
            lambda root, buttons: buttons()["설치 후 실행"].invoke(), installer
        )
        self.assertTrue(ready)
        install.assert_called_once()
        self.assertNotEqual(threads, [get_ident()])

    def test_failure_enables_retry(self):
        attempts = []
        failures = []

        def installer(*_):
            attempts.append(True)
            if len(attempts) == 1:
                raise RuntimeError("offline")

        def interaction(root, buttons):
            def retry():
                try:
                    self.assertTrue(buttons()["설치 후 실행"].instate(["!disabled"]))
                    self.assertTrue(buttons()["취소"].instate(["!disabled"]))
                    buttons()["설치 후 실행"].invoke()
                except Exception as error:
                    failures.append(error)
                    root.destroy()

            buttons()["설치 후 실행"].invoke()
            root.after(500, retry)

        ready, install = self.run_dialog(interaction, installer)
        self.assertFalse(failures)
        self.assertTrue(ready)
        self.assertEqual(install.call_count, 2)

    def test_restart_notice_closes_without_launching(self):
        def installer(*_):
            raise runtime.RestartRequiredError("다시 시작해 주세요.")

        def interaction(root, buttons):
            buttons()["설치 후 실행"].invoke()
            root.after(500, lambda: buttons()["닫기"].invoke())

        ready, install = self.run_dialog(interaction, installer)
        self.assertFalse(ready)
        install.assert_called_once()


if __name__ == "__main__":
    unittest.main()
