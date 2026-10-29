# Backend verification — 2026-10-25

## Cross-platform packaging follow-up (2026-10-29)

The following checks cover the later packaging/runtime changes; the historical
results below describe their own versions and scope.

| Check | Result |
| --- | --- |
| Backend regression suite | 197 tests: 193 passed, four Windows-only Tk UI tests skipped on Linux; 111.918 s |
| Ruff lint/format and `git diff --check` | Passed; 69 Python files formatted |
| Fresh Linux wheel environment | Installed 47 packages, verified GDAL/CRS and compressed NetCDF4 I/O, actual spawned flight/history, and identical offline sdist rebuild |
| Source and installed-wheel GUI | Actual QtWebEngine 6.11.2 / Chromium 140 window, required browser APIs and Python design preview passed from a path containing spaces/Korean characters |
| Rebuilt Linux desktop executable | Full frontend bundle built with PyInstaller 6.14.2; real native GUI/bridge check passed |
| Frozen backend operations | Preview, spawned flights, compressed NetCDF4 weather, history, saved designs, OpenRocket import, CSV export and cancellation/worker reaping passed |
| Windows x64 dependency resolution | The built wheel resolved 46 packages with rasterio/netCDF4 source builds disabled; no Windows executable was run locally |
| Mac arm64/x64 dependency resolution | The built wheel resolved 48 packages for macOS 14 arm64 and macOS 15 x64 with rasterio/netCDF4/PyObjC-core source builds disabled; no Mac executable was run locally |
| HTTPS trust | Empty-system-root fallback, retained system roots, missing-bundle rejection and hostname/chain verification passed offline; `certifi/cacert.pem` is present in the frozen bundle |
| Frozen Linux external browser | Mocked launch checks restore/remove `LD_LIBRARY_PATH` only in the external child; the host environment is preserved |

