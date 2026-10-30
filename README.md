# UNIST-AERO ROCKET SIMULATOR

[![PyPI version](https://img.shields.io/pypi/v/uarc-simulator)](https://pypi.org/project/uarc-simulator/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](./LICENSE)

UARC is a desktop rocket simulator for AERO, UNIST's undergraduate rocket club.
It combines a dockable design workspace with RocketPy flight calculations,
2D/3D rocket previews, weather profiles and terrain maps.

The version badge follows the latest published **uarc-simulator** release on
PyPI; it updates after publication without editing this README.

## Features

- Edit rocket components, materials, motors, tanks and recovery hardware;
  calculate mass, center of gravity and inertia with measured overrides.
- Preview the same design in SVG 2D and Three.js 3D views.
- Select launch locations by Korean/English place search, map picking or
  coordinates. Apply NOAA GFS / ECMWF IFS forecasts through Open-Meteo,
  University of Wyoming soundings, or CSV/Excel `.xlsx` profiles.
- Display terrain from AWS public DEMs, offline GeoTIFF/IMG files or optional
  OpenTopography requests. Use the frozen terrain for trajectory contact and
  show flight paths and predicted landing positions on the Cesium map.
- Save and reopen `.uarc` design files, import supported single-stage OpenRocket
  designs, inspect run history and plots, and export telemetry as CSV.

## Install and run

### Desktop downloads

Download an archive from [GitHub Releases](https://github.com/amuileum07/UARC/releases).
Choose Windows x64, Linux x64 or macOS Apple Silicon. Extract the
**entire `UARC/` folder**, then open `UARC.exe` on Windows or `UARC` on Linux/macOS.
These downloads include Python and the application dependencies.

### Python package

The package is available on [PyPI](https://pypi.org/project/uarc-simulator/).
Python **3.13.x** is required. Other Python minor versions are not yet supported
by the tested native dependency/build combination.
Published packages include the built interface and example designs, so Node.js
and pnpm are only needed for source development.

For a quick launch with [uv](https://docs.astral.sh/uv/getting-started/installation/):

```bash
uvx --python 3.13 --from uarc-simulator uarc
```

Choose one installation method:

| Tool                                     | Install                                        | Run          | Update                                           |
| ---------------------------------------- | ---------------------------------------------- | ------------ | ------------------------------------------------ |
| uv                                       | `uv tool install --python 3.13 uarc-simulator` | `uarc`       | `uv tool upgrade uarc-simulator`                 |
| pipx                                     | `pipx install --python 3.13 uarc-simulator`    | `uarc`       | `pipx upgrade uarc-simulator`                    |
| pip, in an activated virtual environment | `python -m pip install uarc-simulator`         | `uarc`       | `python -m pip install --upgrade uarc-simulator` |
| uvx, an isolated cached environment      | `uvx --python 3.13 --from uarc-simulator uarc` | Same command | Add `--refresh` to that command                  |

`uvx` is included with uv. For pipx setup, see the
[pipx installation guide](https://pipx.pypa.io/latest/how-to/install-pipx.html).
If an installed command is missing from your shell, use `uv tool update-shell`
or `pipx ensurepath`, then reopen the terminal.

For pip, first create a virtual environment with a Python 3.13 interpreter:

```bash
python3.13 -m venv .venv
```

On Windows, use `py -3.13 -m venv .venv` instead.
Activate it with `source .venv/bin/activate` on Linux/macOS, or
`.\.venv\Scripts\Activate.ps1` in Windows PowerShell, then use the pip commands
above. The distribution name is **uarc-simulator** and the launcher is **uarc**;
the PyPI package named `uarc` belongs to another project.

### Platform requirements

- **Windows:** the desktop checks for .NET Framework and WebView2 107+, and offers
  installation of missing prerequisites after consent. Python-package installs
  need an interpreter with Tcl/Tk for this setup window.
- **Linux:** the Python package installs PySide6/Qt; a graphical session and
  compatible system graphics libraries are still required.
- **macOS Apple Silicon:** the desktop uses the native WebKit webview.
  Python-package installs need macOS 14+ for the pinned rasterio wheels.
  Standalone downloads are built and checked on macOS 15. Intel Macs are not
  currently supported.

See [platform setup and packaging](./docs/PACKAGING.md) and
[Linux/Conda graphics troubleshooting](./backend/README.md#linux--conda-graphics-runtime).

## First steps

1. Open UARC and edit the starting design with your actual component and motor
   specifications. Example values describe synthetic hardware.
2. Open **발사장**, choose the launch position and load terrain. New GUI projects
   set launch elevation to terrain plus the editable pad height.
3. Set the launch time and timezone, preview a weather source and apply it.
4. Run with **F5**, then select the result to inspect charts and the mapped
   trajectory. Save the design with **Ctrl+S**.

Saved designs and runs retain their applied terrain/weather snapshots and input
assets. Fetching online data needs a connection; saved profiles can be replayed
offline. Available controls and data limits are described in the
[workspace guide](./frontend/README.md).

Command-line help and headless simulation are also available:

```bash
uarc --help
uarc --simulate my-rocket.uarc --design
uarc-data --help
```

## Model scope

UARC is under active development. Automatic drag estimates have restricted
geometry and Mach ranges; whole-vehicle accuracy is not established by the
component checks. Terrain resolution, height reference and weather coverage
affect flight and landing predictions. See the
[aerodynamic model](./docs/AERODYNAMICS.md),
[design conventions](./docs/DESIGN.md) and
[recorded validation](./docs/VALIDATION.md) for the supported ranges and evidence.

## Documentation and development

| Topic                                                    | Guide                                     |
| -------------------------------------------------------- | ----------------------------------------- |
| Source setup, checks, architecture and repository layout | [Development](./docs/DEVELOPMENT.md)      |
| Desktop controls, weather, maps and result views         | [Workspace](./frontend/README.md)         |
| Python entry points, bridge API and storage              | [Backend](./backend/README.md)            |
| Component coordinates, mass properties and materials     | [Design](./docs/DESIGN.md)                |
| Drag equations and verification limits                   | [Aerodynamics](./docs/AERODYNAMICS.md)    |
| Supported `.ork` conversion                              | [OpenRocket import](./docs/OPENROCKET.md) |
| Executable/PyPI builds and manual releases               | [Packaging](./docs/PACKAGING.md)          |
| Contribution conventions                                 | [Coding style](./CODING_STYLE.md)         |

Maintainers publish from **Actions → Release UARC → Run workflow**. The default
automatically increments the patch version; minor/major increments and an explicit
version override are available. See the [release procedure](./docs/PACKAGING.md#manual-github-actions-releases).

Report reproducible problems through [GitHub Issues](https://github.com/amuileum07/UARC/issues).
For contributions, start with the development and coding-style guides.

## Contributors

[![UARC contributors](https://contrib.rocks/image?repo=amuileum07/UARC)](https://github.com/amuileum07/UARC/graphs/contributors)

## License

UARC is released under the [MIT License](./LICENSE).
Bundled third-party notices are in [Licenses](./Licenses/).
