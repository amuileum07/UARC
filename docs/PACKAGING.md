# Backend and desktop packaging

Run commands from `backend/`. Runtime dependencies remain managed by `uv.lock`;
PyInstaller is a separate build tool, not an application dependency.
Use Python 3.13 for the pinned PyInstaller 6.14.2 build tool (`>=3.8, <3.14`).

## Python distribution

```bash
uv build --out-dir ../dist/python
```

The wheel installs `app/`, including importers and headless commands. It provides
`uarc` for the desktop host and `uarc-data` for files/history. Frontend assets and
the source-tree build scripts are not part of the wheel. Supply an existing
frontend with `uarc --frontend /path/to/dist/index.html` when using the desktop
host from an installed wheel.

## Standalone backend bundle

```bash
uv run python scripts/build_desktop.py --headless --check
uv run --with 'pyinstaller==6.14.2' python scripts/build_desktop.py --headless
../dist/desktop/UARC/UARC --simulate ../examples/design.json --design --preview
../dist/desktop/UARC/UARC --simulate ../examples/design.json --design --data-dir ../data
../dist/desktop/UARC/UARC --data --data-dir ../data list-runs
uv run python scripts/smoke_bundle.py ../dist/desktop/UARC/UARC
```

Distribute the whole `UARC/` folder, not just its launcher. The backend-only build
excludes pywebview and Qt; use its `--simulate` and `--data` modes. Runtime data
defaults to the user's writable data directory, never the bundle's asset tree.

The launcher calls `freeze_support()` before heavy imports or argument routing,
so frozen workers/resource trackers enter their multiprocessing handlers instead
of opening another window or recursively spawning the application. Workers retain
the same limits, cancellation, crash recovery, and atomic result publication.
The smoke script runs outside the checkout working directory with temporary
application data. It checks actual worker flights, preview, history, independent
designs, OpenRocket conversion, CSV export, and on Linux Ctrl+C cancellation and
worker reaping. It also clears `PYTHONPATH` so source imports cannot hide missing
bundle modules. See [the recorded verification](./VALIDATION.md).

## Desktop bundle after the frontend is built

Build the frontend from the repository root first:

```bash
cd frontend
corepack pnpm install --frozen-lockfile
corepack pnpm build
cd ../backend
```

Then run the existing Python packaging command. pnpm builds the web assets;
uv continues to manage Python dependencies and the packaging tool.

```bash
uv run --with 'pyinstaller==6.14.2' python scripts/build_desktop.py --frontend ../frontend/dist
```

The script requires a real `index.html`, includes the built frontend under
`frontend/dist`, collects RocketPy data and runtime version metadata, and includes
project notices, examples, and documentation. On Linux it selects the existing
PySide6/Qt renderer; on Windows it includes the EdgeChromium backend and the
stdlib Tk/Tcl setup UI. Existing `--output` bundle directories are
preserved; choose a new directory for another build.

The SciPy NumPy-compatibility namespace is collected explicitly because it loads
FFT/linear-algebra modules dynamically. Backend-only builds select Matplotlib's
Agg backend both during analysis and in headless dispatch, avoiding a GUI backend
dependency for numerical execution.

Build on the target OS. A backend bundle passing headless checks does not verify
actual Qt/WebView rendering, native dialogs, or another operating system's runtime.
Full desktop acceptance requires the frontend assets and a graphical session.

## Manual GitHub Actions releases

[Release desktop](../.github/workflows/release.yml) has **only** a
`workflow_dispatch` trigger. Pushes, pull requests, tag creation, schedules and
other workflows do not start it. GitHub's manual-dispatch event can also be
invoked by an authorized CLI/API caller; GitHub does not expose a reliable
web-button-only distinction for this event. No CLI/API automation is configured.

To release from the website:

1. Commit and push the workflow, helper script, release notes and application
   changes to the repository's default branch. The workflow must be present on
   the default branch for GitHub to display its **Run workflow** button.
2. Open **Actions → Release desktop → Run workflow** and select the source
   branch. Enter a version such as **0.1.0** and choose whether to mark it as a
   **pre-release** (enabled by default for the current development build).
3. Click **Run workflow**. Source checks and all four native builds must succeed
   before the publish job runs. It creates the tag/release for the **exact commit
   selected when the run began**, even if the branch subsequently moves.

