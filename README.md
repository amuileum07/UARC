# UNIST-AERO ROCKET SIMULATOR

UARC aims to provide a GUI-based rocket simulator for AERO, UNIST's undergraduate rocket club.
The project focuses on ease of use and high-fidelity simulation as development goals.

**Development status:** This project is in early development. Only the backend dependency configuration and initial file skeleton are in place; the GUI and simulation functionality are not yet implemented.

## Directory Structure

The following is the **proposed structure before implementation**. Keep the frontend and backend in one repository, and create files and directories only as their features are implemented.

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
│   │   │   └── api.ts             # Shared Fetch calls and HTTP error handling
│   │   └── styles.css             # Tailwind and global styles
│   ├── index.html
│   ├── package.json
│   ├── tsconfig.json
│   └── vite.config.ts
├── backend/                       # FastAPI + Python simulation processes
│   ├── app/
│   │   ├── main.py                # App creation, configuration loading, and lifecycle
│   │   ├── config.py              # Server settings, including storage paths
│   │   ├── api.py                 # Input validation and run, status, and result APIs
│   │   ├── schemas.py             # Pydantic request, response, and configuration models
│   │   ├── simulation/
│   │   │   ├── jobs.py            # Run IDs, process lifecycle, and state transitions
│   │   │   ├── worker.py          # Simulation entry point in a separate process
│   │   │   └── engine.py          # RocketPy model construction and result conversion
│   │   ├── importers/
│   │   │   └── openrocket.py      # .ork conversion using RocketSerializer
│   │   └── storage.py             # SQLite and per-run file access
│   ├── tests/                     # API, simulation, file conversion, and storage tests
│   │   └── fixtures/              # Small, reproducible test inputs
│   └── pyproject.toml             # Python dependencies and tool configuration
├── examples/                      # Small rocket and environment examples tracked in Git
├── docs/                          # Input units, API usage, and simulation model documentation
├── data/                          # Local data generated at runtime
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

Python package `__init__.py` files and detailed tool-generated configuration files are omitted from the tree. Once package managers are selected, commit their lockfiles to version control.

## Tech Stack

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
| Fetch API | | REST API communication and simulation status polling |

#### Backend & Simulation
| Library / Technology | Version | Purpose |
|:--|:--|:--|
| Python | 3.13.5 | Core backend execution runtime |
| uv | 0.12.21 | Fast Python package and environment manager |
| FastAPI | 0.142.2 | High-performance backend REST API framework |
| Uvicorn | 0.54.0 | ASGI web server |
| Pydantic | 2.13.5 | Data validation and settings management |
| RocketPy | 1.13.0 | 6-DoF trajectory and rocket dynamics simulation |
| NumPy | 2.5.3 | Numerical computation and vectorized array data processing |
| Python Multiprocessing | stdlib | Dedicated worker process for non-blocking simulation computation |
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
| TanStack Query | | Asynchronous server state management and caching |
| Dockview | | IDE-style dockable panel layout for engineering UI |
| Desktop Packager (PyInstaller / Tauri) | | Standalone desktop application packaging |

## Contributors

<a href="https://github.com/amuileum07/UARC/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=amuileum07/UARC" />
</a>

## Licenses

License for this project : [License](./LICENSE)
Third-Party Licenses : [Licenses](./Licenses/)
