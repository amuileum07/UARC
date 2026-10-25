# Desktop host and simulation engine

## Setup and desktop entry point

From the `backend/` directory:

```bash
uv sync
uv run uarc --help
```

`uv sync` includes development dependencies such as Ruff and updates `uv.lock`
when dependency declarations change. Commit the updated lockfile with dependency
changes; use `uv sync --locked` when the lockfile must remain unchanged.

The project installs `app/` directly and exposes `uarc` through `app.main:main`.
FastAPI/Uvicorn have been replaced with pywebview. Linux installs the PySide6
renderer automatically; Windows and macOS use pywebview's platform dependencies.
Windows also needs its WebView2 runtime; platform details are in the
[pywebview installation guide](https://pywebview.flowrl.com/guide/installation.html).

The React/Vite application has not been implemented yet. Once a local Vite
server or built frontend is available, launch it inside the desktop window:

```bash
uv run uarc --dev-url http://localhost:5173
uv run uarc --frontend ../frontend/dist/index.html
```

Run the backend immediately without frontend assets using the synthetic example:

```bash
uv run python -m app.simulation ../examples/simulation.json --data-dir ../data
```

The example models synthetic hardware, not a real flight vehicle. The command
prints stage changes to stderr and a run ID plus summary JSON to stdout.
Ctrl+C cancels the worker and exits with status 130. Failed or timed-out runs
exit with status 1. The same scheduler and storage serve the GUI bridge.

Without options, the launcher looks for `frontend/dist/index.html` in this
checkout. A missing build produces an explicit error rather than an empty
window. Use `--frontend` to supply assets when running an installed wheel.
Distributable executable packaging and actual GUI rendering still require
separate verification on each target OS.

## Desktop bridge

`app/bridge.py` exposes validation, simulation jobs, and stored results;
`kind` is `environment`, `motor`, `rocket`, `flight`, or `simulation`.
Parametric component inputs additionally use `kind="design"`.
The existing frontend helper in
`frontend/src/lib/bridge.ts` waits for `pywebviewready`, sends JSON text, and
propagates validation errors as rejected promises:

```typescript
const config = await validateConfig("environment", {
  latitude: 35.57, longitude: 129.18, elevation: 53,
});
```

The bridge uses Pydantic's JSON validation mode so JavaScript arrays populate
tuple fields, including inertia and curves, without weakening strict Python
validation. `engine.py` and `schemas.py` are unchanged by the desktop migration:
neither module depends on FastAPI or pywebview. Native RocketPy objects remain
inside the worker process. The GUI loop stays on the main thread.

| Bridge method | Result |
| --- | --- |
| `get_config_schema(kind)` | JSON Schema for an input model |
| `validate_config(kind, payload_json)` | Validated JSON-compatible config |
| `submit_simulation(payload_json)` | Queued run record, including `run_id` |
| `preview_design(payload_json)` | Derived solver input and component/assembly mass report |
| `submit_design(payload_json)` | Compile, snapshot, and queue a component design |
| `get_design(run_id)` | Editable saved component design |
| `get_design_report(run_id)` | Saved automatic/effective mass properties and component outlines |
| `rerun(run_id)` | Queue a new run from a finished run's frozen solver inputs |
| `get_run(run_id)` | State, stage, timestamps, worker PID, error, and sampled peak RSS |
| `list_runs(limit=50, offset=0)` | Newest-first persistent history; up to 1000 records per request |
| `cancel_run(run_id)` | Updated record; running jobs pass through `cancelling` |
| `get_summary(run_id)` | Small summary for a succeeded run |
| `get_telemetry(run_id, query_json="{}")` | Bounded rows for selected columns and time range |

`SimulationConfig` combines `environment`, `motor` (or `null` for an unpowered
flight), `rocket`, and `flight`, with optional `surfaces` and `tanks`.
Serializable surfaces cover nose cones, trapezoidal/elliptical fins, and tails.
Liquid/hybrid motors require cylindrical mass-based tanks; solid/generic motors
reject tanks. Other native components remain available through the Python engine
API and need explicit DTO support before they can cross the desktop boundary.

For example, once the desktop page has a validated simulation config:

```javascript
const api = window.pywebview.api;
const run = await api.submit_simulation(JSON.stringify(config));
const status = await api.get_run(run.run_id);
// Poll until succeeded, failed, cancelled, timed_out, or interrupted.
// On success:
const summary = await api.get_summary(run.run_id);
const telemetry = await api.get_telemetry(run.run_id, JSON.stringify({
  columns: ["time_s", "z_asl_m", "vz_m_s"],
  start_time: 0,
  end_time: 30,
  max_points: 2000,
}));
```

The React job UI is not implemented yet. `bridge.ts` wraps input validation,
design preview/submission, saved design/report loading, and replay requests.

## Numeric component design

`RocketDesign` stores editable dimensions, materials, component positions, motor
and fuel parameters, and measured overrides. `app/design.py` calculates airframe
mass, axial CG, and inertia before producing the existing `SimulationConfig`.
See [the design format and model assumptions](../docs/DESIGN.md).

From `backend/`, preview the synthetic numeric design without creating a run:

```bash
uv run python -m app.simulation ../examples/design.json --design --preview
```

Edit numbers in `examples/design.json`, then run the supervised simulation:

```bash
uv run python -m app.simulation ../examples/design.json --design --data-dir ../data
```

Design runs save both `design.json` and `design_report.json`, alongside the frozen
solver input and copied files. `get_design()` returns a model that can be edited
and submitted again even after its original local files are removed. A replay
uses a new run ID and never overwrites prior results. Flight summaries include
initial/final mass and CG for the complete rocket, including motor and propellant.

## Scheduling, storage, and resource limits

`simulation/jobs.py` starts a fresh `spawn` process for each run, with default
limits of one worker, eight additional pending slots, and 300 wall-clock seconds
per worker. Startup, weather loading, solving, and saving count toward that
deadline; queued time does not. A full queue rejects new submissions before
creating a run. Public bridge calls are synchronized independently of numerical
execution. Native BLAS/OpenMP thread limits are set to one for spawned workers.

GUI options are `--workers`, `--queue-size`, `--job-timeout`, `--data-dir`, and
`--memory-limit-mb`. The headless command accepts the last three options. On
Linux, each worker defaults to a 1024 MiB RSS limit, monitored through `/proc`
approximately every 100 ms; `--memory-limit-mb 0` disables it. Sampling can
overshoot the limit and is not an OS-enforced memory sandbox. Other platforms
currently have no RSS monitor. Account for worker count, GUI memory, and OS
headroom when selecting limits.

States are `queued`, `running`, `cancelling`, `succeeded`, `failed`, `cancelled`,
`timed_out`, and `interrupted`. Stages report startup/building/simulating/saving,
not a fabricated completion percentage. Cancellation and timeout terminate the
individual process, escalating to kill after one second. GUI shutdown cancels
pending/running work and reaps children. A child watches for host death and
exits if the host disappears. Restart marks unfinished records `interrupted`;
completed runs remain available. One host owns a data directory at a time.

By default, data is stored under `$XDG_DATA_HOME/uarc` (or
`~/.local/share/uarc`) on Linux, `~/Library/Application Support/uarc` on macOS,
and `%LOCALAPPDATA%/uarc` on Windows. `--data-dir` overrides this location.
SQLite contains metadata only. Each `runs/<run-id>/` directory contains
`input.json`, `runtime.json`, `telemetry.npy`, `summary.json`, and `complete.json`;
stage/error diagnostics and copied input files may also be present. A completion
marker is published only after results are saved, and the scheduler additionally
requires a successful worker exit. Failed or cancelled runs do not expose results.
Existing published runs are never overwritten. Partial files are retained for
inspection; automatic retention/deletion is not implemented.

JSON requests are limited to 2 MiB. Local file references must resolve to regular
files inside `<data-dir>/inputs/` or copied input assets of known runs; relative
paths are resolved under `inputs/`. Run metadata files cannot be used as assets. Accepted
files are copied into the run directory at submission, with a combined 64 MiB
limit and a check for source changes during copying. Provider identifiers such
as `GFS` remain provider identifiers; live weather responses are not frozen by
these local-file snapshots.

Telemetry queries accept known unique column names, inclusive `start_time` and
`end_time` bounds, and `max_points` between 32 and 10000 (default 2000).
Results contain `columns`, row-major `data`, `total_rows`, `matched_rows`,
`returned_rows`, and `decimated`. Full arrays stay in `.npy` files and are read
with memory mapping. Larger requests use bucket min/max sampling, preserving
endpoints and samples nearest apogee/parachute event times. At most two telemetry
reads run concurrently; an additional request is rejected for retry. Output and
scan buffers are bounded, but a wide time range still scans its source rows;
very large interactive histories may need precomputed multiresolution data.
RocketPy still keeps full integration histories in a worker's RAM, so memory
mapping does not eliminate the solver's memory cost.

## Simulation engine

`app/simulation/engine.py` assembles caller-supplied RocketPy models and runs a
single flight. It contains no preset rocket, motor, launch location, or data-file
path. All quantities use SI units; launch angles use degrees.

| Function | Inputs | Result |
| --- | --- | --- |
| `build_environment` | `EnvironmentConfig` | `Environment` |
| `build_motor` | A concrete motor config; optional runtime `tanks` keyword | `Motor` |
| `build_rocket` | Motor, `RocketConfig`, and optional runtime `surfaces` keyword | `Rocket` |
| `run_simulation` | Rocket, environment, and `FlightConfig` | `Flight` |
| `summarize_flight` | A computed `Flight` | Dictionary of numbers, flags, strings, and nullable event values |

The complete `Flight` remains available for RocketPy's plots, telemetry, and
exporters. `run_simulation` returns this object, not the summary dictionary.
The scheduler keeps it inside the worker and saves its state array before the
process exits.
The engine performs synchronous computation; scheduling and file storage belong
to the calling application.

`app/schemas.py` validates types, ranges, curves, and relationships between input
values when a configuration is created. Invalid input raises Pydantic's
`ValidationError` before reaching the engine. The engine handles assembly and
computation; errors while loading files/weather or solving a flight propagate to
its caller. Schemas contain only serializable data and expose JSON Schema;
RocketPy instances and Python callbacks stay outside these models. Surface and
tank objects are separate engine arguments. Inertia checks remain at the input
boundary because RocketPy does not enforce physical principal moments. Solver
output checks reject non-finite, empty, or time-reversed results. Validation,
summarization, and saving reuse RocketPy's cached `solution_array`.

## Example

Run from the `backend/` directory using the project's Python environment.
These synthetic values demonstrate the interface and do not represent real
hardware. Production inputs must come from the vehicle being modeled.

```python
from rocketpy import NoseCone, TrapezoidalFins
from app.schemas import (
    EnvironmentConfig,
    FlightConfig,
    GenericMotorConfig,
    RocketConfig,
)
from app.simulation.engine import (
    build_environment,
    build_motor,
    build_rocket,
    run_simulation,
    summarize_flight,
)

environment = build_environment(
    EnvironmentConfig(
        latitude=0,
        longitude=0,
        elevation=120,
    )
)
motor = build_motor(
    GenericMotorConfig(
        thrust_source=[(0, 0), (0.05, 60), (0.9, 60), (1, 0)],
        burn_time=1,
        chamber_radius=0.018,
        chamber_height=0.12,
        chamber_position=0.07,
        propellant_initial_mass=0.1,
        nozzle_radius=0.01,
        dry_mass=0.15,
        dry_inertia=(0.001, 0.001, 0.0001),
    )
)
rocket = build_rocket(
    motor,
    RocketConfig(
        radius=0.025,
        mass=1.2,
        inertia=(0.08, 0.08, 0.002),
        power_off_drag=0.5,
        power_on_drag=0.4,
        center_of_mass_without_motor=0,
        motor_position=-0.45,
        parachutes=[dict(name="recovery", cd_s=0.3, trigger="apogee", lag=0.1)],
    ),
    surfaces=[
        (NoseCone(length=0.2, kind="conical", base_radius=0.025), 0.7),
        (
            TrapezoidalFins(
                n=4, root_chord=0.12, tip_chord=0.05, span=0.08, rocket_radius=0.025
            ),
            -0.35,
        ),
    ],
)
flight = run_simulation(
    rocket,
    environment,
    FlightConfig(
        rail_length=1.5,
        inclination=85,
        heading=0,
        max_time=60,
        max_time_step=0.05,
    ),
)
summary = summarize_flight(flight)
print(summary)
```

## Input and result conventions

- Choose `SolidMotorConfig`, `LiquidMotorConfig`, `HybridMotorConfig`, or
  `GenericMotorConfig`. Each model declares its required fields and defaults
  explicitly, using native constructor keyword names. `MotorConfig` is the
  discriminated union of those models, selected by `motor_type`; JSON consumers
  can validate it with `TypeAdapter(MotorConfig).validate_json(payload)`.
  There is no generic `parameters` bag or constructor-signature inspection.
- Body mass and inertia exclude the entire motor. Body positions share the
  rocket coordinate system; `motor_position` locates the motor coordinate origin.
  Motor/tank positions use the motor's own coordinate system.
- `build_rocket(..., surfaces=...)` accepts `(AeroSurface, position)` pairs, including native nose, fin,
  tail, and custom surfaces. Positions can be axial scalars or `(x, y, z)` tuples.
  `parachutes` and `rail_buttons` use native `Rocket.add_parachute` and
  `Rocket.set_rail_buttons` keyword names. Additional sensors, air brakes, or
  controllers can be attached through RocketPy before running the flight.
- Liquid/hybrid motor construction requires `build_motor(config, tanks=[(tank, position), ...])` with
  configured RocketPy `Tank` objects. Solid/generic motors do not accept tanks.
- Curve fields accept constants, increasing two-column tables, or file path
  strings. Pass `str(path)` for a `Path` object. The application must resolve and
  authorize file paths before calling the engine; a string schema does not make
  arbitrary browser-supplied paths safe. File and solver errors propagate.
- For advanced Python inputs, use native RocketPy interfaces: construct a motor
  with a callable/`Function` thrust source and pass it to `build_rocket`; call
  `environment.set_atmospheric_model(...)` for callable weather profiles or
  `rocket.add_parachute(...)` for callback triggers before `run_simulation`.
  Native custom solvers can be used directly with `Flight`. These runtime values
  are intentionally excluded from serializable DTO fields.
- Environment profile heights are ASL meters. Pressure is Pa, temperature K,
  `wind_u` points east, and `wind_v` north. Scalars apply at every altitude.
  Omitted pressure/temperature retain ISA profiles. Weather models may adjust
  RocketPy's `max_expected_height` when loading their data.
- With no `atmosphere_type`, weather overrides select `custom_atmosphere`;
  otherwise the default is `standard_atmosphere`. Explicit external models use
  `atmosphere_type`, `atmosphere_file`, `atmosphere_dictionary`, and optionally
  `pressure_conversion_factor`. Forecast/reanalysis/ensemble/Windy require a
  date. `ensemble_member` selects a loaded ensemble member. Network failures do
  not silently fall back to ISA. Live weather service availability is external.
- `inclination` is relative to the horizontal: 90 degrees is vertical. `heading`
  is clockwise from north and is normalized modulo 360. Standard rail launches
  use an inclination in `(0, 90]`. To resume, set
  `initial_solution=tuple(previous_flight.solution[-1])`, a 14-value numeric state;
  `max_time` must exceed its start time.
- Flight options such as `terminate_on_apogee`, `rtol`, `atol`, `ode_solver`, and
  `simulation_mode` pass to RocketPy. `max_time` is simulated time, not a server
  timeout. `max_time_step=None` means no upper limit and round-trips through JSON.
  Each run copies the rocket to isolate mutable histories; callers must
  manage state in their own callbacks and avoid mutating a shared environment.
- Summary apogee/impact fields are `None` until their events occur. AGL is relative
  to the launch site's elevation. `max_*` values cover only the simulated interval.
  `termination_reason` is `impact`, `apogee`, `time_limit`, or `stopped`.
  `impact_speed_m_s` is the full velocity magnitude, not signed vertical velocity.

## Code quality

Ruff uses `pyproject.toml` to lint and format `app/` and `tests/`. Its formatter
also handles supported Python examples in Markdown files. `uv.lock` records
its installed version.
See [CODING_STYLE.md](../CODING_STYLE.md) for the enabled rules and conventions.
All commands below run from `backend/`; `.` means the current directory and its
subdirectories. `uv run` uses the project's environment, so activating `.venv`
or installing Ruff globally is unnecessary.

| Command | Purpose | Edits files? |
| --- | --- | --- |
| `uv run ruff check .` | Report lint violations such as import ordering or suspicious code | No |
| `uv run ruff check --fix .` | Apply supported safe lint fixes and report remaining violations | Yes |
| `uv run ruff format .` | Normalize spacing, indentation, and line wrapping | Yes |
| `uv run ruff format --check .` | Report files whose formatting would change | No |

For a normal development pass, apply safe lint fixes first, then format:

```bash
uv run ruff check --fix .
uv run ruff format .
```

If `check --fix` still reports violations, read them and correct the code
manually; a nonzero exit status can mean that some fixes succeeded but others
remain. `format` only changes formatting and does not resolve every lint rule.
Review changes with `git diff`, then verify:

```bash
uv run ruff check .
uv run ruff format --check .
uv run python -m unittest discover -s tests -v
```

`All checks passed!` means linting passed. `files already formatted` means
formatting passed. `files would be reformatted` means the check found formatting
changes but did not apply them; run `uv run ruff format .` to apply them.
If the formatting check prints a long diff, use
`uv run ruff format --check . --output-format concise` for a shorter report.

A lint diagnostic such as
`app/schemas.py:24:48: B905 ...` identifies the file, line, column, and rule code.
The `[*]` marker identifies a supported safe automatic fix. To read a rule's
explanation, run `uv run ruff rule B905`, substituting the reported code.
Do not enable `--unsafe-fixes` by default: those fixes may change behavior.

To limit work to one file, replace `.` with its path, for example
`uv run ruff check app/schemas.py` or `uv run ruff format app/schemas.py`.
Lint and formatting checks do not execute the application; the unittest command
checks runtime behavior. Before committing, review both the code changes and
the test results. Keep later style fixes scoped to the code being changed.

## Verification

```bash
cd backend
.venv/bin/python -m unittest discover -s tests -v
```

From the repository root, Node.js 22.20+ can run the bridge tests without npm
dependencies (TypeScript syntax is stripped for this runtime check):

```bash
node --experimental-strip-types --test frontend/src/lib/bridge.test.mjs
```

Desktop tests exercise bridge validation and launcher wiring without opening a
window. Frontend tests cover bridge readiness, JSON transport, Python errors,
and use outside the desktop host. They do not replace a future TypeScript build
or native GUI test.

Tests use synthetic hardware and offline weather. They compare actual flight
results with native RocketPy, exercise all four motor types, and check early
termination, recovery, repeated runs, profiles, validation, and weather errors.
They also check JSON round-trips, JSON Schema generation, required motor fields,
and rejection of runtime objects in DTOs and invalid solver results.
External weather forwarding is mocked; it does not verify live forecast services.