The version must match both `backend/pyproject.toml` and
`frontend/package.json`; `0.1.0` and `v0.1.0` both produce tag `v0.1.0`.
For later releases, update both manifests, run `uv lock` from `backend/` and
commit the resulting lockfile before dispatching. Existing tags/releases/assets
are not overwritten. Concurrent release runs are serialized.

| Runner | Artifact |
| --- | --- |
| Windows Server 2022 x64 | `UARC-v0.1.0-windows-x86_64.zip` |
| Ubuntu 22.04 x64 | `UARC-v0.1.0-linux-x86_64.tar.gz` |
| macOS 15 Apple Silicon | `UARC-v0.1.0-macos-arm64.tar.gz` |
| macOS 15 Intel | `UARC-v0.1.0-macos-x86_64.tar.gz` |

All archives contain the complete `UARC/` folder and built frontend. Unix tar
archives preserve executable permissions and PyInstaller symlinks. These are
portable executables; the Mac archives are not `.app` or `.dmg` installers.
The recipient extracts the entire archive and opens `UARC.exe` (Windows) or
`UARC` (Linux/Mac). Windows retains its consent-based prerequisite setup.

The workflow uses Python 3.13.5, Node 22.20.0, the manifest-pinned pnpm version,
uv 0.12.21 and PyInstaller 6.14.2. JavaScript/Python dependencies use the committed
lockfiles. GitHub `setup-python` supplies the interpreter, including Windows
Tcl/Tk; uv is configured not to download a different interpreter. The frontend
is checked/built once and shared with the native jobs. Full backend unit/lint
checks run on Linux; Windows additionally exercises the real setup controls with
a mocked installer. Each native executable runs the existing frozen-worker/file
smoke checks before packaging. These checks do not install Microsoft runtimes
or certify interactive webview/3D rendering on end-user desktops.

The publish job requires exactly four nonempty archives and creates
`SHA256SUMS.txt`. It uploads all assets into a draft and publishes only after
upload succeeds. If publication fails after creating the draft, inspect the
failed run and draft/tag manually; there is no automatic deletion or clobbering.
Earlier build failures create no release. Successful files remain downloadable
from **Releases**; intermediate workflow artifacts are retained for seven days.

Only the publish job requests `contents: write`; checkout/build jobs have read
access and do not persist checkout credentials. Actions are pinned to verified
commit SHAs. The built-in `GITHUB_TOKEN` is sufficient; no personal token or
signing secret is required. Repository/organization policy must allow Actions,
the pinned actions and release creation. Builds have no developer signing
certificate or Apple notarization configured. Edit
[RELEASE_NOTES.md](RELEASE_NOTES.md) before each release; it becomes the release
body and records distribution/model limitations.

The workflow has not been dispatched as part of local configuration. Local
script/lint tests do not replace the first native GitHub-hosted build.

## Windows first-run prerequisites

The desktop launcher checks prerequisites **before importing pywebview/pythonnet
or creating simulation jobs**. Windows uses EdgeChromium explicitly. There is no
installation prompt for already-present prerequisites. `--help`, the headless
`--simulate` / `--data` entry points, and spawned simulation workers do not run
the setup wizard. Linux and macOS keep their existing startup paths.

The two prerequisites match the locked pywebview 6.2.1 WinForms implementation:

| Component | Detection | Installation after consent |
| --- | --- | --- |
| .NET Framework 4.6.2+ | HKLM `SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full`, `Release >= 394802`, checking both registry views | Microsoft's .NET Framework **4.8 web installer**, `/q /norestart /ChainingPackage UARC`; requests UAC elevation |
| Evergreen WebView2 Runtime | HKCU and HKLM `SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}`, `pv >= 86.0.622.0`, checking both registry views | Microsoft's architecture-selecting Evergreen bootstrapper, `/silent /install`; normally per-user, or per-machine when already elevated / managed by the Microsoft updater |

An installed Edge browser alone is not treated as the Evergreen Runtime.
Existing compatible .NET versions are retained; 4.8 is installed only if the
minimum prerequisite is missing. Python, pythonnet, numerical libraries and
native libraries collected by PyInstaller belong in the complete bundle; this
wizard does not run pip/uv on the recipient's computer or install GPU drivers.

