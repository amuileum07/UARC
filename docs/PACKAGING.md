# Backend and desktop packaging

Run commands from `backend/`. Runtime dependencies remain managed by `uv.lock`;
PyInstaller is a separate build tool, not an application dependency.
Use Python 3.13 for the pinned PyInstaller 6.14.2 build tool (`>=3.8, <3.14`).

## Python distribution

The PyPI distribution name is **uarc-simulator**; the unrelated `uarc` project
name is already registered. Executable commands remain **uarc / uarc-data**.
The project is published on [PyPI](https://pypi.org/project/uarc-simulator/).
Use one of these methods with Python 3.13.x. The metadata deliberately excludes
other Python minor versions until their native dependencies and build tool are
verified together; an unrestricted `>=3.13` allowed Python 3.15 to fall back to a
rasterio source build without GDAL on Windows.

| Tool | Install/run |
| --- | --- |
| pip, inside a virtual environment | `python -m pip install uarc-simulator`, then `uarc` |
| pipx | `pipx install --python 3.13 uarc-simulator`, then `uarc` |
| uv, persistent | `uv tool install --python 3.13 uarc-simulator`, then `uarc` |
| uvx, temporary | `uvx --python 3.13 --from uarc-simulator uarc` |

For a one-off pipx run: `pipx run --python 3.13 --spec uarc-simulator uarc`. Do not use
`pip install uarc` or `uvx uarc`: those select the other PyPI project. Python
installations used for the Windows prerequisite setup UI need Tcl/Tk support;
the OS webview/graphics requirements still apply. The frozen executable archives
remain the Python-free distribution path.

The release matrix covers standard GIL-enabled 64-bit CPython 3.13: Windows/Linux
x64 and macOS arm64/x64. PyPy, free-threaded Python, 32-bit Python, Windows ARM64
and Linux ARM64 are outside this verified matrix. Linux executables target
Ubuntu 22.04 or compatible newer desktop systems, not musl/Alpine environments.

Build the frontend first, then build from `backend/`:

```bash
uv run python scripts/build_python.py
uv run python scripts/smoke_python.py ../dist/python
uv run python scripts/smoke_python.py ../dist/python --fresh
uv run python scripts/smoke_python.py ../dist/python --fresh --gui
```

The builder temporarily stages the frontend, examples, documentation and notices
under `app/_assets`, then builds a universal wheel and a source distribution.
It refuses to replace an existing staging directory or distribution, and removes
only its own staged files on success/failure. Choose `--output` for a fresh output
directory when needed. Keep `backend/LICENSE` identical to the root license;
the package metadata includes MIT and the license file. The PyPI description is
`backend/PYPI.md` with absolute documentation links.

The wheel's data files work independently of the source checkout and current
directory. The shared asset resolver preserves frozen paths and source frontend
overrides. Node.js is not required to install the sdist either: it already contains
the built assets. A plain `uv build` from an unstaged checkout is not the release
recipe because it can omit those assets. The smoke script installs the wheel to
a temporary target, asserts import/asset origins, runs a real spawned flight and
history query, and rebuilds the sdist offline to compare wheel contents. It reuses
the checked numerical dependencies by default. With `--fresh`, it creates an
isolated virtual environment, resolves the wheel's dependencies from PyPI, and
checks real GeoTIFF/CRS and compressed NetCDF4 I/O in the same process before the
flight, plus the PyObjC WebKit imports on macOS. It requires rasterio/netCDF4
wheels so system GDAL/HDF5 cannot mask a missing binary distribution. The source
uv configuration also forbids building
those two packages from source. Pure-Python source dependencies remain allowed.
PyPI tools use the dependency declarations, not `uv.lock`; RocketPy is pinned
because the terrain adapter requires 1.13.0.

The GUI uses the same pywebview 6.2.1 / Linux PySide6 6.11.2 versions in the
wheel and frozen builds. These are deliberate application compatibility pins;
upgrade them with the native GUI checks rather than only import/headless tests.
`--fresh --gui` also opens the installed `uarc` launcher, loads a local UTF-8 page
from a path containing spaces/Korean characters, checks secure-context browser
features and requests a design preview through the JavaScript/Python bridge.
It closes only its own test process and submits no flight. A graphical session
is required; Linux CI uses Xvfb with the required XCB/EGL system libraries.

The Linux runner explicitly installs `libxcb-shape0` as well as the cursor/XKB
libraries. Qt's cursor warning is generic and does not identify every missing
XCB library. Before GUI checks, CI runs `ldd` on both the xcb platform plugin
and `QtWebEngineProcess`, then loads the plugin to detect symbol/version errors.
Missing native dependencies stop the job with the actual loader output.

The GUI report server handles browser-preopened sockets concurrently with a
three-second request timeout and bounded callback bodies. `page-loaded` and
`bridge-ready` stages are flushed to the log, and native failure logs are printed
before cleanup. The actual GUI deadline remains 60 seconds; the checks are not
skipped and the outer deadline is not extended. Installed-asset assertions compare
canonical paths on both sides, including Windows short TEMP paths such as
`RUNNER~1`; files must still exist inside the installed package environment.

On macOS, the GUI harness launches the same installed/frozen executable through
CPython 3.13's `posix_spawn` path: an absolute launcher, no subprocess `cwd`, and
`close_fds=False`. It changes its own working directory temporarily before
servicing requests, then restores it. Listener/log descriptors must be
non-inheritable; only standard output/error are redirected. The report loop
starts handling connections after launch instead of starting a server thread
before `Popen`. This avoids the previous macOS fork path without changing the
application's launcher or browser checks. A PID is printed when creation returns;
if creation itself stalls, a 20-second diagnostic dumps the harness stack. The
60-second GUI and 90-second caller deadlines remain unchanged.

HTTPS requests retain system/custom CA roots and explicitly load the bundled
certifi roots. This avoids depending on the Python/OpenSSL certificate paths of
the build machine, particularly the python.org framework paths on macOS.
Certificate-chain and hostname verification remain enabled. Offline tests cover
an empty system trust store and missing bundled roots.

Frozen Linux builds restore the original `LD_LIBRARY_PATH` only for the external
`xdg-open` browser process. The host and simulation/Qt children keep their bundled
libraries; changing the host environment while bridge threads run is avoided.

The pinned rasterio 1.4.4 wheels require macOS 14+ on Apple Silicon and macOS 15+
on Intel. On older macOS versions installers can otherwise attempt a source
build requiring external GDAL. The standalone archives are built and checked on
macOS 15 for both architectures; older versions need separate acceptance testing.

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

`tzdata` is a runtime dependency for IANA timezone lookup when the OS has no
database, including Windows. Every bundle explicitly includes the data package,
its regional modules and license metadata. The source and installed-package
checks cover UTC, Asia/Seoul and DST validation without OS timezone data; the
bundle smoke check also disables OS timezone lookup for its weather flight.

On macOS, netCDF4 and rasterio ship separate HDF5/netCDF dylibs with matching
basenames but different build features. After PyInstaller collection, the builder
restores both packages' original extension modules and private dylibs, retaining
their wheel-relative load paths and distinct library IDs, then ad-hoc signs them.
It requires self-contained wheels and rejects non-system dependencies outside
each package instead of silently mixing Homebrew or other package libraries.
The bundle smoke check also imports a synthetic compressed NetCDF4 weather file
through the data CLI and runs a frozen-worker flight with it, without network access.

Build on the target OS. A backend bundle passing headless checks does not verify
actual Qt/WebView rendering, native dialogs, or another operating system's runtime.
Full desktop acceptance requires the frontend assets and a graphical session.

## Manual GitHub Actions releases

[Release UARC](../.github/workflows/release.yml) has **only** a
`workflow_dispatch` trigger. Pushes, pull requests, tag creation, schedules and
other workflows do not start it. GitHub's manual-dispatch event can also be
invoked by an authorized CLI/API caller; GitHub does not expose a reliable
web-button-only distinction for this event. No CLI/API automation is configured.

To release from the website:

1. Commit and push the workflow, helper script, release notes and application
   changes to the repository's default branch. The workflow must be present on
   the default branch for GitHub to display its **Run workflow** button.
2. Open **Actions → Release UARC → Run workflow** and select the source branch.
   Leave **version** empty and choose **bump**: `patch` (default), `minor` or
   `major`. An explicit new X.Y.Z in **version** overrides **bump**. Choose whether
   to mark the GitHub release as a **pre-release** (enabled by default).
   Enable **publish_pypi** only after registering the Trusted Publisher below.
3. Click **Run workflow**. The prepare job selects and stages the version, then
   source checks and all four native builds must succeed before publication.
   The publish job commits only the verified version files to the selected branch
   and tags that commit. Application source is the dispatched commit plus those
   version updates.

The automatic base is the greater of the source version and existing numeric
X.Y.Z release tags, compared numerically. For example, `0.1.0` becomes `0.1.1`
with `patch`, `0.2.0` with `minor`, or `1.0.0` with `major`. Explicit versions
cannot be older than the source version or reuse an existing numeric release.
Both `0.2.0` and `v0.2.0` produce tag `v0.2.0`.

`backend/pyproject.toml`, `backend/uv.lock` and `frontend/package.json` are updated
together; uv maintains its own manifest/lock format without requesting dependency
upgrades. The same three files are passed to every build job and the publish
job. There is no need to edit version strings before a normal release. The README
badge queries PyPI, so it follows PyPI publication rather than source commits or
GitHub-only releases; badge caches may take a few minutes to refresh.

The version commit is created only after all builds/checks pass. Its push uses an
explicit lease requiring the branch to remain at the dispatched SHA; a changed
or deleted branch stops publication without replacing intervening work. Start a
new run from the updated branch in that case. Branch rules must allow this bot
commit; the workflow does not bypass protections. Existing tags/releases/assets
are not overwritten, and concurrent release runs are serialized.

| Runner | Artifact |
| --- | --- |
| Windows Server 2022 x64 | `UARC-vX.Y.Z-windows-x86_64.zip` |
| Ubuntu 22.04 x64 | `UARC-vX.Y.Z-linux-x86_64.tar.gz` |
| macOS 15 Apple Silicon | `UARC-vX.Y.Z-macos-arm64.tar.gz` |
| macOS 15 Intel | `UARC-vX.Y.Z-macos-x86_64.tar.gz` |

All archives contain the complete `UARC/` folder and built frontend. Unix tar
archives preserve executable permissions and PyInstaller symlinks. These are
portable executables; the Mac archives are not `.app` or `.dmg` installers.
The recipient extracts the entire archive and opens `UARC.exe` (Windows) or
`UARC` (Linux/Mac). Windows retains its consent-based prerequisite setup.
Extract Unix bundles to a filesystem that preserves symlinks (for example ext4
or APFS). The data directory and no-overwrite exports also need hard-link
support; FAT/exFAT volumes are not supported for these operations. Failure leaves
existing destination files intact; move the destination to a native filesystem.

The workflow uses Python 3.13.5, Node 22.20.0, the manifest-pinned pnpm version,
uv 0.12.21 and PyInstaller 6.14.2. JavaScript/Python dependencies use the committed
lockfiles. GitHub `setup-python` supplies the interpreter, including Windows
Tcl/Tk; uv is configured not to download a different interpreter. The frontend
is checked/built once and shared with the native jobs. Full backend unit/lint
checks run on Linux; Windows additionally exercises the real setup controls with
a mocked installer. All four native jobs also install the built Python wheel
and resolve its dependencies in a new virtual environment, independently of the
locked source environment, before building the executable. Each native executable
runs the existing frozen-worker/file smoke checks and a real native-webview/
JavaScript/bridge-preview check before packaging. These checks do not install
Microsoft runtimes or certify 3D rendering on end-user GPUs. They run from fresh
temporary data and frontend paths without modifying the user's designs.

The publish job requires four native archives, the verified wheel and sdist,
and creates `SHA256SUMS.txt`. It uploads all assets into a draft and publishes only after
upload succeeds. If publication fails after the version commit or draft is
created, inspect the failed run and branch/draft/tag manually; there is no
automatic deletion or clobbering.
Earlier build failures create no release. Successful files remain downloadable
from **Releases**; intermediate workflow artifacts are retained for seven days.

Only the publish job requests `contents: write` for the version commit and release;
checkout/build jobs have read access and do not persist checkout credentials.
The publish job configures GitHub CLI as its Git credential helper. Actions are pinned to verified
commit SHAs. The built-in `GITHUB_TOKEN` is sufficient; no personal token or
signing secret is required. Repository/organization policy must allow Actions,
the pinned actions and release creation. Builds have no developer signing
certificate or Apple notarization configured. Edit
[RELEASE_NOTES.md](RELEASE_NOTES.md) before each release; it becomes the release
body and records distribution/model limitations.

Local script/lint tests do not replace the native GitHub-hosted build and target-OS
GUI acceptance checks. Configuring the workflow does not publish a release.

### Optional PyPI publication

The same manual workflow always builds/verifies the wheel and sdist and attaches
them to GitHub Releases. **publish_pypi defaults to false.** When explicitly
enabled, a separate job runs after the GitHub release succeeds. It downloads
the already-verified artifacts and publishes them using PyPI Trusted Publishing
(OIDC), without a persistent API-token secret. It is never triggered by a push,
tag or `release.published` event. Only that job has `id-token: write`.

Before the first PyPI upload, register a
[pending Trusted Publisher](https://pypi.org/manage/account/publishing/) in your
PyPI account (or an existing project's Publishing settings if you own it):

| Setting | Value |
| --- | --- |
| PyPI project | `uarc-simulator` |
| GitHub owner | `amuileum07` |
| Repository | `UARC` |
| Workflow filename | `release.yml` |
| GitHub environment | `pypi` |

Configure the matching GitHub environment if required by repository policy.
The existing [uarc-simulator project](https://pypi.org/project/uarc-simulator/)
uses its project's Publishing settings for future publisher changes. The pending
publisher form is only for a first publication under a new, eligible name.

The GitHub pre-release checkbox labels the GitHub release only. PyPI uses the
package's version: the current `0.1.0` is a normal Python package version even
if GitHub calls it a pre-release. This workflow currently validates X.Y.Z versions;
PEP 440 `rc` versions need a separate version-policy change. A failed PyPI job
does not roll back the already-published GitHub release; inspect the upload result
before retrying. Existing PyPI release files are never overwritten/skipped.

See [PyPI Trusted Publishers](https://docs.pypi.org/trusted-publishers/adding-a-publisher/)
and [creating a project via OIDC](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/).

## Windows first-run prerequisites

The desktop launcher checks prerequisites **before importing pywebview/pythonnet
or creating simulation jobs**. Windows uses EdgeChromium explicitly. There is no
installation prompt for already-present prerequisites. `--help`, the headless
`--simulate` / `--data` entry points, and spawned simulation workers do not run
the setup wizard. Linux and macOS keep their existing startup paths.

The prerequisites cover pywebview 6.2.1 WinForms and UARC's browser feature needs:

| Component | Detection | Installation after consent |
| --- | --- | --- |
| .NET Framework 4.6.2+ | HKLM `SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full`, `Release >= 394802`, checking both registry views | Microsoft's .NET Framework **4.8 web installer**, `/q /norestart /ChainingPackage UARC`; requests UAC elevation |
| Evergreen WebView2 Runtime | HKCU and HKLM `SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}`, major version >= 107, checking both registry views | Microsoft's architecture-selecting Evergreen bootstrapper, `/silent /install`; normally per-user, or per-machine when already elevated / managed by the Microsoft updater |

The minimum follows Vite 7's Edge 107 target and the UI's `structuredClone`,
`Object.hasOwn` and `crypto.randomUUID` use. pywebview's lower renderer minimum
alone does not establish frontend compatibility; an older installed runtime is
offered an upgrade through the same setup flow.

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
