# Backend verification — 2026-10-25

Verified on Linux with Python 3.13.5, RocketPy 1.13.0, NumPy 2.5.3,
Pydantic 2.13.5, Ruff 0.17.2, and PyInstaller 6.14.2. The workload machine
reports an AMD Ryzen 3 7330U and eight logical CPUs.

## Regression and distribution checks

| Check | Result |
| --- | --- |
| `uv run python -m unittest discover -s tests` | 69 tests passed; final full run 57.122 s |
| `uv run ruff check .` | Passed |
| `uv run ruff format --check .` | 28 Python files already formatted |
| `git diff --check` | Passed |
| `uv build` | Source distribution and wheel built |
| Extracted wheel outside the checkout | Imported the wheel's app package and completed a real spawned flight |
| Linux backend-only PyInstaller bundle | Built and executed without source imports |
| Bundle smoke verification | Preview, spawned flights, history, independent designs, OpenRocket import, CSV export, Ctrl+C cancellation, and worker reaping passed |

The tests exercise input/result contracts, analytic mass and inertia, material
and position changes, file snapshots, replay, four motor types, multiple workers,
queue limits, cancellation, deadlines, sampled RSS failure, worker/host death,
supervisor failure, restart recovery, publication failures, preserved output
files, telemetry extrema/events, and hostile/unsupported import inputs.

The independent ballistic reference uses constant gravity, zero drag, no motor,
and vertical motion at the pole so Coriolis acceleration vanishes. Starting at
170 m ASL with 20 m/s upward velocity and g=9.81 m/s², the state history matches
`z(t) = 170 + 20t - 9.81t²/2` and `vz(t) = 20 - 9.81t` to absolute tolerances
of 1e-5 m and 1e-6 m/s. Apogee time, ASL/AGL altitude, unchanged mass, and
time-limit termination are checked separately. UTM coordinates are unnecessary
for this polar dynamics reference.

## Small reproducible workload

From `backend/`:

```bash
uv run python scripts/benchmark_backend.py ../examples/design.json --design --runs 4 --workers 2
```

The recorded run used the synthetic parametric example, two disposable workers,
and temporary data. Startup, design compilation, scheduling, simulation, and
result I/O are included.

| Measurement | Observed |
| --- | ---: |
| Successful simulations | 4 / 4 |
| Elapsed time | 5.739 s |
| Throughput | 0.697 runs/s |
| Status-query P95 | 0.422 ms |
| Status-query maximum | 33.575 ms |
| Status-query samples | 398 |
| Sampled host peak RSS | 163.8 MiB |
| Largest sampled individual worker peak RSS | 162.5 MiB |

These values measure this small example on this machine. They do not establish
large-model capacity, GUI frame rate, an OS-enforced memory limit, or a bound on
unsampled memory spikes. Solver integration histories still occupy worker RAM.
For larger vehicles or longer/finer integrations, repeat the same measurement
with representative inputs and choose worker limits for the available memory.

## Reproduce executable acceptance

```bash
uv run python scripts/smoke_bundle.py ../dist/backend-linux/UARC/UARC
```

The checked bundle is under `dist/backend-linux/UARC/`; distribute that entire
folder. Python distributions are under `dist/python/`. See
[PACKAGING.md](./PACKAGING.md) to rebuild into another output directory.

Frontend rendering, full desktop bundles with actual editor assets, Windows and
macOS executable behavior, real-flight agreement, and complete OpenRocket
numerical equivalence were not established by these checks. Supported import
features and explicit conversion errors are listed in [OPENROCKET.md](./OPENROCKET.md).
Current physical-model assumptions remain in [DESIGN.md](./DESIGN.md).

## Linux Conda graphics regression (2026-10-25)

The local Conda-based Python 3.13.5 environment reproduced a Mesa driver load
failure: Conda's `libstdc++.so.6` lacked `GLIBCXX_3.4.30` required by system
`libLLVM-15.so.1`. With the desktop runtime initialization, both `radeonsi_dri.so`
and `swrast_dri.so` loaded successfully using the system C++ runtime.

An X11 probe created an OpenGL 4.6 context on AMD RENOIR. A separate hidden
pywebview/Qt window loaded the built UARC workspace, completed the Python design
preview, created a WebGL2 context on ANGLE/AMD RENOIR, and opened both the Three.js
rocket canvas and Cesium map canvas before closing normally. This was a source
desktop launch, not a rebuilt executable or a live online-terrain check.
The 10 desktop launcher/runtime tests and Ruff checks passed. No software-only
graphics flags or sandbox-disabling flags were used.
