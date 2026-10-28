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
Release checks cover frozen numerical workers and file operations; native webview,
3D rendering and real Windows prerequisite installation need desktop validation.
`SHA256SUMS.txt` lists archive checksums.

The `uarc_simulator-*.whl` and `.tar.gz` Python distributions include the interface
and starting designs. They need Python 3.13+ and the platform webview dependencies.
Install the downloaded wheel with pip, or after PyPI publication use
`pipx install uarc-simulator`, `uv tool install uarc-simulator`, or
`uvx --from uarc-simulator uarc`. PyPI publication is an optional manual workflow
step, so GitHub assets may be available before the PyPI project is published.

Aerodynamic coefficients are preliminary engineering estimates; the supported
Mach range is not a claim of complete experimental validation. See the included
`docs/AERODYNAMICS.md`, `docs/PACKAGING.md` and license notices for scope.
