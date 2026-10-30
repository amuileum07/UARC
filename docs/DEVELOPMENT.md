# UARC development

User installation instructions are in the [main README](../README.md).
This guide covers source setup, checks, architecture and repository layout.
Dependency versions are maintained in the manifests and lockfiles rather
than duplicated in a README version table.

## Source setup

Use Python 3.13, [uv](https://docs.astral.sh/uv/getting-started/installation/),
Node.js 22.20+ and the pnpm version pinned in the root and frontend
`package.json` files. Python dependencies use `backend/uv.lock`; JavaScript
dependencies use `frontend/pnpm-lock.yaml`.

From the repository root, install and build the interface:

```bash
corepack pnpm --dir frontend install --frozen-lockfile
corepack pnpm build
cd backend
uv sync --locked
uv run --locked uarc
```

For live frontend changes, run this from the repository root in one terminal:

```bash
corepack pnpm dev
```

In another terminal:

```bash
cd backend
uv run --locked uarc --dev-url http://localhost:5173
```

The Vite server provides the web assets; the pywebview desktop provides the
Python bridge. Opening the web page in a normal browser does not provide that
bridge. The root package forwards frontend commands and prevents Corepack from
inheriting another package manager from a parent directory. See the
[frontend guide](../frontend/README.md) for dependency changes and editor controls.

## Checks

From the repository root:

```bash
corepack pnpm check
corepack pnpm --dir frontend test
corepack pnpm --dir frontend format:check
corepack pnpm build
```

From `backend/`:

```bash
uv run --locked ruff check app scripts tests
uv run --locked ruff format --check app scripts tests
uv run --locked python -m unittest discover -s tests -v
```

Run backend tests from `backend/`; some fixtures use paths relative to it.
Ruff handles Python linting/formatting. Biome lints frontend code, Prettier formats
it and TypeScript checks types. Native GUI, graphics and installer acceptance
still require the target OS. See [validation](VALIDATION.md) and
[packaging checks](PACKAGING.md) for what automated tests establish.

Use [the CI and release guide](CI_RELEASE_GUIDE.md) to choose regression and
native checks for a feature change, record evidence, and distinguish the current
workflows from planned release gates.

## Architecture

The React/Dockview workspace calls the desktop host through
`window.pywebview.api` and `frontend/src/lib/bridge.ts`. The local application
uses pywebview's asset server and JavaScript–Python bridge; it has no separate
FastAPI/Uvicorn service.

Pydantic models in `backend/app/schemas/` define serializable inputs and results.
The design compiler derives mass properties and RocketPy inputs. The GUI host
submits jobs to a bounded scheduler; each flight runs in a disposable `spawn`
process. Only the host writes SQLite, and workers publish result files before
marking a run complete. The initial limits are one worker and eight pending jobs;
configuration and limits are described in the [backend guide](../backend/README.md).
Rendering, bridge data flow and GUI acceptance criteria are documented in
[GUI.md](GUI.md).

React, TypeScript and Vite provide the interface, Dockview the panel layout,
SVG/Three.js the rocket views and Cesium the launch-site/trajectory map. Python
uses pywebview, RocketPy, NumPy/SciPy, Pydantic and Rasterio/GDAL. SQLite, JSON
and NumPy arrays store metadata, snapshots and telemetry. Current declared and
resolved versions are in [frontend/package.json](../frontend/package.json),
[backend/pyproject.toml](../backend/pyproject.toml) and their adjacent lockfiles.

## Repository layout

| Path                                                | Responsibility                                                      |
| --------------------------------------------------- | ------------------------------------------------------------------- |
| `frontend/src/features/`                            | Rocket, environment, simulation and results panels                  |
| `frontend/src/components/`, `frontend/src/lib/`     | Shared controls, geometry, bridge transport and types               |
| `backend/app/schemas/`                              | Domain input/result models and validation                           |
| `backend/app/design.py`, `backend/app/materials.py` | Component compilation and material catalogue                        |
| `backend/app/simulation/`                           | RocketPy assembly, jobs, workers and headless commands              |
| `backend/app/terrain*.py`, `backend/app/weather.py` | Site data, elevation references and weather snapshots               |
| `backend/app/bridge.py`, `backend/app/main.py`      | Desktop API and GUI lifecycle                                       |
| `backend/app/storage.py`, `backend/app/cli.py`      | Persistent designs/runs, authorized assets and file commands        |
| `backend/scripts/`, `backend/tests/`                | Build/check tools and offline regression tests                      |
| `examples/`, `docs/`, `Licenses/`                   | Synthetic examples, technical documentation and third-party notices |

Generated `frontend/dist/` assets are included in release distributions. Editable
development installs find assets in the checkout; installed Python packages use
bundled assets and frozen executables use their internal asset directory.

Runtime data defaults to the platform's writable user data directory, outside
the checkout. `--data-dir ../data` explicitly selects the ignored local example
layout: `uarc.sqlite3`, `inputs/`, immutable `designs/<id>/` snapshots and
`runs/<id>/` result directories. A run retains inputs, mass/design reports,
summary, telemetry, runtime versions, progress and completion/error records.
Storage authorization and resource limits are detailed in the backend guide.

## Releases

Only manual GitHub Actions runs publish releases. A run selects a new version,
builds/tests that version on each target, then commits the version files and
tags that commit after all builds pass. The PyPI README badge follows published
metadata automatically. Maintainer inputs, branch-movement handling and PyPI
Trusted Publishing setup are documented in [PACKAGING.md](PACKAGING.md#manual-github-actions-releases).

Release UARC enables `desktop_acceptance` by default: the final archives must
pass the full UI/3D/normal-relaunch scenario before publication. Disabling it is
recorded in the release notes. The separate Desktop acceptance workflow remains
available for verification without changing versions or publishing a release.
