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
PySide6/Qt renderer; on Windows it includes the EdgeChromium backend. Platform
webview prerequisites still apply. Existing `--output` bundle directories are
preserved; choose a new directory for another build.

The SciPy NumPy-compatibility namespace is collected explicitly because it loads
FFT/linear-algebra modules dynamically. Backend-only builds select Matplotlib's
Agg backend both during analysis and in headless dispatch, avoiding a GUI backend
dependency for numerical execution.

Build on the target OS. A backend bundle passing headless checks does not verify
actual Qt/WebView rendering, native dialogs, or another operating system's runtime.
Full desktop acceptance requires the frontend assets and a graphical session.

References: [PyInstaller multiprocessing](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html#multi-processing),
[frozen asset paths](https://pyinstaller.org/en/stable/runtime-information.html),
[pywebview freezing](https://pywebview.flowrl.com/guide/freezing).
