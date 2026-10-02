# UNIST-AERO ROCKEET SIMULATOR

This project aimed gui rocket simulator for AERO, undergraduate rocket club of UNIST.
It's For eay of use and high-fidelity simulation.

# Directory Structure

# Built Steck

## Libraries

### Frontend
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

### Backend & Simulation
| Library / Technology | Version | Purpose |
|:--|:--|:--|
| FastAPI | | High-performance backend REST API framework |
| Uvicorn | | ASGI web server |
| Pydantic | | Data validation and settings management |
| RocketPy | | 6-DoF trajectory and rocket dynamics simulation |
| NumPy | | Numerical computation and vectorized array data processing |
| Python Multiprocessing | | Dedicated worker process for non-blocking simulation computation |
| RocketSerializer | | Open OpenRocket file (.ork) |

### Storage & Data Management
| Technology / Format | Version | Purpose |
|:--|:--|:--|
| JSON | | Simulation configurations and rocket parameter files |
| NumPy File (.npy / .npz) | | High-volume trajectory and simulation telemetry array storage |
| SQLite | | Simulation run history, metadata, and session management |

### Planned Additions
| Library / Technology | Version | Purpose |
|:--|:--|:--|
| Three.js | | 3D rocket model and trajectory visualization |
| TanStack Query | | Asynchronous server state management and caching |
| Dockview | | IDE-style dockable panel layout for engineering UI |
| Desktop Packager (PyInstaller / Tauri) | | Standalone desktop application packaging |

# Licenses

License for this project : [License](./LICENSE)
Third-Party Licenses : [Licenses](./Licenses/)
