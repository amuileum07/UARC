# UARC desktop workspace

Requires Node 22.20+, pnpm 10.33.4 (pinned in `package.json`), and the existing
Python environment in `backend/`. JavaScript dependencies use pnpm; Python
dependencies continue to use uv. The commands below use the Corepack bundled
with Node 22, so a global pnpm installation is unnecessary. If `pnpm` is already
on your PATH, it can replace `corepack pnpm` in these commands.

The following commands start from the **UARC repository root**. If your terminal
is currently in `backend/`, first run `cd ..`:

```bash
corepack pnpm --dir frontend install --frozen-lockfile
corepack pnpm dev
```

The root `package.json` forwards `dev`, `build`, `lint`, `lint:fix`, and `check`
to `frontend/` and pins pnpm before Corepack searches parent directories. This avoids inheriting a Yarn
setting from a file such as `~/package.json`. It does not create a pnpm workspace
or move the frontend lockfile. Inside `frontend/`, the original commands still
work directly. Do not run frontend commands from `backend/`.

In another terminal:

```bash
cd backend
uv run uarc --dev-url http://localhost:5173
```

Production assets: run `corepack pnpm build` in the repository root or `frontend/`, then `uv run uarc` in
`backend/`. A normal browser alone cannot call the desktop Python bridge.

Track the root `package.json`, `frontend/package.json`,
`frontend/pnpm-lock.yaml`, and `frontend/pnpm-workspace.yaml` in Git. Keep the
two `packageManager` versions synchronized when updating pnpm. Dependencies,
build output, any local `.pnpm-store/`, and pnpm debug logs are ignored.
Do not generate a second lockfile with npm or Yarn. `pnpm-lock.yaml` was imported
from the previous npm lockfile without upgrading application dependencies.
From the repository root, use `corepack pnpm --dir frontend add <package>` for
runtime dependencies and `corepack pnpm --dir frontend add -D <package>` for
development tools. These update the frontend lockfile; use
`corepack pnpm --dir frontend install --frozen-lockfile` for existing checkouts
and CI. The root package only provides command shortcuts and has no dependencies.

`pnpm-workspace.yaml` holds the single-package install settings; it does not add
a repository-wide JavaScript workspace. The pinned esbuild dependency may run its
binary setup script. The unnecessary protobufjs/fsevents install scripts are
disabled. Revisit these settings when intentionally updating those dependencies.

The workspace includes component/material/motor editing, SVG and Three.js rocket
views, a Cesium site map, saved design snapshots, job status/cancellation, result
charts, CSV export, and synchronized trajectory time selection. Advanced input
and thrust curves can be edited in the validated JSON panel. Save with Ctrl+S;
run with F5. Tabs can be rearranged and the layout can be reset.

Select a component and use **선택 부품 삭제** below the project component list
or at the top of its properties. Both buttons share the same deletion rules.
Selection moves to the next component, or the previous one at the end of the
list. A design must retain at least one body tube or aerodynamic surface; a
disabled button explains this restriction. Deleting a component also clears its
uncommitted field issues, and the updated design can be saved normally.

The property editor uses the backend's existing `get_config_schema("design")`
definitions, including defaults and nullable/union types. It no longer limits
editing to numbers already present in a design. Boolean flags, enums, text,
optional values, vectors/tensors, curves, and nested settings have native form
controls; Python remains responsible for physical validation.

| Location | Editable settings |
| --- | --- |
| Project → **로켓 전체 · 항력 · 실측값** | Design name, manual Mach/Cd inputs or independent Cd0 estimates (Mach ≤ 0.7 / Mach 0–3) with component breakdown, rail buttons, measured airframe mass/CG/inertia overrides |
| Component properties | Material, measured mass, dimensions, intrinsic inertia, all four aerodynamic surface types and nose shapes |
| Parachute → **낙하산 전개** | Apogee/descending AGL trigger, Cd·A override, sampling, lag, noise, canopy radius/height/porosity/Cd |
| **모터 · 추진제** | No motor or generic/solid/liquid/hybrid; thrust, burn interval, reshape, dry mass/inertia, orientation, grains/chamber/nozzle/reference pressure |
| Motor → **탱크** | Add/delete tanks; geometry, caps, position, fluids/densities, phase mass curves, flux interval, discretization |
| **재질** | Search the offline manufacturer library, inspect references, add/customize bulk/areal/linear densities, delete unused materials |
| **비행 설정** | Launch/termination plus solver, equations, DOF, time steps, scalar/13-component tolerances, 14-component initial state, log/event flags |
| **발사장** | Terrain query radius, gravity override, atmosphere height limit, manual vertical curves, forecast/reanalysis/ensemble/Windy file/provider settings and variable mapping |
| Project → **OpenRocket 가져오기** | Native .ork selection, explicit parachute trigger, warnings and conversion preview before replacing the design |
| **비행 결과** | Same-input rerun, query time interval, telemetry columns (including attitude/angular velocity), display point limit |