The existing successful [0.1.0 release run](https://github.com/amuileum07/UARC/actions/runs/40712559165)
completed Windows, Linux and both Mac builds and frozen backend checks at commit
`990aa0003c38672b55a25453968fed25bd5a72bf`. It predates these follow-up changes.
The workflow now additionally tests the real native GUI and bridge in fresh
wheel installations and frozen executables on all four targets. Configuring
those jobs is not evidence that the new Windows/Mac GUI checks have run.

This follow-up uses an offline verification page, not a full editor/GPU
acceptance run. Hardware 3D rendering, real Microsoft prerequisite installation,
Apple quarantine/notarization policy and live weather/terrain service responses
are not established by these checks. Bundles remain unsigned by a Developer ID
and unnotarized; native filesystem links and the documented OS/Python/architecture
requirements still apply. See [PACKAGING.md](PACKAGING.md).

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

## pnpm migration (2026-10-26)

Imported the npm lockfile with pnpm 10.33.4, preserving all 125 unique package
versions. A clean install selected 75 packages for Linux; the project then
installed successfully from the same lockfile and store in offline mode.
TypeScript checking, all 11 frontend tests, formatter checking, the production
build, and Cesium static-asset copying passed with pnpm's dependency layout.
`uv lock --check --offline` also passed; Python configuration and `uv.lock`
were unchanged. The Vite bundle-size warning remains as before the migration.

From `frontend/`, reproduce with `corepack pnpm install --frozen-lockfile`,
`corepack pnpm check`, `corepack pnpm test`, `corepack pnpm format:check`, and
`corepack pnpm build`.

## Biome lint integration (2026-10-26)

Added Biome 2.6.2 as a pinned frontend development dependency without changing
existing dependency versions. Biome lint and TypeScript checks passed for the
configured scope (25 linted files, no errors or warnings). Safe-fix execution,
Prettier checking, all 11 frontend tests, and the production build passed.
Deliberately invalid JS, TS, TSX, CSS, and HTML fixtures each produced the expected
lint diagnostic. Generated DTOs remain excluded from lint and included in `tsc`.

Lint-driven fixes specify action-button types, stabilize effect callbacks and
dependencies, and make SVG part selection keyboard-accessible. A source desktop
check changed body length from 0.6 m to 0.7 m and observed preview mass change
from 1.208 kg to 1.226 kg, selected the nose using Enter on its SVG control,
and opened both the 3D rocket and map canvases successfully. Prettier remains
the sole formatter; Biome formatting and assist actions are disabled.

From the repository root, run `corepack pnpm lint`, `corepack pnpm lint:fix`,
and `corepack pnpm check` (lint plus types).

## GUI launch-site and forecast selection (2026-10-26)

The environment editor now has location/terrain and time/weather tabs, place
search, explicit map picking, and separate edited-site versus run-result views.
GFS and IFS forecasts are fetched/previewed before application and stored as
numeric profiles in the design/run environment. Network calls do not run in
the solver and replay uses the frozen data.

All 94 backend tests passed, including 11 new offline weather tests. They cover
UTC/IANA/DST handling, wind direction/vector interpolation, temperature/pressure
units, geopotential-height conversion, ellipsoid/geoid offsets, pad-height ground
coverage, stale-input rejection, missing/invalid provider data, bounded HTTP and
redirect refusal, saved-design replay, engine use, and out-of-range flights.
All 15 frontend tests passed, including site selection, unchanged-coordinate
preservation, weather application, time conversion, and late-response matching.
Ruff, Biome, TypeScript, Prettier, production build, and Cesium asset copying passed.
The existing large-chunk build warning remains.

Live read-only requests to Open-Meteo returned GFS and ECMWF IFS 0.25° profiles
for a Berlin test coordinate, each with 14 levels from 50 m to approximately
20.65 km. A place search returned Ulsan-area results. These checks establish
provider connectivity and response compatibility at the time of the check,
not guaranteed availability for every location or forecast time.

A hidden source desktop window loaded the production frontend and exercised
place selection, Cesium coordinate picking, time/timezone input, profile preview
and application, stale-date execution blocking, saving, and a real spawned
flight that reached ground contact. The map returned to editable-site mode after
viewing the result. This deterministic GUI check used provider fixtures; live
provider calls were checked separately above. Synthetic pointer capture was
stubbed only in the probe so Cesium's actual camera picking could run without
a physical pointer device. No test hook was added to the application.

Forecast coverage starts at the launch elevation minus pad height and ends at
the available upper-air level. A flight leaving that vertical range fails
instead of publishing extrapolated results; terrain below that ground anchor
therefore needs a different atmosphere input. Near-ground 2 m temperature and
10 m wind are approximations, as labelled in the UI. This work does not validate
landing accuracy or replace a boundary-layer/weather-field model.

Provider references: [forecast API](https://open-meteo.com/en/docs),
[GFS variables](https://open-meteo.com/en/docs/gfs-api),
[IFS variables](https://open-meteo.com/en/docs/ecmwf-api), and
[place search](https://open-meteo.com/en/docs/geocoding-api).

## Wyoming observations and local weather profiles (2026-10-26)

The complete backend suite passed **106 tests**; frontend tests passed **17**.
Ruff, Biome/TypeScript, Prettier, and the production build passed. The existing
large-chunk warning remains. New checks cover Wyoming identity/unit validation,
CSV encoding/delimiters, actual multi-sheet XLSX files, column/unit conversion,
meteorological wind direction, AGL/geopotential/geoid heights, missing/nonfinite
values, duplicate heights, pressure inversions, formula/error cells, file/range
limits, changed-preview hashes, authorized asset paths, and saved-file replay.

A live read-only call to the [current Wyoming archive](https://weather.uwyo.edu/upperair/sounding.shtml)
returned station **83779**, **2019-02-05 12:00 UTC**, with **59 levels** spanning
approximately **722.08–21935.22 m** after geopotential-to-geometric conversion.
This verifies compatibility with that actual response; other station/time
combinations can be unavailable. The GUI keeps the launch site/elevation and
shows station distance and observation/launch time difference.

A hidden desktop window using production assets exercised native-dialog-selected
CSV input, column defaults, profile preview/application, original-file snapshot
storage, and a real spawned flight reaching ground contact. It then imported a
real XLSX, changed worksheets, previewed/applied its six levels, and verified
that cancelling the picker retained the profile. A Wyoming response fixture
exercised station/time entry, the 59-level preview, distance notes, and the
launch-outside-coverage warning. Only the native picker selection and provider
responses were substituted in this deterministic GUI probe; parsing, bridge,
workspace, persistence, and solver used the production implementations.

CSV/XLSX metadata associates the imported profile with the explicitly selected
launch location/time; it does not establish the file's actual provenance or
meteorological suitability. XLSX values are read without evaluating formulas.
Observation/file profiles keep their actual vertical bounds; launch application
and flight range checks prevent extrapolation. This is still a single vertical
profile, not a spatially/time-varying weather field or landing-accuracy validation.

## Backend settings exposed in GUI (2026-10-26)

The property editor now reads the existing backend configuration schema rather
than discovering only numeric values in the current JSON. Coverage includes
nullable inputs, enums, booleans, strings, vectors, inertia tensors, curves,
material management, component variants, four motor variants/tanks, parachute
deployment, airframe overrides/rail buttons, flight solver/initial state,
manual/direct-provider atmosphere settings, and terrain request radius.
OpenRocket conversion and result query/rerun controls use existing bridge APIs.
No dependency or solver behavior was added for these editors.

Backend tests passed **106** and frontend tests passed **21**. Frontend checks
cover schema references/union/default selection, ordered finite pasted tables,
all motor/component templates, atomic sweep alternatives, prototype-safe editing,
and prior weather/preview/bridge behavior. All **11** new motor/component template
combinations also passed Python validation, compilation, and native RocketPy
assembly. Ruff, Biome, TypeScript, Prettier, production build, and diff whitespace
checks passed; the existing Cesium/Three.js chunk-size warning remains.

Hidden desktop checks with production assets and the real bridge/store exercised:

- Four motor variants, tank creation/deletion/editing, material creation, and new
  elliptical-fin/tail components, including persisted settings.
- Mach/Cd table edits, measured airframe mass, rail-button angle, numeric AGL
  parachute deployment, Cd·A and sampling frequency.
- Six-component inertia, 14-component initial state with unit quaternion and
  launch elevation, scalar/vector tolerances, and explicitly nullable motor input.
- Manual pressure/temperature curves, gravity/height range, direct ensemble
  settings, and clearing incompatible inputs on return to standard atmosphere.
- Real 3DOF/RK45 flight ending at impact, bounded telemetry query, empty query
  interval, and a second real run using the saved input.
- Native-dialog-selected .ork conversion, warnings/preview and explicit apply;
  cancelling a curve-file picker kept the prior curve.

The earlier CSV/XLSX/Wyoming GUI probe also passed after the shared editor change.
Provider-backed direct modes were validated as configuration without issuing
forecast/reanalysis/ensemble network calls. Minimum time step is LSODA-specific;
the GUI labels that limitation. Raw solver assembly-only coordinate frames,
off-axis surface tuples, native Python callbacks, and unfrozen legacy Wyoming
URL forwarding remain outside new component-design creation controls.

## Visible 3D map correction (2026-10-27)

The previous map used an ellipsoid terrain provider with independent opaque
height polygons and a vertical camera. A visible-window check reproduced the
flat-looking patch even with a 600 m synthetic hill. Earlier hidden-window
checks established DOM/bridge behavior, not actual map pixel rendering; a hidden
Qt window could report a canvas element while its drawing buffer was 0×0.

Saved height grids now drive a Cesium `CustomHeightmapTerrainProvider`; OpenStreetMap
imagery follows the mesh. North/south row order, bilinear sampling, geoid offset,
negative elevations, and shared tile edges are covered by runnable tests against
the real Cesium heightmap API. Missing elevation cells reject the display surface
with a visible message instead of creating fabricated terrain. Outside dataset
bounds the display uses an explicitly labelled reference ellipsoid. Flight contact
and its height reference remain implemented in the existing Python adapter.

The 3D camera is oblique, fits after the panel has a usable viewport, and has
site/trajectory reset controls. Map errors remain visible. Static terrain/path
entities are separated from the time-dependent marker. Design edits clone only
their changed path so unrelated edits retain the same terrain reference.

Frontend tests passed **26**, with Biome/TypeScript, Prettier and production build
checks. Visible Qt screenshots were inspected before/after the fix, with a
synthetic hill and with a live 9×9 SRTM90m response at 35.55° N, 129.3° E (4–96 m,
no missing values). Real OpenStreetMap tiles rendered over the surface. Checks
included 2D/3D transitions, resizing from 1500×1000 to 1200×850, and reopening
the map tab. Rendered screenshots were allowed to complete; canvas dimensions
alone do not establish that a restored WebGL frame has been painted.

A real spawned flight using the live-grid site finished at impact, and its
trajectory, predicted landing point, and selected-time marker were inspected in
the visible result map. A separate incomplete-grid case displayed its error and
ellipsoid fallback. No numerical flight/contact equations were changed.

This changes display integration, not DEM resolution or landing accuracy.

### Relief visibility and logo check (2026-10-27)

A second visible-window check confirmed SCENE3D, a north-up 65° downward camera,
and loaded globe heights of 4.21, 93.45, and 65.85 m at three positions in the saved
Ulsan grid. Thus the terrain was genuinely elevated, but its unlit uniform gray
surface made the 4–96 m relief across 2 km difficult to distinguish. The display
now derives grayscale hillshade from mesh fragment derivatives, since the custom
heightmap provider does not supply vertex normals. Heights stay at 1× and the
caption reports the elevation range and sample spacing. No-data mode explicitly
explains that online imagery alone does not supply terrain heights.

Visible production-asset checks passed with relief and OSM imagery, 2D/3D switching,
zero Cesium logo images, retained OSM attribution, and unchanged loaded heights.
The no-elevation case retained its notice after imagery was enabled. The logo
change uses `CreditDisplay.cesiumCredit`; the credit container is retained. This
viewer uses local heightmaps and OSM, with no ion terrain, imagery, or geocoder.
Frontend tests (26), Biome/TypeScript, Prettier, and the production build passed.

### Public and offline DEM sources (2026-10-27)

The default is now AWS Open Data Terrain Tiles, with bounded GeoTIFF acquisition,
mosaicking, and reprojection into the same frozen grid used for display and
terrain contact. Target spacing defaults to 30 m; actual spacing is reported when
the 257×257 cap applies. Local self-contained GeoTIFF/ERDAS IMG/ASCII Grid/HGT
imports use Rasterio 1.4.4 and a bounded warped window, with explicit vertical
datum, unit, and optional EPSG override. NoData/outside coverage rejects an import.
EGM96, EGM2008, national orthometric heights, and ellipsoid heights remain distinct.

Deterministic tests cover projected EPSG:5186 rasters, IMG reading, row orientation,
feet conversion, missing CRS/coverage/NoData, an AWS four-tile boundary mosaic,
OpenTopography dataset/reference handling, credential redaction, and fixed portal
URLs. A visible Qt probe acquired real AWS GeoTIFF data at 35.55° N, 129.3° E,
radius 300 m, producing a 21×21 grid at 30 m spacing. After explicit launch-height
adoption, a real spawned flight succeeded with `ground_model=terrain`.

The same GUI probe exercised OpenTopography selection/key entry, COP30/EGM2008
adoption, EPSG:5186 IMG import, native file-dialog cancellation preserving the
previous grid, VWorld portal opening, and error-free visible terrain rendering.
Only the OpenTopography response and native file choice were fixture-controlled;
AWS acquisition, projection, storage, and flight integration were real. Browser
launches were captured rather than opening account pages during the test.
No personal API key was available: authenticated OpenTopography and VWorld tile
responses were not live-verified. VWorld is explicitly a satellite-imagery option;
its undocumented legacy DEM binary endpoint is not used for collision heights.

Keys stay in memory and are excluded from design/run snapshots. HTTP failures
suppress URL-bearing exception contexts. Frontend tests (26), static checks,
formatting, and the production build passed; the backend suite passed 115 tests.

### Automatic AWS acquisition and continuous terrain (2026-10-27)

Valid WGS84 sites without an attached grid now acquire AWS calculation heights
automatically after a 600 ms debounce. The existing request queue coalesces edits
and discards late responses. Saved/alternate grids remain attached; changing site
with another source selected does not issue an AWS calculation request. Choosing
AWS explicitly after an alternate import replaces it only after successful fetch.
Radius/spacing preferences are shared with the manual refresh controls. Failures
remain visible and do not cause retries on unrelated height/weather/body edits.
The bundled numeric example now explicitly declares WGS84 and EGM96.

AWS display terrain now continues outside the saved rectangle using public
Terrarium tiles, avoiding the previous artificial zero-height plateau boundary.
Inside the boundary the frozen calculation grid takes precedence. Outside tiles
are visual context; they do not expand flight-contact coverage. Display requests
have a 15 s timeout, a size bound, a 64-tile decoded-memory cache, and source zoom
cap 14. Fully saved tiles render without a network request; errors retain saved
heights and label the outside ellipsoid fallback. Dense wire grids are hidden by
default and can be toggled. The camera remains north-up, 65° downward, at 1× heights.

A visible production Qt probe at 38.119° N, 128.465° E automatically fetched exactly
one grid, with heights 1082.41–1699.59 m. Loaded globe heights were 1694.75 m at the
site and 1462.07 m just outside the calculation rectangle; screenshots showed the
continuous mountain surface. Checks covered changed-site acquisition with a shared
500 m radius, 2D/3D transitions, alternate-source suppression, a controlled network
failure without retry loops, and successful manual retry. A second probe preserved
an attached local grid without any calculation request, then fetched AWS when
explicitly selected. No account keys or simulated AWS heights were used.

Frontend tests passed 30, including request eligibility, Terrarium decoding,
negative/submeter heights, zoom-cap sampling, frozen-height precedence and offline
covered tiles. Biome/TypeScript, Prettier, production build and the 23 weather tests
which consume the changed numeric example passed. Flight equations were unchanged.

### Shared result plots and 3D trajectory (2026-10-27)

Submitting or selecting a run now reveals plots and the map in separate dock
groups. Existing separated placements are retained; closed panels reopen and a
maximized group exits maximization. Selection, including reselecting the same
run, restores 3D. Flight framing uses a 30 m minimum radius rather than the site's
750 m minimum, keeping short flights visible. Saved absolute flight heights are
not clamped onto the terrain. Both views share the run snapshot and selected time;
pending selections hide an earlier trajectory and late responses are discarded.

A visible production Qt probe ran two real spawned RocketPy flights with different
headings over a previously acquired, frozen SRTM grid at 35.55° N, 129.3° E.
The terrain-mode impact matched the grid at the simulated contact coordinates
within 0.00001 m (numerical consistency, not DEM accuracy). The first flight's
338 saved samples ranged from 4.01 to 62.44 m and occupied about 259 vertical screen
pixels after automatic framing. A screenshot confirmed an elevated monochrome
trajectory beside the plot. Checks covered slider movement, history switching,
same-run reselect, closed-panel restoration, maximized-panel recovery, preserving
the old site/DEM after moving the editor, and a deliberately delayed stale result.
No render errors occurred. The delay was fixture-controlled; the flights, result
storage and map rendering were real.

All 32 frontend tests and nine terrain integration tests passed, together with
Biome/TypeScript checks, Prettier and the production build. Added deterministic
checks cover named/reordered trajectory columns, absolute heights and geoid
offsets, malformed/reversed/out-of-range positions and short-flight camera range.
No flight equations or terrain-contact behavior changed in this update.

### Korean place and address search (2026-10-27)

Explicit place searches now use Photon's OpenStreetMap POI/road index, with
Open-Meteo/GeoNames as a city fallback. The default scope is South Korea; worldwide
search remains selectable. Korean Unicode/whitespace is normalized, UNIST and
유니스트 use the official-name query 울산과학기술원, and UNIST-gil/UNIST-gill use
유니스트길. No campus coordinates are hardcoded. OSM node/way/relation IDs are
namespaced, duplicate objects collapse, and categories/addresses/source are shown.
The existing bounded HTTPS transport is reused. A lock, 1.1 s request interval
and 128-entry in-memory cache limit repeated public-service requests. Missing
foreign timezones are not inferred from coordinates.

Live backend and visible production Qt checks found 울산과학기술원 for UNIST,
유니스트 and the full Korean name, and 유니스트길 for both road-name spellings.
울산 and worldwide Paris searches also returned results. Choosing the university
applied 35.573527° N, 129.1898563° E while preserving the entered launch altitude.
Korean IME Enter was prevented from prematurely submitting. Editing a pending
query and returning to the original text still discarded the stale response.
Only that response delay and the initial offline terrain fixture were controlled;
the place queries, provider results and GUI coordinate application were real.

The full backend suite passed 124 tests, including eight new location tests for
normalization, caching, scope, deduplication, fallback, malformed coordinates,
bridge validation and throttling. All 32 frontend tests, Ruff, Biome/TypeScript,
format checks and production build passed. Public Photon service usage and
attribution are documented in the frontend README.
