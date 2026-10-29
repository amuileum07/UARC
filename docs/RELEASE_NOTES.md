Portable desktop builds for Windows, Linux and macOS.

| Download | Architecture | Launch after extracting the entire archive |
| --- | --- | --- |
| `windows-x86_64.zip` | Windows x64 | `UARC/UARC.exe` |
| `linux-x86_64.tar.gz` | Linux x64 | `./UARC/UARC` |
| `macos-arm64.tar.gz` | Mac Apple Silicon | `./UARC/UARC` |
| `macos-x86_64.tar.gz` | Mac Intel | `./UARC/UARC` |

Keep the complete `UARC/` folder together, including `_internal/`. Python, uv,
pnpm and Node.js are not needed on the recipient's computer. Windows first-run
setup offers missing WebView2/.NET prerequisites for installation after consent.
The Linux build targets Ubuntu 22.04 or newer compatible desktop environments.
The Mac builds use macOS 15 runners and are portable executable folders, not
`.app` installers. Other OS versions still need native acceptance testing.

These builds have no developer code-signing certificate or Apple notarization.
Release checks cover frozen workers, file operations, and a native-webview/
JavaScript/bridge-preview check for the installed wheel and frozen executable.
3D rendering on end-user GPUs and real Windows prerequisite installation still
need desktop validation. Windows requires WebView2 107+ for the UI's browser APIs.
HTTPS requests use bundled CA roots alongside system/custom roots, avoiding
build-machine certificate paths on macOS. Certificate verification remains on.
`SHA256SUMS.txt` lists archive checksums.

The `uarc_simulator-*.whl` and `.tar.gz` Python distributions include the interface
and starting designs. They need Python 3.13.x and the platform webview dependencies.
The Python package requires macOS 14+ on Apple Silicon or 15+ on Intel for its
native rasterio wheel. Release checks also install the wheel in a fresh virtual
environment on all four targets and exercise GDAL and compressed NetCDF4 I/O.
Install the downloaded wheel with pip, or after PyPI publication use
`pipx install --python 3.13 uarc-simulator`,
`uv tool install --python 3.13 uarc-simulator`, or
`uvx --python 3.13 --from uarc-simulator uarc`. PyPI publication is an optional
manual workflow step, so GitHub assets may be available before the PyPI project
is published.

Aerodynamic coefficients are preliminary engineering estimates; the supported
Mach range is not a claim of complete experimental validation. See the included
`docs/AERODYNAMICS.md`, `docs/PACKAGING.md` and license notices for scope.
