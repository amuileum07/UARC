# UNIST-AERO ROCKET SIMULATOR

UARC aims to provide a local desktop rocket simulator for AERO, UNIST's undergraduate rocket club.
The project focuses on ease of use and high-fidelity simulation as development goals.

The target application combines a React interface with a [pywebview desktop window and JavaScript–Python bridge](https://pywebview.flowrl.com/guide/interdomain). The UI calls Python through `window.pywebview.api`, so the local simulation workflow does not require a FastAPI/Uvicorn API service. An HTTP API can be added later if browser access or remote computation becomes a requirement.

**Development status:** The RocketPy engine, Pydantic input models, desktop launcher, and JSON input-validation bridge are implemented and tested. Python dependencies now use pywebview, with PySide6 on Linux; FastAPI/Uvicorn have been removed. The React UI, simulation job management, import, and storage features remain planned, so there is not yet a complete desktop simulation workflow. See [backend/README.md](./backend/README.md) for setup, launcher options, and the working engine example.

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
│   │   ├── bridge.py              # JSON config validation; job and result methods are planned
│   │   ├── schemas.py             # Serializable Pydantic input, result, and configuration models
│   │   ├── simulation/
│   │   │   ├── jobs.py            # Run IDs, worker lifecycle, and thread-safe job state
│   │   │   ├── worker.py          # Simulation entry point in a separate process
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
│           ├── summary.json       # Summary results, such as apogee
│           └── telemetry.npz      # Time series and trajectory arrays
├── Licenses/                      # Third-party licenses
├── .gitignore
├── LICENSE
└── README.md
```

Python package `__init__.py` files and detailed tool-generated configuration files are omitted from the tree. `backend/uv.lock` records the desktop dependencies. The `backend/app/` package is installed directly; the former `backend/src/backend/` template has been removed.

Bridge methods will submit jobs and return run IDs promptly; the UI will poll their status through the bridge. RocketPy computation stays in a separate worker process, while the GUI event loop stays on the main thread. Shared job state must handle concurrent bridge calls. See the pywebview [bridge documentation](https://pywebview.flowrl.com/guide/interdomain) and [threading FAQ](https://pywebview.flowrl.com/guide/faq).

## Tech Stack

The tables describe the target stack. Blank versions indicate planned dependencies whose versions have not been selected.

### Libraries

#### Frontend
| Library / Technology | Version | Purpose |
|:--|:--|:--|
| React | | Core UI component library |
| TypeScript | | Static type checking and safety |
| Vite | | Frontend build tool and development server |
| shadcn/ui | | Accessible and customizable UI components |
| Tailwind CSS | | Utility-first CSS styling framework |
| React Hook Form | | Form state management and input handling |
| Zod | | Schema validation and form data parsing |
| Plotly.js / react-plotly.js | | Interactive 2D/3D flight trajectory and telemetry plotting |
| pywebview JS API | | Promise-based Python calls and simulation status polling through `bridge.ts` |

#### Desktop & Simulation
| Library / Technology | Version | Purpose |
|:--|:--|:--|
| Python | 3.13.5 | Desktop host and simulation execution runtime |
| uv | 0.12.21 | Fast Python package and environment manager |
| pywebview | 6.2.1 | Native desktop window, JavaScript–Python bridge, and file dialogs |
| PySide6 | 6.11.2 | Qt/WebEngine renderer installed automatically on Linux |
| Pydantic | 2.13.5 | Data validation and settings management |
| RocketPy | 1.13.0 | 6-DoF trajectory and rocket dynamics simulation |
| NumPy | 2.5.3 | Numerical computation and vectorized array data processing |
| Python Multiprocessing | stdlib | Dedicated simulation worker processes managed by the desktop host |
| RocketSerializer | | Open OpenRocket file (.ork) |

#### Storage & Data Management
| Technology / Format | Version | Purpose |
|:--|:--|:--|
| JSON | stdlib | Simulation configurations and rocket parameter files |
| NumPy File (.npy / .npz) | 2.5.3 | High-volume trajectory and simulation telemetry array storage |
| SQLite | stdlib (3.x) | Simulation run history, metadata, and session management |

#### Planned Additions
| Library / Technology | Version | Purpose |
|:--|:--|:--|
| Three.js | | 3D rocket model and trajectory visualization |
| TanStack Query | | Asynchronous bridge result caching and polling, if needed |
| Dockview | | IDE-style dockable panel layout for engineering UI |
| Desktop Packager (PyInstaller / py2app) | | Bundle Python and frontend assets; select and test per target OS |

Desktop distribution also depends on the target platform's [webview runtime](https://pywebview.flowrl.com/guide/web_engine) and [packaging setup](https://pywebview.flowrl.com/guide/freezing). Renderer compatibility and packaged builds must be tested on each supported OS.

## Contributors

<a href="https://github.com/amuileum07/UARC/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=amuileum07/UARC" />
</a>

## Licenses

License for this project : [License](./LICENSE)
Third-Party Licenses : [Licenses](./Licenses/)
