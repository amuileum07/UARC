# UNIST-AERO ROCKET SIMULATOR

UARC aims to provide a local desktop rocket simulator for AERO, UNIST's undergraduate rocket club.
The project focuses on ease of use and high-fidelity simulation as development goals.

The target application combines a React interface with a [pywebview desktop window and JavaScript–Python bridge](https://pywebview.flowrl.com/guide/interdomain). The UI calls Python through `window.pywebview.api`, so the local simulation workflow does not require a FastAPI/Uvicorn API service. An HTTP API can be added later if browser access or remote computation becomes a requirement.

**Development status:** The RocketPy engine, serializable simulation inputs, desktop launcher, bounded process scheduler, cancellation, run history, result storage, and telemetry queries are implemented. The backend also runs without a GUI through `uv run python -m app.simulation ../examples/simulation.json` from `backend/`. The React UI, OpenRocket import, and executable packaging remain planned. See [backend/README.md](./backend/README.md) for setup, resource limits, bridge methods, and examples.

Numeric component designs now support material density, wall/plate thickness,
positions, continuous Haack nose profiles, automatic mass/CG/inertia, and measured
overrides. Edit [examples/design.json](./examples/design.json); see
[docs/DESIGN.md](./docs/DESIGN.md) for the coordinate and mass-model conventions.

## Directory Structure

The following is the **target structure**, combining implemented engine files with planned desktop features. Keep the frontend and Python application in one repository, and create files and directories only as their features are implemented.

During development, the pywebview window will load the Vite development server. Packaged builds will load the generated frontend assets through [pywebview's built-in static file server](https://pywebview.flowrl.com/guide/architecture.html). Simulation calls use the JavaScript–Python bridge in both cases.

```text
UARC/
├── frontend/                      # React + TypeScript + Vite
│   ├── src/
│   │   ├── main.tsx               # React entry point
│   │   ├── App.tsx                # Application layout and feature composition
│   │   ├── features/
│   │   │   ├── rocket/            # Rocket and motor inputs, .ork import UI
│   │   │   ├── environment/       # Launch site, atmosphere, and wind settings
│   │   │   ├── simulation/        # Run requests, status, and history
│   │   │   └── results/           # Trajectory and telemetry charts, result views
│   │   ├── components/
│   │   │   └── ui/                # Shared UI components, including shadcn/ui
│   │   ├── lib/
│   │   │   └── bridge.ts          # Typed Python calls, pywebview readiness, and error handling
│   │   └── styles.css             # Tailwind and global styles
│   ├── dist/                      # Generated frontend assets bundled with the desktop app
│   ├── index.html
│   ├── package.json
│   ├── tsconfig.json
│   └── vite.config.ts
├── backend/                       # pywebview desktop host + Python simulation processes
│   ├── app/
│   │   ├── main.py                # Main-thread GUI startup, window creation, and shutdown
│   │   ├── config.py              # App settings, frontend asset paths, and user data location
│   │   ├── bridge.py              # JSON validation, submission, status, cancellation, and results
│   │   ├── schemas.py             # Serializable Pydantic input, result, and configuration models
│   │   ├── design.py              # Component mass properties and design-to-solver conversion
│   │   ├── simulation/
│   │   │   ├── jobs.py            # Bounded scheduling, deadlines, and worker lifecycle
│   │   │   ├── worker.py          # Build, solve, and save one run in a spawn process
│   │   │   ├── __main__.py        # Headless JSON simulation command
│   │   │   └── engine.py          # RocketPy model construction and result conversion
│   │   ├── importers/
│   │   │   └── openrocket.py      # .ork conversion using RocketSerializer
│   │   └── storage.py             # SQLite and per-run file access
│   ├── tests/                     # Bridge, simulation, file conversion, and storage tests
│   │   └── fixtures/              # Small, reproducible test inputs
│   └── pyproject.toml             # Python dependencies and tool configuration
├── examples/                      # Small rocket and environment examples tracked in Git
├── docs/                          # Input units, bridge contracts, and simulation model documentation
├── data/                          # Runtime layout; packaged apps use a writable user data directory
│   ├── uarc.sqlite3               # Run status, history, and result paths
│   └── runs/
│       └── <run-id>/
│           ├── input.json         # Input snapshot for reproducing the run
│           ├── design.json        # Editable component design, for parametric runs
│           ├── design_report.json # Computed/measured mass properties and outlines
│           ├── summary.json       # Summary results, such as apogee
│           ├── telemetry.npy      # Full state history, readable through a memory map
│           ├── runtime.json       # Python and numerical package versions
│           └── complete.json      # Published only after result files are saved
├── Licenses/                      # Third-party licenses
├── .gitignore
├── LICENSE
└── README.md
```

Python package `__init__.py` files and detailed tool-generated configuration files are omitted from the tree. `backend/uv.lock` records the desktop dependencies. The `backend/app/` package is installed directly; the former `backend/src/backend/` template has been removed.

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
| Vite | | N/A | Frontend build tool and development server |
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
| RocketSerializer | | TBD | Open OpenRocket file (.ork) |

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
| Three.js | | N/A | 3D rocket model and trajectory visualization |
| TanStack Query | | N/A | Asynchronous bridge result caching and polling, if needed |
| Dockview | | N/A | IDE-style dockable panel layout for engineering UI |
| Desktop Packager (PyInstaller / py2app) | | TBD | Bundle Python and frontend assets; select and test per target OS |

Desktop distribution also depends on the target platform's [webview runtime](https://pywebview.flowrl.com/guide/web_engine) and [packaging setup](https://pywebview.flowrl.com/guide/freezing). Renderer compatibility and packaged builds must be tested on each supported OS.

## Contributors

<a href="https://github.com/amuileum07/UARC/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=amuileum07/UARC" />
</a>

## Licenses

License for this project : [License](./LICENSE)
Third-Party Licenses : [Licenses](./Licenses/)
