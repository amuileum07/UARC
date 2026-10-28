"""Consent-based Windows prerequisites, before importing pywebview/pythonnet.

The setup UI uses bundled stdlib Tk, so it needs neither WebView2 nor .NET.
Detection/installation sources and Windows acceptance checks: docs/PACKAGING.md.
"""

import base64
import ctypes
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue
from threading import Thread
from urllib.parse import urlsplit
from urllib.request import urlopen


@dataclass(frozen=True)
class Dependency:
    name: str
    url: str
    arguments: str
    administrator: bool = False


DOTNET = Dependency(
    ".NET Framework 4.6.2 이상 (4.8 설치)",
    "https://go.microsoft.com/fwlink/?LinkId=2085155",
    "/q /norestart /ChainingPackage UARC",
    administrator=True,
)
WEBVIEW = Dependency(
    "Microsoft Edge WebView2 Runtime",
    "https://go.microsoft.com/fwlink/p/?LinkId=2124703",
    "/silent /install",
)
MAX_DOWNLOAD_BYTES = 16 * 1024 * 1024  # Online bootstrappers, not offline runtimes.

# Paths/arguments travel through environment values, never interpolated code.
# Microsoft publisher AND a valid Authenticode chain are required before launch.
_INSTALL_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
try {
    $signature = Get-AuthenticodeSignature -LiteralPath $env:UARC_SETUP_PATH
    if ($signature.Status -ne 'Valid' -or
        $signature.SignerCertificate.Subject -notmatch '(^|,\s*)O=Microsoft Corporation(,|$)') {
        exit 9001
    }
    $options = @{
        FilePath = $env:UARC_SETUP_PATH
        ArgumentList = $env:UARC_SETUP_ARGUMENTS
        Wait = $true
        PassThru = $true
    }
    if ($env:UARC_SETUP_ADMIN -eq '1') { $options.Verb = 'RunAs' }
    $process = Start-Process @options
    exit $process.ExitCode
} catch {
    exit 9002
}
"""


class RestartRequiredError(RuntimeError):
    """Installation completed but UARC must wait for a user-initiated reboot."""


def _registry_values(hive: str, path: str, name: str):
    import winreg

    values = []
    for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
        try:
            with winreg.OpenKey(
                getattr(winreg, hive), path, 0, winreg.KEY_READ | view
            ) as key:
                values.append(winreg.QueryValueEx(key, name)[0])
        except FileNotFoundError:
            continue
        except OSError as error:
            raise RuntimeError(
                "Windows 구성 요소 정보를 읽을 수 없습니다. 접근 권한을 확인해 주세요."
            ) from error
    return values


def missing_dependencies() -> list[Dependency]:
    missing = []
    releases = _registry_values(
        "HKEY_LOCAL_MACHINE",
        r"SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full",
        "Release",
    )
    if not any(type(value) is int and value >= 394802 for value in releases):
        missing.append(DOTNET)
    versions = []
    path = (
        r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    )
    for hive in ("HKEY_CURRENT_USER", "HKEY_LOCAL_MACHINE"):
        for value in _registry_values(hive, path, "pv"):
            if isinstance(value, str) and re.fullmatch(
                r"[0-9]{1,10}(?:\.[0-9]{1,10}){3}", value
            ):
                versions.append(tuple(map(int, value.split("."))))
    # Match the pinned pywebview WinForms backend's minimum, using tuple ordering.
    if not any(version >= (86, 0, 622, 0) for version in versions):
        missing.append(WEBVIEW)
    return missing


def _download(dependency: Dependency, destination: Path) -> None:
    with (
        urlopen(dependency.url, timeout=30) as response,
        destination.open("wb") as stream,
    ):
        if urlsplit(response.geturl()).scheme != "https":
            raise RuntimeError(
                "설치 파일의 다운로드 주소가 안전하지 않아 중단했습니다."
            )
        size = 0
        while chunk := response.read(64 * 1024):
            size += len(chunk)
            if size > MAX_DOWNLOAD_BYTES:
                raise RuntimeError("설치 파일의 크기가 예상 범위를 초과했습니다.")
            stream.write(chunk)
    if destination.read_bytes()[:2] != b"MZ":
        raise RuntimeError("올바른 Windows 설치 파일을 다운로드하지 못했습니다.")


def _run_installer(dependency: Dependency, installer: Path) -> int:
    if not os.environ.get("SYSTEMROOT"):
        raise RuntimeError("Windows 시스템 폴더를 찾지 못했습니다.")
    windows = Path(os.environ["SYSTEMROOT"])
    powershell = windows / "System32/WindowsPowerShell/v1.0/powershell.exe"
    environment = dict(
        os.environ,
        UARC_SETUP_PATH=str(installer),
        UARC_SETUP_ARGUMENTS=dependency.arguments,
        UARC_SETUP_ADMIN="1" if dependency.administrator else "0",
        PSMODULEPATH=str(powershell.parent / "Modules"),
    )
    command = [
        str(powershell),
        "-NoProfile",
        "-NonInteractive",
        "-EncodedCommand",
        base64.b64encode(_INSTALL_SCRIPT.encode("utf-16le")).decode("ascii"),
    ]
    kernel = None
    if getattr(sys, "frozen", False):
        bundled = Path(sys._MEIPASS).resolve()
        environment["PATH"] = os.pathsep.join(
            part
            for part in environment.get("PATH", "").split(os.pathsep)
            if part and not Path(part).resolve().is_relative_to(bundled)
        )
        # External Windows tools must not inherit PyInstaller's DLL directory.
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.SetDllDirectoryW.argtypes = [ctypes.c_wchar_p]
        kernel.SetDllDirectoryW.restype = ctypes.c_int
        if not kernel.SetDllDirectoryW(None):
            raise ctypes.WinError()
    try:
        process = subprocess.Popen(
            command,
            env=environment,
            cwd=windows,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    finally:
        if kernel is not None and not kernel.SetDllDirectoryW(str(sys._MEIPASS)):
            raise ctypes.WinError()
    # The vendor owns its install transaction. Do not kill it on a UI timeout;
    # waiting happens in a worker thread and leaves the setup window responsive.
    return process.wait()


def install_dependencies(dependencies: list[Dependency], progress) -> None:
    with tempfile.TemporaryDirectory(prefix="uarc-setup-") as temporary:
        for index, dependency in enumerate(dependencies):
            if dependency not in missing_dependencies():
                continue  # Another process or an earlier retry may have installed it.
            progress(f"{dependency.name}: Microsoft 설치 파일 다운로드 중…")
            installer = Path(temporary) / f"runtime-{index}.exe"
            _download(dependency, installer)
            progress(f"{dependency.name}: 서명 확인 및 설치 중…")
            code = _run_installer(dependency, installer)
            if code in (3010, 1641):
                raise RestartRequiredError(
                    "설치를 마치려면 Windows를 다시 시작해야 합니다.\n"
                    "작업을 저장하고 재부팅한 뒤 UARC를 다시 실행해 주세요."
                )
            if code == 9001:
                raise RuntimeError(
                    "Microsoft의 유효한 서명을 확인하지 못해 실행을 차단했습니다."
                )
            if code == 9002:
                raise RuntimeError(
                    "설치를 시작하지 못했습니다. 관리자 권한 요청의 취소 여부를 확인해 주세요."
                )
            if code != 0:
                raise RuntimeError(f"{dependency.name} 설치 실패 (오류 코드 {code}).")
            if dependency in missing_dependencies():
                raise RuntimeError(
                    f"{dependency.name} 설치를 확인하지 못했습니다. 다시 시도해 주세요."
                )
    if missing_dependencies():
        raise RuntimeError(
            "필수 구성 요소가 아직 없습니다. 설치 후 다시 실행해 주세요."
        )


def _show_setup(dependencies: list[Dependency]) -> bool:
    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError as error:
        raise RuntimeError(
            "설치 안내 창을 열 수 없습니다. 전체 UARC 배포 폴더를 다시 풀어 주세요."
            if getattr(sys, "frozen", False)
            else "설치 안내 창에 필요한 Tcl/Tk가 없습니다. Tcl/Tk를 포함한 Python 또는 실행 파일 배포판을 사용해 주세요."
        ) from error
    try:
        root = tk.Tk()
    except tk.TclError as error:
        raise RuntimeError("Windows 설치 안내 창을 열 수 없습니다.") from error
    root.title("UARC · 필수 구성 요소 설치")
    root.resizable(False, False)
    style = ttk.Style(root)
    if "vista" in style.theme_names():
        style.theme_use("vista")
    panel = ttk.Frame(root, padding=24)
    panel.grid()
    ttk.Label(panel, text="필수 구성 요소가 없습니다. 설치하여 진행하시겠습니까?").grid(
        row=0, column=0, columnspan=2, sticky="w", pady=(0, 16)
    )
    checked = [tk.BooleanVar(root, value=True) for _ in dependencies]
    choices = []
    for row, (dependency, selected) in enumerate(
        zip(dependencies, checked, strict=True), 1
    ):
        choice = ttk.Checkbutton(panel, text=dependency.name, variable=selected)
        choice.grid(row=row, column=0, columnspan=2, sticky="w", pady=4)
        choices.append(choice)
    row = len(dependencies) + 1
    ttk.Label(
        panel,
        text="위 항목은 UARC 실행에 모두 필요합니다. 인터넷 연결이 필요합니다.\n"
        ".NET 설치 시 관리자 권한을 요청할 수 있으며, 자동으로 재부팅하지 않습니다.",
    ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(12, 8))
    status = tk.StringVar(root, value="설치할 필수 항목을 모두 선택해 주세요.")
    ttk.Label(panel, textvariable=status, wraplength=500).grid(
        row=row + 1, column=0, columnspan=2, sticky="w", pady=8
    )
    # Bootstrappers do not provide granular progress; use an indeterminate bar.
    bar = ttk.Progressbar(panel, mode="indeterminate")
    bar.grid(row=row + 2, column=0, columnspan=2, sticky="ew", pady=8)
    events = Queue()
    busy = ready = False

    def cancel():
        if not busy:
            root.destroy()

    def refresh(*_):
        install.configure(
            state="normal" if not busy and all(x.get() for x in checked) else "disabled"
        )

    def worker():
        try:
            install_dependencies(
                dependencies, lambda message: events.put(("progress", message))
            )
        except RestartRequiredError as error:
            events.put(("restart", str(error)))
        except (OSError, RuntimeError, ValueError) as error:
            events.put(("error", str(error)))
        else:
            events.put(("done", ""))

    def poll():
        nonlocal busy, ready
        try:
            kind, message = events.get_nowait()
        except Empty:
            root.after(100, poll)
            return
        if kind == "progress":
            status.set(message)
            root.after(100, poll)
            return
        busy = False
        bar.stop()
        if kind == "done":
            ready = True
            root.destroy()
            return
        status.set(message)
        close.configure(state="normal")
        if kind == "restart":
            close.configure(text="닫기")
        else:
            for choice in choices:
                choice.configure(state="normal")
            refresh()

    def start():
        nonlocal busy
        if busy or not all(x.get() for x in checked):
            return
        busy = True
        for choice in choices:
            choice.configure(state="disabled")
        install.configure(state="disabled")
        close.configure(state="disabled")
        bar.start(12)
        Thread(target=worker, daemon=False).start()
        root.after(100, poll)

    install = ttk.Button(panel, text="설치 후 실행", command=start)
    install.grid(row=row + 3, column=0, sticky="e", padx=(0, 8), pady=(12, 0))
    close = ttk.Button(panel, text="취소", command=cancel)
    close.grid(row=row + 3, column=1, sticky="e", pady=(12, 0))
    for selected in checked:
        selected.trace_add("write", refresh)
    root.protocol("WM_DELETE_WINDOW", cancel)
    root.bind("<Escape>", lambda _: cancel())
    install.focus_set()
    root.mainloop()
    return ready


def ensure_windows_runtime() -> bool:
    if sys.platform != "win32":
        return True
    try:
        missing = missing_dependencies()
        return not missing or _show_setup(missing)
    except (OSError, RuntimeError) as error:
        user = ctypes.WinDLL("user32", use_last_error=True)
        user.MessageBoxW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_uint,
        ]
        user.MessageBoxW.restype = ctypes.c_int
        user.MessageBoxW(None, str(error), "UARC 실행 준비", 0x10)
        return False
