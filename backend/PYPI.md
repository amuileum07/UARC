# UARC simulator

UARC is a desktop rocket simulator for AERO, UNIST's undergraduate rocket club.
It combines a React interface, 2D/3D rocket previews, terrain maps and RocketPy
flight calculations. The Python distribution is **uarc-simulator**; the commands
are **uarc** and **uarc-data**. The unrelated PyPI project named `uarc` is not this
application.

Python **3.13.x** and a graphical desktop are required. Other Python minor
versions are not yet supported by the tested native dependency/build combination.
The published wheel and source distribution include the built interface,
starting designs, material
catalogue and documentation. Node.js and pnpm are not needed to run an installed
distribution.

## Install and run

Choose one installation method:

```bash
# pip, inside a Python 3.13 virtual environment
python -m pip install uarc-simulator
uarc

# pipx, using a Python 3.13 interpreter
pipx install --python 3.13 uarc-simulator
uarc

# uv persistent tool installation
uv tool install --python 3.13 uarc-simulator
uarc

# uvx: temporary isolated environment
uvx --python 3.13 --from uarc-simulator uarc
```

For one-off pipx execution, use `pipx run --python 3.13 --spec uarc-simulator uarc`.
Use `uarc --help` or `uarc-data --help` for available options. The same launcher
supports `uarc --simulate design.uarc --design` and `uarc --data --help` without
opening a window.

OS webview/graphics dependencies still apply. Windows offers missing WebView2
and .NET prerequisites for installation after consent; its setup window needs
Python's Tcl/Tk support. Linux uses PySide6/Qt and the system graphics libraries.
macOS uses the native WebKit webview; the pinned rasterio wheels require macOS
14+ on Apple Silicon or 15+ on Intel. Python-free executable downloads are also
provided through [GitHub Releases](https://github.com/amuileum07/UARC/releases).

PyPI installers resolve dependency declarations rather than `uv.lock`.
RocketPy is pinned to 1.13.0 because the terrain-contact adapter is version-bound.
If installation tries to build rasterio and asks for GDAL, check the Python
version and architecture first; the supported wheels include GDAL.
Aerodynamic coefficients remain preliminary engineering estimates, with
component-specific verification limits.

See [documentation](https://github.com/amuileum07/UARC/tree/main/docs),
[aerodynamic verification](https://github.com/amuileum07/UARC/blob/main/docs/AERODYNAMICS.md),
and [source](https://github.com/amuileum07/UARC). Licensed under MIT; bundled
third-party notices are included with the package assets.