If either component is missing, a separate setup window lists the missing items
with checked checkboxes and **설치 후 실행 / 취소** buttons. All listed items are
required; unchecking one disables installation. Cancel or closing the window
before installation exits without downloading anything. Installation runs on a
worker thread, with status text and an indeterminate progress bar. Vendor
bootstrappers do not expose a shared percentage-progress interface. While a
vendor installer is running, the setup window cannot be closed: UARC waits for
the install transaction rather than abruptly terminating it.

Only fixed Microsoft HTTPS download links are used. Downloads have a 30-second
socket timeout and a 16 MiB bootstrapper size limit. Before executing a file,
the built-in Windows PowerShell verifies **valid Authenticode** and the
**Microsoft Corporation publisher**. Paths and arguments are passed as data,
not interpolated PowerShell code. UARC does not bypass PowerShell execution
policy or request permanent administrator privileges for the application.
This targets Windows 10/11 with their built-in Windows PowerShell/base .NET
intact; repairing removed or damaged OS components remains a manual operation.
Frozen launches temporarily reset PyInstaller's DLL search directory for the
external system process and remove bundled directories from its PATH.

Each successful installer exit is followed by fresh registry checks. Exit
codes 3010/1641 stop startup and display a restart notice; UARC does not issue
a reboot command. A failed download, invalid signature, cancelled UAC request,
installer failure or unsuccessful recheck keeps the app closed and enables a
retry or cancel. Temporary installer files are removed after the process ends.
On a retry, components already installed are skipped. A restart-required result
offers closing the wizard; launch UARC again after restarting Windows.

For offline installation, use the official
[WebView2 Evergreen Standalone Installer](https://developer.microsoft.com/en-us/microsoft-edge/webview2/)
and [.NET Framework 4.8 Runtime](https://dotnet.microsoft.com/en-us/download/dotnet-framework/net48)
on the target computer, then reopen UARC. If company policy prevents the
PowerShell signature check or installation, an administrator must install the
runtime through the approved deployment method.

Build the Windows distribution **on Windows** using Python 3.13 with Tcl/Tk
enabled. The build checks Tcl initialization; PyInstaller collects Tk/Tcl for
Windows desktop builds only. Headless, Linux and macOS builds still exclude
Tk. Distribute the entire generated `UARC/` directory, including `_internal/`.

Offline automated checks:

```powershell
uv run python -m unittest discover -s tests -p test_windows_runtime.py -v
uv run python -m unittest discover -s tests -p test_desktop.py -v
uv run python -m unittest discover -s tests -p test_files.py -v
```

The tests mock registry/download/process operations; they never install software
or require administrator rights. Windows-only setup-dialog tests additionally
exercise the real Tk controls with a mocked installer. These do not certify an
actual Microsoft install transaction. Before a Windows release, verify a real
bundle in clean Windows 10/11 VMs:

- Existing runtimes: immediate startup, with no download or installation prompt.
- Missing WebView2: checkbox gating, cancel without a download, consent, actual
  installation, automatic continuation and a second launch without the wizard.
- Missing/old .NET: UAC refusal, successful installation and restart handling.
- Offline/proxy failure, invalid signature and failed-install retry: readable
  error, responsive setup window and no main window before a successful recheck.
- A launch path containing spaces/non-ASCII characters; normal 3D map rendering;
  headless commands and spawn workers without additional setup windows.

Implementation checks can run on Linux; the actual Windows installation,
elevation, signature verification and frozen Tk/WebView2 rendering still require
the Windows acceptance checks above.

Sources: [Microsoft WebView2 distribution and registry detection](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution),
[.NET Framework version detection](https://learn.microsoft.com/en-us/dotnet/framework/install/how-to-determine-which-versions-are-installed),
[.NET deployment switches and return codes](https://learn.microsoft.com/en-us/dotnet/framework/deployment/deployment-guide-for-developers),
[PyInstaller external-process DLL search paths](https://pyinstaller.org/en/v6.14.2/common-issues-and-pitfalls.html#launching-external-programs-from-the-frozen-application).

References: [PyInstaller multiprocessing](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html#multi-processing),
[frozen asset paths](https://pyinstaller.org/en/stable/runtime-information.html),
[pywebview freezing](https://pywebview.flowrl.com/guide/freezing).
