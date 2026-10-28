# UNIST-AERO ROCKET SIMULATOR

UARC aims to provide a local desktop rocket simulator for AERO, UNIST's undergraduate rocket club.
The project focuses on ease of use and high-fidelity simulation as development goals.

The target application combines a React interface with a [pywebview desktop window and JavaScript–Python bridge](https://pywebview.flowrl.com/guide/interdomain). The UI calls Python through `window.pywebview.api`, so the local simulation workflow does not require a FastAPI/Uvicorn API service. An HTTP API can be added later if browser access or remote computation becomes a requirement.

The planned GUI uses [Dockview](https://dockview.dev/docs/overview/quickstart/?framework=react) (`dockview-react`) for an IDE-style dockable workspace. Rocket design, launch environment, simulation status/history, and result plots will be React panels with tabs, drag-and-drop docking, and resizing.

The GUI requirements include live, selectable **2D/3D rocket previews** driven by numeric component inputs, and a **launch-site map with terrain, flight paths, and predicted landing positions** driven by the environment coordinates. Terrain elevation will support launch-elevation checks and terrain-aware impact detection. The initial implementation supports embedded elevation grids and terrain events; see frontend/README.md for resolution and version limits. See [docs/GUI.md](./docs/GUI.md) for the workspace, rendering/data flow, height references, accuracy limits, and acceptance criteria. Keep the interface visually minimal and the TypeScript, semantic HTML, and CSS explicit and small; frontend conventions are in [CODING_STYLE.md](./CODING_STYLE.md#6-frontend-conventions).

**Development status:** The RocketPy engine, typed input/result schemas, desktop launcher, bounded process scheduler, cancellation, run history, result storage, and telemetry queries are implemented. Editable designs can be saved independently of simulations; input-file import, CSV export, and bounded single-stage OpenRocket import are available through the backend. Run without a GUI using `uv run python -m app.simulation ../examples/simulation.json` or manage files with `uv run uarc-data --help` from `backend/`. The first React desktop workspace is implemented; see frontend/README.md for its verification limits. Executable build scripts and their platform verification scope are documented in [docs/PACKAGING.md](./docs/PACKAGING.md). See [backend/README.md](./backend/README.md) for setup, resource limits, bridge methods, and examples.

Numeric component designs now support material density, wall/plate thickness,
positions, continuous Haack nose profiles, automatic mass/CG/inertia, and measured
overrides. Edit [examples/design.json](./examples/design.json); see
[docs/DESIGN.md](./docs/DESIGN.md) for the coordinate and mass-model conventions.

## Desktop workspace

Native release builds are configured in
[Release UARC](./.github/workflows/release.yml). From GitHub, choose
**Actions → Release UARC → Run workflow**, enter the matching project version
(currently `0.1.0`) and optionally change the pre-release setting. The workflow
runs only on manual dispatch; pushes, pull requests and tags do not trigger it.
It builds Windows/Linux x64 and both Apple Silicon/Intel Mac archives, checks
the frozen executables and publishes a GitHub Release with checksums after all
targets succeed. Commit/push the workflow to the default branch before using
the button. See [release instructions](./docs/PACKAGING.md#manual-github-actions-releases).

The workflow also builds self-contained Python distributions named
**uarc-simulator**, including the interface and starting designs. After PyPI
Trusted Publisher setup, enable **publish_pypi** in the manual run to publish
them. Users can then use `pip install uarc-simulator`, `pipx install uarc-simulator`,
`uv tool install uarc-simulator`, or `uvx --from uarc-simulator uarc`.
Python 3.13+ is required; the `uarc` / `uarc-data` command names are retained.
The separate PyPI project named `uarc` is unrelated. See
[Python distribution setup](./docs/PACKAGING.md#python-distribution).

The first React/Dockview workspace is implemented: numeric editing, selectable SVG/Three.js previews, a Cesium site map, elevation checks, saved designs, jobs and result charts. See [frontend/README.md](./frontend/README.md) for launch commands and terrain-model limitations. Terrain contact uses a version-bound RocketPy 1.13.0 adapter; Automatic AWS public DEM acquisition, continuous surrounding terrain display, offline GeoTIFF/IMG import, and optional OpenTopography API acquisition feed the same frozen terrain used for rendering and contact. VWorld satellite imagery is optional.

The launch-environment editor includes place-name search, map picking, date/time
and timezone input, NOAA GFS / ECMWF IFS forecasts via Open-Meteo, University of
Wyoming radiosonde observations, and CSV/Excel (.xlsx) profile import. Weather is
previewed before applying and embedded in saved designs/runs for offline replay;
see [usage and height/time limits](./frontend/README.md).

The GUI also exposes the existing motor/tank variants, aerodynamic/recovery
settings, curves and inertia tensors, measured airframe overrides, solver/initial
state controls, material management, OpenRocket import, and bounded result queries.
See the [editor control map](./frontend/README.md) for where each setting lives.

Frontend packages use **pnpm 10.33.4** on Node.js 22.20+, pinned by
`frontend/package.json` and `frontend/pnpm-lock.yaml`. From the **UARC repository
root**, run `corepack pnpm --dir frontend install --frozen-lockfile`, then
`corepack pnpm dev` or `corepack pnpm build`. The root `package.json` routes these
two commands to `frontend/` and prevents Corepack from inheriting an unrelated
parent directory's package-manager setting. Python packages continue to use **uv** and
`backend/uv.lock`; from `backend/`, run `uv sync --locked`, then `uv run uarc`.
See [frontend setup](./frontend/README.md) for package changes and checks.
Frontend code quality uses Biome 2.6.2 for linting, Prettier for formatting, and
TypeScript for type checking. Run `corepack pnpm check` from the repository root
for lint and type checks, or `corepack pnpm lint:fix` for safe lint fixes.

## Directory Structure

The following is the **target structure**, combining implemented engine files with planned desktop features. Keep the frontend and Python application in one repository, and create files and directories only as their features are implemented.

During development, the pywebview window will load the Vite development server. Packaged builds will load the generated frontend assets through [pywebview's built-in static file server](https://pywebview.flowrl.com/guide/architecture.html). Simulation calls use the JavaScript–Python bridge in both cases.

```text
UARC/
├── frontend/                      # React + TypeScript + Vite workspace
│   ├── src/
│   │   ├── main.tsx               # React entry point
│   │   ├── App.tsx                # Dockview workspace and feature composition
│   │   ├── features/              # Feature screens [planned]
│   │   │   ├── rocket/            # Numeric inputs, shared 2D/3D geometry, .ork import UI
│   │   │   ├── environment/       # Launch site, terrain map/checks, atmosphere, wind
│   │   │   ├── simulation/        # Run requests, status, and history
│   │   │   └── results/           # Trajectory and telemetry charts, result views
│   │   ├── components/            # Reusable interface components [planned]
│   │   │   └── ui/                # Shared UI components, including shadcn/ui
│   │   ├── lib/
│   │   │   └── bridge.ts          # JSON calls, pywebview readiness; UI/result types pending
│   │   └── styles.css             # Tailwind and global styles [planned]
│   ├── dist/                      # Generated frontend assets bundled with the desktop app
│   ├── index.html                 # [planned]
│   ├── package.json               # Frontend dependencies, scripts, and pnpm version
│   ├── biome.json                 # Lint rules and scope; Prettier owns formatting
│   ├── pnpm-lock.yaml             # Reproducible JavaScript dependency graph
│   ├── pnpm-workspace.yaml        # Single-package dependency build-script settings
│   ├── tsconfig.json              # [planned]
│   └── vite.config.ts             # [planned]
├── backend/                       # pywebview desktop host + Python simulation processes
│   ├── app/
│   │   ├── __main__.py            # Early freeze support and GUI/headless dispatch
│   │   ├── main.py                # Main-thread GUI startup, window creation, and shutdown
│   │   ├── cli.py                 # Design files, input import, history, and CSV export
│   │   ├── config.py              # App settings, frontend asset paths, and user data location
│   │   ├── bridge.py              # JSON validation, submission, status, cancellation, and results
│   │   ├── schemas/               # Domain-specific Pydantic models; stable app.schemas imports
│   │   ├── design.py              # Component mass properties and design-to-solver conversion
│   │   ├── terrain.py             # Height interpolation, vertical references, site checks
│   │   ├── terrain_sources.py     # AWS/OpenTopography rasters and offline DEM import
│   │   ├── simulation/
│   │   │   ├── jobs.py            # Bounded scheduling, deadlines, and worker lifecycle
│   │   │   ├── worker.py          # Build, solve, and save one run in a spawn process
│   │   │   ├── __main__.py        # Headless JSON simulation command
│   │   │   └── engine.py          # RocketPy model construction and result conversion
│   │   ├── importers/
│   │   │   └── openrocket.py      # Bounded XML/ZIP/gzip .ork-to-design conversion
│   │   └── storage.py             # SQLite and per-run file access
│   ├── tests/                     # Bridge, simulation, file conversion, and storage tests
│   │   └── fixtures/              # Small, reproducible test inputs
│   ├── scripts/
│   │   ├── build_desktop.py       # PyInstaller desktop/backend folder bundles
│   │   ├── smoke_bundle.py        # Execute a bundle's file/solver/cancellation checks
│   │   └── benchmark_backend.py   # Worker throughput, RSS, and host query latency
│   └── pyproject.toml             # Python dependencies and tool configuration
├── examples/                      # Small rocket and environment examples tracked in Git
├── docs/                          # GUI plan, units, bridge contracts, and model documentation
├── data/                          # Example runtime root; opt in with --data-dir
│   ├── uarc.sqlite3               # Run/design metadata and history
│   ├── inputs/                    # Explicitly imported local files
│   ├── designs/
│   │   └── <design-id>/           # Immutable design.json and copied input assets
│   └── runs/
│       └── <run-id>/
│           ├── input.json         # Input snapshot for reproducing the run
│           ├── design.json        # Editable component design, for parametric runs
│           ├── design_report.json # Computed/measured mass properties and outlines
│           ├── summary.json       # Summary results, such as apogee
│           ├── telemetry.npy      # Full state history, readable through a memory map
│           ├── runtime.json       # Python and numerical package versions
│           ├── progress.json      # Worker stage; error.json accompanies failures
│           └── complete.json      # Published only after result files are saved
├── Licenses/                      # Third-party licenses
├── package.json                   # pnpm boundary and frontend dev/build shortcuts
├── .gitignore
├── LICENSE
└── README.md
```

Python package `__init__.py` files and detailed tool-generated configuration files are omitted from the tree. `backend/uv.lock` records the desktop dependencies. The `backend/app/` package is installed directly; the former `backend/src/backend/` template has been removed.

Both development and installed launches default to the platform's writable user data directory, outside this checkout. `--data-dir ../data` selects the example layout above. Runtime inputs, saved designs, and results are ignored by Git. Backend linting/formatting uses Ruff; checks and tests are documented in [CODING_STYLE.md](./CODING_STYLE.md).

Bridge methods submit jobs and return run IDs; the UI can poll status and request bounded result slices. Each simulation runs in a disposable `spawn` process, while the GUI event loop stays on the main thread. The default is one running worker plus eight pending slots. Only the host updates SQLite; workers publish result files atomically. See the pywebview [bridge documentation](https://pywebview.flowrl.com/guide/interdomain) and [threading FAQ](https://pywebview.flowrl.com/guide/faq).

## Tech Stack

The tables describe the target stack. Blank versions indicate planned dependencies whose versions have not been selected.

Python requirements are the published `Requires-Python` constraints for the listed package versions, checked on 2026-10-10. They describe installation constraints, not a guarantee that every newer Python release has been tested. `N/A` marks JavaScript/TypeScript libraries, `Follows interpreter` marks Python standard-library modules, and `TBD` marks Python dependencies whose versions have not been selected. The uv row refers to its PyPI installation requirement; its standalone CLI does not require Python to run.

### Libraries

#### Frontend

| Library / Technology | Version | Python requirement | Purpose |
|:--|:--|:--|:--|
| React | | N/A | Core UI component library |
| TypeScript | | N/A | Static type checking and safety |
| pnpm | 10.33.4 | N/A | Frontend package manager; Node.js 22.20+ for this project |
| Biome | 2.6.2 | N/A | Frontend linting and safe fixes; configured separately from Prettier formatting |
| Vite | | N/A | Frontend build tool and development server |
| Dockview (`dockview-react`) | | N/A | React workspace with tabs, dockable panels, and resizable layouts |
| SVG (browser native) | | N/A | 2D rocket profiles, dimensions, component selection, and CG markers |
| shadcn/ui | | N/A | Accessible and customizable UI components |
| Tailwind CSS | | N/A | Utility-first CSS styling framework |
| React Hook Form | | N/A | Form state management and input handling |
| Zod | | N/A | Schema validation and form data parsing |
| Plotly.js / react-plotly.js | | N/A | Interactive 2D/3D flight trajectory and telemetry plotting |
| pywebview JS API | | Follows pywebview host | Promise-based Python calls and simulation status polling through `bridge.ts` |

#### Desktop & Simulation

| Library / Technology | Version | Python requirement | Purpose |
|:--|:--|:--|:--|
| Python | 3.13.5 | Project minimum: `>=3.13` | Desktop host and simulation execution runtime |
| uv | [0.12.21](https://pypi.org/project/uv/0.12.21/) | `>=3.8` (PyPI install) | Fast Python package and environment manager |
| pywebview | [6.2.1](https://pypi.org/project/pywebview/6.2.1/) | `>=3.8` | Native desktop window, JavaScript–Python bridge, and file dialogs |
| PySide6 | [6.11.2](https://pypi.org/project/PySide6/6.11.2/) | `>=3.10, <3.15` | Qt/WebEngine renderer installed automatically on Linux |
| Pydantic | [2.13.5](https://pypi.org/project/pydantic/2.13.5/) | `>=3.9` | Data validation and settings management |
| RocketPy | [1.13.0](https://pypi.org/project/rocketpy/1.13.0/) | `>=3.10` | 6-DoF trajectory and rocket dynamics simulation |
| NumPy | [2.5.3](https://pypi.org/project/numpy/2.5.3/) | `>=3.12` | Numerical computation and vectorized array data processing |
| Python Multiprocessing | stdlib | Follows interpreter | Dedicated simulation worker processes managed by the desktop host |
| OpenRocket importer | stdlib | Follows interpreter | Convert supported single-stage `.ork` designs without Java; see [support limits](./docs/OPENROCKET.md) |

For the current Linux setup, the project minimum (`>=3.13`) and locked PySide6 requirement (`<3.15`) limit Python to the 3.13 or 3.14 series. The verified UARC environment uses Python 3.13.5; this constraint intersection does not establish runtime compatibility with 3.14.

#### Storage & Data Management

| Technology / Format | Version | Python requirement | Purpose |
|:--|:--|:--|:--|
| JSON | stdlib | Follows interpreter | Simulation configurations and rocket parameter files |
| NumPy File (.npy / .npz) | 2.5.3 | `>=3.12` (NumPy) | High-volume trajectory and simulation telemetry array storage |
| SQLite | stdlib (3.x) | Follows interpreter (`sqlite3`) | Simulation run history, metadata, and session management |

#### Planned Additions

| Library / Technology | Version | Python requirement | Purpose |
|:--|:--|:--|:--|
| Three.js | | N/A | Numeric-design-driven 3D rocket geometry; shares profiles with the 2D preview |
| CesiumJS | 1.134.1 | N/A | 2D/3D terrain from AWS/public or imported DEMs, flight paths, and predicted landing markers |
| TanStack Query | | N/A | Asynchronous bridge result caching and polling, if needed |
| PyInstaller (build tool) | 6.14.2 | `>=3.8, <3.14` | Folder-bundle recipe implemented; build and verify on each target OS |

Desktop distribution also depends on the target platform's [webview runtime](https://pywebview.flowrl.com/guide/web_engine) and [packaging setup](https://pywebview.flowrl.com/guide/freezing). Renderer compatibility and packaged builds must be tested on each supported OS.

See [docs/VALIDATION.md](./docs/VALIDATION.md) for the measured backend workload,
regression checks, bundle verification, and the limits of that evidence.

## Contributors

<a href="https://github.com/amuileum07/UARC/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=amuileum07/UARC" />
</a>

## Licenses

License for this project : [License](./LICENSE)
Third-Party Licenses : [Licenses](./Licenses/)