Curve inputs offer a constant, an authorized native-dialog-selected file, or an
editable numeric two-column table. Table coordinates must strictly increase;
click **표 적용** to commit pasted data. Incomplete numeric fields or unapplied
tables block saving/running. Cancelling a curve-file picker preserves the
previous curve. Incompatible fin sweep definitions are cleared atomically.
Motor variants retain their prior settings while that motor editor stays open.
New components, motors, and tanks contain **example values** that
must be replaced with actual specifications. Used materials cannot be deleted.
The material library contains 86 independently sourced density presets
(43 bulk, 16 surface, 27 line), with manufacturer, industry, USDA and original
research references. The material editor also lists unresolved research items.
Under **재질 → 사용자 재질 추가**, enter a name, density type and positive
finite density. Units are kg/m³, kg/m² or kg/m; changing type clears the draft
value. User materials are stored with the design and included in `.uarc` files.
Simulator material and surface-finish tables are not included.
Body/surface properties accept measured or independently documented roughness,
with its convention preserved. The optional automatic Cd0 mode uses only ks;
positive Ra/legacy heights require manual drag inputs. Missing ks is explicitly
reported as a smooth-surface assumption. Automatic estimates are limited to
Mach ≤ 0.7 for the legacy model, or Mach 0–3 with `compressible_v1` for a conical
nose (length/diameter 3–10) and 3/4 thin double-wedge trapezoidal fins. Positive
tip chord, thickness/chord ≤ 5%, zero cant and midchord sweep within ±10° are
required. Fin mass/rendering remain flat-plate approximations; supply measured
fin mass when beveling matters. Transonic nose pressure scales a fineness-3
NACA flight curve; other fineness ratios remain engineering estimates. The
preview table uses a fixed reference atmosphere; actual flight uses weather-based
Reynolds numbers. Manual input values remain saved when switching modes.
See [the model documentation](../docs/AERODYNAMICS.md) for equations and limits.
See [material units, sources and limits](../docs/DESIGN.md#material-library-and-surface-data).

The canonical component design keeps axial positions and tail-to-nose coordinates;
body mass properties are calculated or explicitly overridden. Raw solver-only
off-axis surface tuples, alternative rocket coordinate frames, and native
Python callbacks are not editable component-design inputs. Wyoming uses the
frozen observation importer above the file importer; legacy URL forwarding is
not offered for new designs because that path cannot preserve its source through
the existing snapshot workflow. Other direct provider modes may fetch at run time.

The **발사장** navigation button opens the environment editor beside the map.
The editor has **위치 · 지형** and **시각 · 기상** tabs. Search Korean/English place
names or road addresses with Photon/OpenStreetMap, select a result, or enable
**지도에서 발사점 선택** and click the globe. Escape cancels picking; coordinate
inputs provide a keyboard alternative. Selections use WGS84 and invalidate the
previous terrain/geoid data. New editor projects default to **발사 고도 설정 →
지형 + 발사대 · 자동**: loading terrain sets the launch height to the sampled
surface plus the pad height and adopts its vertical reference. Changing the pad
height, location, or terrain recalculates it before online weather is requested.
The computed height/reference are read-only; the pad height remains editable and
can include a platform or structure not already represented in the elevation data.
Missing/NoData/out-of-bounds terrain or unknown references block running rather
than falling back to the previous launch height. **수동 입력 · 측량 고도** preserves
an explicitly entered height; its one-time alignment button remains under
**지형 자료**. The selected mode is saved in `.uarc` files. Legacy designs without
`environment.elevation_mode` remain manual so their saved heights are not changed.
The map's **표시 자료** selector distinguishes the edited launch site
from the selected run's immutable site and trajectory.

Place search defaults to **대한민국**; choose **전 세계** for overseas locations.
`UNIST`, `유니스트`, and `울산과학기술원` resolve through the same official-name
query, while `UNIST-gil`/`UNIST-gill` resolve to `유니스트길`. Results distinguish
universities, roads and bus stops, with address, source and coordinates. These are
representative place points rather than exact launch-pad positions. Unknown
overseas timezones are labelled for checking; selection does not change launch
time/elevation. Searches run only on submission, are serialized with at least
1.1 s between uncached lookups, and cache up to 128 query/scope pairs in memory.
Open-Meteo/GeoNames supplements empty or unavailable Photon searches. Failed
services are not cached as empty matches. Editing the query/scope discards stale
responses, and Enter while composing Korean text does not submit prematurely.
The public [Photon service](https://github.com/komoot/photon#demo-server) is for
modest usage and has no availability guarantee; a larger deployment needs its own
service. OSM attribution remains visible in the search panel.

In **시각 · 기상**, enter the launch date/time and an IANA timezone (for example,
`Asia/Seoul` or `UTC`). Choose **NOAA GFS** or **ECMWF IFS 0.25°** via Open-Meteo,
fetch the upper-air profile, inspect its grid/time/height table, and explicitly
apply it. Requests cover recent five days through the following nine calendar
days; individual models may have shorter availability. There is no silent fallback
when the chosen model/time is unavailable. Once an online profile is applied,
changing the location, height, or launch time automatically fetches and applies
the same provider's profile after a 600 ms debounce, even if the weather panel is
closed. Late responses are discarded when the site/provider changes or a manual
atmosphere is selected. Running stays blocked until matching weather is applied;
failed requests retain the previous snapshot and show an error. Use the existing
fetch/apply buttons to retry. Unchanged saved designs and run snapshots are not
refetched. Requests retain bounded responses and timeouts.

Alternatively choose **University of Wyoming · 고층 관측**, enter a five-digit
WMO station number and a separate UTC observation time (00/03/06/09/12/15/18/21).
This retrieves radiosonde observations rather than a launch-time forecast.
The preview shows station coordinates, distance to the launch site, time offset,
and any rows excluded for missing fields. The launch location/elevation stays
as entered. Automatic refresh preserves the explicitly selected station and UTC
observation time; it does not silently choose a different station. A station may
have no observation at the selected time.

Manual atmospheric curves and constants are preserved when moving. Imported
CSV/Excel profiles retain their numeric heights/values, source hash, and file
reference; their application site/time metadata follows the edited environment
without a network request. They still must cover the launch/flight heights.
Changing the vertical reference or geoid conversion requires reimporting the
profile rather than relabelling its saved heights.

The independent **기상 파일 가져오기** section accepts **CSV / Excel (.xlsx)**
from the native file picker. Select a worksheet, inspect the first five rows,
map the height/pressure/temperature/wind columns, and confirm every unit and
height reference. Units are not guessed. Wind supports east/north u/v or
speed and meteorological-from direction (north 0°, east 90°); speeds support
m/s, km/h, or knots. Heights support m/ft and ASL, launch-ground AGL, or
geopotential heights; pressure supports Pa/hPa, temperature K/°C.
Generate the weather preview, then click **이 기상 적용**. A launch time and WGS84
site must be set first; the file's actual location/time must match that intended
use. No network request is required for file import.

Files need unique column names in the first row and numeric values below it.
See [example CSV](../examples/weather.csv); select m, ASL, Pa, K, and u/v m/s
for that example. Limits: 8 MiB, 4096 data rows, 32 columns, 16 worksheets.
Use values rather than Excel formulas; save legacy .xls as .xlsx. Missing values,
duplicate heights, and nondecreasing pressure are rejected. Rows are sorted by
height. The normalized profile and original file are preserved when saving.

Applied weather profiles are embedded in `environment.weather_profile`, including
coordinates, time, model, retrieval timestamp, response hash, and numeric levels.
The engine builds pressure/temperature/wind from those frozen levels; saving and
rerunning do not refetch or reread the source. Changing site, elevation/reference, geoid
undulation, launch time, or timezone requires fetching/applying matching data.
Pending or late responses never overwrite another site's weather. Standard and
manual atmospheres remain available; manual constant pressure/temperature inputs
use Pa/K, and u/v winds use m/s.

Forecast limitations are displayed: hourly fields are interpolated in time (wind
as vectors); geopotential heights are converted with RocketPy's WGS84 radius;
surface pressure is downscaled to the launch elevation minus pad height. The 2 m
temperature and 10 m wind approximate the conditions at that ground anchor. Unknown vertical references
are treated as sea-level heights; ellipsoid heights require geoid undulation.
The profile begins at the pad's ground elevation and ends at the available upper-air
level (typically around 20 km). Runs outside that range, including a valley below
that ground elevation, fail rather than publishing extrapolated results. A finer
boundary-layer model and direct historical reanalysis service are not included.
Observation/file profiles use their own actual vertical range; launch elevation
must be inside that range before applying, and the entire flight must stay inside
it. Values outside the range are not extrapolated.

Terrain sources are selected in **발사 환경 → 위치·지형**:

- **AWS Open Data / Terrain Tiles** loads automatically for a valid WGS84 launch
  site when no frozen grid is attached; no AWS account or API key is needed.
  Coordinate edits are debounced and late responses are discarded. Weather/body
  edits do not trigger terrain requests. Other sources and saved grids are kept
  until the user explicitly replaces them; choosing AWS again after an alternate
  import loads AWS. The requested area is mosaicked and reprojected in Python to
  the frozen height grid used by both Cesium and ground contact. **AWS 지형
  새로고침** explicitly retries or applies changed radius/spacing settings.
- **국토정보플랫폼 / local DEM** opens its download portal and a native file picker
  accepts GeoTIFF, ERDAS IMG, ASCII Grid, and HGT. Large originals (up to 2 GiB)
  are read through a bounded warped window rather than copied into the input store.
  Self-contained rasters are required; convert external-file datasets into a
  single GeoTIFF. Native CRS metadata is used unless the user explicitly supplies
  an EPSG override. Height units and vertical reference are explicit; unknown
  vertical references cannot be used for terrain contact.
- **OpenTopography** opens its key-issuance page when selected. Paste a key and
  select SRTM GL1/GL3 (EGM96) or Copernicus DSM 30 m (EGM2008). Keys are held in
  memory for the request, never in design/run snapshots or diagnostic URLs.
- **Open Topo Data** remains an optional legacy 9×9 SRTM90m source.

Choose a radius from 100–5000 m and target spacing from 5–1000 m. A grid is capped
at 257×257 nodes and reports its actual spacing; interpolation cannot improve the
original DEM accuracy. Missing coverage or NoData rejects the import and preserves
existing terrain. Sources/runs retain heights, source, sampling/pixel spacing,
vertical reference, acquisition time, and a grid hash. Local replay needs no
provider request. Successful imports enable terrain contact. Automatic launch
height mode also aligns the height/reference; manual mode offers **지형 자료 →
발사 고도·기준을 지형 + 발사대로 맞추기** for one-time alignment.
Different orthometric datums cannot be converted using a single geoid offset.

The map's **배경 지도** selector offers none, OpenStreetMap roads, or **VWorld
satellite imagery**. Selecting VWorld opens its API-key site; enter the key and
press **연결**. The key stays in app memory and the service registration must allow
this application's origin. These are imagery tiles: their pixels never supply
collision heights. The app does not use the undocumented legacy VWorld DEM binary
endpoint. OpenTopography and VWorld requests require the user's valid credentials;
a key is not bundled. Provider/terrain credits remain visible or accessible.

The saved grid supplies Cesium heightmap terrain, so imagery follows the surface.
3D opens north-up at a 65° downward angle with grayscale relief shading and heights
at 1×. **발사장 맞춤** resets the view, and **전체 궤적** frames a selected result.
2D remains top-down. Ctrl+drag or the middle mouse button tilts/orbits the camera.
Submitting a simulation or selecting a run opens **비행 결과** and **지형 · 궤적**
together in separate dock groups, restoring closed panels and leaving already
separated groups in place. Result selection returns the map to 3D and frames the
whole flight, including short flights, at its actual size. **발사장 맞춤** still
frames the wider site. The outlined monochrome flight line uses absolute saved
altitudes, not heights clamped onto terrain. The plot time slider/playback moves
the map marker. Both views use the selected run's frozen site/DEM, even after the
editable design moves elsewhere. Pending/failed runs show their state without
displaying a previous run's trajectory; late responses cannot replace a newer
selection. Plot query filters do not crop the full map trajectory.
Hidden map panels pause rendering and resize on return. Dense grid lines are off
by default; **고도 격자** toggles them. The outline marks calculation coverage.
**지도 정보 · 도움말** starts collapsed; click its summary or use Enter/Space to
show coordinates, sources, height references and controls. The expanded area is
height-limited and scrollable. Loading and actionable errors remain visible.
For AWS, surrounding Terrarium elevation tiles stream into a 65×65 Web Mercator
heightmap rather than dropping the surface to zero outside a rectangular patch.
A bounded memory cache holds up to 64 decoded tiles; source zoom is capped at 14
and higher display levels interpolate those source tiles. Pixel edges are clamped
and Cesium skirts cover subpixel differences. Saved heights always override display
tiles inside the calculation grid; fully covered tiles need no network. Surrounding
tiles are visual context and never extend the solver's saved coverage. Invalid
display pixels use a validated lower-resolution parent tile when available, with
a visible notice; interpolation uses that parent's actual source level. Network
failures retain their cause instead of retrying every parent. Timeouts or
missing tiles show a warning and retain frozen heights, with an ellipsoid fallback
outside them. Other imported datasets remain bounded/offline; contact calculations
fail outside their saved coverage.
Display refinement ends at level 18 (about 2.4 m sample spacing at the equator),
already finer than the minimum 5 m acquisition spacing. Terminal tiles report
zero geometric error and no child data. A small pinned Cesium engine patch keeps
these leaves terminal even at zero camera distance; ordinary `pnpm install`
applies it. Render failures use the app's error/restart controls. Restart restores
terrain, imagery and entities, and negative-height initial framing starts above
the ellipsoid while terrain is loading.
The Cesium logo is removed using its public credit API; ion services are not used.

Set horizontal and vertical references explicitly before checking elevations.
EGM96 heights and ellipsoid heights require a local geoid undulation to compare.
Without it, the globe's absolute vertical placement is approximate and labelled.
The numeric terrain calculation uses the declared height reference, never the
rendered mesh. The CG preview excludes motor mass.

Terrain-contact mode uses an isolated event adapter verified against RocketPy
1.13.0 only. Other versions fail closed. It supports descent below launch height;
missing terrain coverage fails the run instead of substituting zero elevation.
The predicted contact point is limited by DEM resolution and the flight model.
Sub-grid features are not resolved and there is no separate 3D building collision
model. Map coordinate conversion is limited to 10 km from launch.

From the repository root, run:

```bash
corepack pnpm check
corepack pnpm lint
corepack pnpm lint:fix
corepack pnpm --dir frontend test
corepack pnpm --dir frontend format:check
corepack pnpm build
```

`check` runs Biome lint followed by TypeScript's `tsc --noEmit`; `lint` only runs
Biome, and `lint:fix` applies its safe fixes. Lint errors and warnings fail these
checks. Prettier remains the sole formatter (`format` / `format:check`), so adding
Biome does not introduce a second formatting style. Biome formatting and assist
actions are disabled in `biome.json`.

Biome 2.6.2 checks hand-written JS, TS, JSX/TSX, CSS, HTML, and frontend JSON.
HTML document analysis uses Biome's experimental full-support setting; HTML
formatting stays with Prettier. The configuration respects the repository's Git
ignore rules and excludes generated `src/lib/types.ts` from lint; TypeScript
still checks that file. No extra cache-ignore rule is needed for CLI linting.
Keep `biome.json` in Git alongside the dependency manifest and lockfile.

Python DTOs are generated by `backend/scripts/export_frontend_types.py`; after
regeneration run the frontend formatter. Native packaged rendering and live
provider availability require testing on the target computer.

### Portable design files

Click the name in the top header or project panel to rename the current design.
Enter or blur applies a nonblank name (up to 128 characters); Esc cancels.
Ctrl+S commits the edit before saving. Export suggests `<current name>.uarc`,
preserving Korean text and replacing filesystem-reserved characters with `_`.
Reserved device names and long UTF-8 filenames are handled at the export boundary.
The save dialog still allows a different filename; the design retains its own name.

Use **프로젝트 → 설계 파일 내보내기** to save `.uarc`, or **설계 파일 열기**
to open `.uarc` and existing `.json` designs. The dedicated extension contains
UTF-8 JSON using the existing `RocketDesign` contract and `schema_version: 1`.
Components, materials, liquid tanks, solver settings and frozen terrain/weather
are included; flight telemetry and API keys are not part of the design. Imported
files are bounded to 2 MiB and validated/compiled before replacing the editor.
Unsaved edits retain the existing confirmation. Cancelling a dialog changes
nothing. Existing export destinations are refused; choose a new filename.
External curve/weather file references must first become numeric tables or frozen
weather profiles so the exported file remains portable.
