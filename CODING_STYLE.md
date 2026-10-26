# UARC Coding Style & Architecture Guide

This document defines the architectural principles, coding conventions, and implementation guidelines for the UARC backend (`backend/app/`, `backend/tests/`) and planned frontend (`frontend/src/`).

All new contributions and refactorings must adhere to these standards.

---

## 1. Core Principles

1. **Separation of Concerns**
   * **Data Validation & DTOs**: Handled exclusively by `schemas.py` (Pydantic V2).
   * **Component Design & Mass Properties**: Handled by `design.py`; preserve editable designs separately from derived solver inputs. See [docs/DESIGN.md](./docs/DESIGN.md).
   * **Hardware Assembly & Numerical Solvers**: Handled exclusively by `engine.py` (RocketPy wrapper).
   * **Desktop Boundary & Lifecycle**: Handled by `bridge.py` and `main.py` (pywebview); `simulation/jobs.py` owns bounded scheduling and `simulation/worker.py` runs simulations in separate processes.
   * **Persistence**: Handled by `storage.py`.

2. **Explicit Over Implicit**
   * Avoid generic `**kwargs` or untyped dictionaries.
   * Prefer explicitly typed Config models and keyword-only arguments.

3. **Fail-Fast & Strict Contracts**
   * Reject invalid configurations at the schema layer before launching numerical solvers.
   * Use precise built-in exceptions (`ValueError`, `TypeError`, `RuntimeError`) rather than generic `Exception`.

4. **Units and Coordinate Conventions**
   * **SI Units**: All physical quantities use standard SI units (m, kg, s, Pa, K, N, kg·m²).
   * **Angles**: User-facing angles use degrees (°). Inclinations are normalized to $(0, 90]^\circ$; headings are normalized modulo $360^\circ$.
   * **Altitudes**: Explicitly differentiate and label ASL (Above Sea Level) versus AGL (Above Ground Level).

---

## 2. Data Schemas & DTOs (`app/schemas.py`)

Models in `schemas.py` serve as the single source of truth for bridge serialization, input validation, and reproducibility snapshots (`input.json`). The bridge validates JSON text with `model_validate_json` or `TypeAdapter.validate_json`, so JavaScript arrays can populate tuple fields without weakening strict Python validation.

### 2.1 Pure Serializable DTO Rule

* **No Runtime Objects**: Never include non-serializable RocketPy runtime objects (`AeroSurface`, `Tank`, `Flight`) as Pydantic fields. Do not enable `arbitrary_types_allowed`.
* **Round-Trip Guarantee**: Every config model must be capable of lossless round-trip serialization:
  $$\text{model} \equiv \text{type}(\text{model}).\text{model\_validate\_json}(\text{model}.\text{model\_dump\_json}())$$

### 2.2 Base Configuration

All configuration models must inherit from `EngineConfig`, which strictly forbids unmodeled extra fields:

```python
class EngineConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
```

### 2.3 Strict Numeric Constraints (`Annotated`)

* Use standard Python 3.10+ union syntax (`A | B`, `T | None`) instead of `Optional` or `Union`.
* Annotate numeric constraints declaratively:

```python
Number = Annotated[float, Field(strict=True, allow_inf_nan=False)]
Positive = Annotated[Number, Field(gt=0)]
NonNegative = Annotated[Number, Field(ge=0)]
```

### 2.4 Polymorphism: Discriminated Unions

Model variants (e.g., motor types) using Pydantic discriminated unions:

```python
class SolidMotorConfig(GrainMotorBase):
    motor_type: Literal["solid"] = "solid"

class LiquidMotorConfig(MotorBase):
    motor_type: Literal["liquid"] = "liquid"

MotorConfig = Annotated[
    SolidMotorConfig | LiquidMotorConfig | HybridMotorConfig | GenericMotorConfig,
    Field(discriminator="motor_type"),
]
```

### 2.5 Validation Layer

* Use `@field_validator` for field-level sanitization and format checks.
* Use `@model_validator(mode="after")` for cross-field consistency and physical sanity checks:

```python
@model_validator(mode="after")
def compatible_weather(self):
    if self.max_expected_height <= self.elevation:
        raise ValueError("max_expected_height must be above the launch elevation.")
    return self
```

---

## 3. Simulation Engine (`app/simulation/engine.py`)

`engine.py` consumes validated Config objects and drives RocketPy simulations.

### 3.1 Zero Redundant In-Line Validation

* Do not duplicate Pydantic validation checks inside engine functions.
* Accept typed Config models directly:

```python
# Correct
def build_environment(config: EnvironmentConfig) -> Environment: ...

# Incorrect: Raw parameters with manual assertion clutter
def build_environment(latitude: float, longitude: float, ...) -> Environment:
    if not -90 <= latitude <= 90:
        raise ValueError(...)
```

### 3.2 Keyword-Only Parameters for Non-Serializable Inputs

Pass runtime instances (`AeroSurface`, `Tank`) through explicit keyword-only arguments:

```python
def build_motor(config: MotorConfig, *, tanks: Sequence[tuple[Tank, float]] = ()) -> Motor:
    ...

def build_rocket(
    motor: Motor | None,
    config: RocketConfig,
    *,
    surfaces: Sequence[tuple[AeroSurface, float | tuple[float, float, float]]] = (),
) -> Rocket:
    ...
```

### 3.3 Mutation and Side-Effect Isolation

* RocketPy mutates stateful components during flight (e.g., mass depletion, parachute events).
* Always isolate reusable objects using `deepcopy()`:

```python
flight = Flight(
    rocket=deepcopy(rocket),
    environment=environment,
    ...
)
```

### 3.4 Solver Solution Integrity Check

Validate raw numerical integration solutions before returning to callers:

```python
solution = np.asarray(flight.solution_array, dtype=float)
if solution.ndim != 2 or solution.shape[1] != 14 or not np.isfinite(solution).all():
    raise RuntimeError("RocketPy returned an invalid flight solution.")
```

Reuse RocketPy's cached `solution_array` for validation, summaries, and storage.
Reject empty and time-reversed solutions as well as invalid shapes/non-finite data.

### 3.5 Worker and Persistence Boundaries

* Send serializable `SimulationConfig` data through the application boundary;
  build RocketPy tanks, surfaces, rockets, and environments inside a worker.
  Bounded design previews may build temporary aerodynamic surfaces through the
  engine to reuse their profiles; flight integration remains in worker processes.
* Each run uses a disposable `spawn` process. Bound active and pending work,
  monitor wall-clock time and supported memory limits, and reap stopped workers.
* Keep `Flight` and full state arrays inside workers. Save raw telemetry to `.npy`;
  bridge responses contain metadata, summaries, or bounded chart rows.
* The host owns SQLite writes and locks the data directory. Snapshot authorized
  local input files before queuing, and publish completion only after result files.
* Preserve numerical extrema and event samples when reducing chart data.
* Keep result contracts in `schemas.py` alongside inputs. Result JSON Schema is
  exposed through the bridge; do not weaken strict input validation for JavaScript.
* Standalone designs are immutable snapshots with their own copied input assets.
  CLI/native dialogs authorize local file import and export; arbitrary bridge
  paths do not grant filesystem access. Preserve existing export destinations.
* External importers must bound archive/XML input and reject unsupported physical
  features explicitly. Use declared mappings and reference fixtures.

---

## 4. Testing Guidelines (`backend/tests/`)

1. **Hermetic & Offline Execution**
   * Tests must execute entirely offline without network access or live weather API queries.
   * Use synthetic hardware fixtures:

     ```python
     def motor_parameters(kind="generic"): ...
     def rocket_parameters(): ...
     def surface_fixture(): ...
     ```

2. **Both Positive & Negative Coverage**
   * Test successful trajectory solves as well as expected boundary rejections (`ValidationError`, `ValueError`).

3. **Schema Round-Trip Verification**
   * Every model must be verified for JSON serialization / deserialization fidelity:

     ```python
     encoded = config.model_dump_json()
     restored = type(config).model_validate_json(encoded)
     self.assertEqual(encoded, restored.model_dump_json())
     ```

4. **Use Subtests**
   * Wrap parameterized test matrices (e.g., iterating across motor types or atmosphere models) with `with self.subTest(...):`.

---

## 5. Code Style & Tooling

* **Runtime**: Python 3.13+
* **Environment & Packaging**: `uv` (`pyproject.toml`, `uv.lock`)
* **Linting & Formatting**: [Ruff](https://docs.astral.sh/ruff/), installed through the `uv` development dependency group and configured in `backend/pyproject.toml`.
  * Run `uv run ruff check .` and `uv run ruff format --check .` from `backend/` before submitting changes.
  * The linter checks errors (`E4`, `E7`, `E9`, `F`), import ordering (`I`), naming (`N`), modern Python syntax (`UP`), common bug patterns (`B`), and simplifications (`SIM`). The Python target is inferred from `requires-python`.
  * Use `uv run ruff check --fix .` for supported safe fixes and `uv run ruff format .` for formatting. Review the diff; do not enable unsafe fixes by default or reformat unrelated code.
* **Formatting & Naming**: PEP 8 naming; Ruff formatting with a target line length of 88 characters and four-space indentation. Whitespace and line wrapping are handled by the formatter rather than duplicate lint rules.
  * Functions & variables: `snake_case`
  * Classes & types: `PascalCase`
  * Constants: `SCREAMING_SNAKE_CASE`
* **Import Ordering**:
  1. Standard library (`math`, `copy`, `collections.abc`, etc.)
  2. Third-party packages (`numpy`, `pydantic`, `rocketpy`, etc.)
  3. Local application imports (`app.schemas`, `app.simulation.engine`, etc.)
* **Docstrings**:
  * Concise and contract-focused. Specify input units, coordinate frames, and assumptions. Avoid repeating obvious variable names.

## 6. Frontend Conventions

The frontend should be as explicit and economical as the Python backend. Follow
the GUI requirements in [docs/GUI.md](./docs/GUI.md); planned stack entries are
options, not a requirement to install every library.

* Use React with strict TypeScript, ES modules, named exports, and small functions.
  Use `camelCase` for values/functions, `PascalCase` for components/types, and
  `SCREAMING_SNAKE_CASE` for constants. Avoid `any`, unchecked assertions, nested
  ternaries, speculative abstractions, and generic wrappers with one caller.
* Organize code by feature. Keep `App.tsx` responsible for workspace composition;
  keep geometry conversion, rendering, bridge calls, and form editing separate.
  Introduce shared components/hooks only when there is actual reuse or a clear
  lifecycle to own. Do not build a custom rendering or state-management framework.
* Keep one editable design and derive views from it. Camera/selection/layout state
  is separate from physical input. Parse finite numbers at the form boundary;
  allow intermediate text such as an empty field without committing invalid
  values. Pydantic remains authoritative for physical validation and mass models.
* Use concrete bridge input/result types matching Python schemas. Validate external
  responses at the boundary; do not scatter casts or replicate solver equations
  in UI components. Errors must remain visible and actionable.
* Effects synchronize external systems only. Clean up viewers, geometry/materials,
  observers, listeners, timers, and requests. Associate asynchronous work with its
  input revision and ignore obsolete responses. Never trigger flight integration
  from a render or numeric-input change.
* Prefer semantic HTML and native controls: labelled inputs, buttons, fieldsets,
  and tables. Make panel controls keyboard-accessible with visible focus. Provide
  a text/table equivalent for canvas-only data; do not rely on color or pointer
  interactions alone. Render imported text as text, never untrusted HTML.
* Start with a small global stylesheet for tokens, typography, focus, and workspace
  sizing, plus feature-scoped CSS where needed. Use CSS custom properties, Grid,
  and Flexbox; avoid inline style duplication, `!important`, deep selectors, and
  competing styling systems. Dynamic dimensions and canvas sizes may use inline
  styles. If adopting a listed CSS/UI library, use it consistently rather than
  adding a parallel system.
* Keep the visual language restrained: neutral surfaces, thin borders, compact
  spacing, one accent, tabular numbers, and explicit unit labels. Use motion only
  for navigation/playback; honor reduced-motion settings. Keep technical data
  attribution and validation details available without crowding the workspace.
* Use the project formatter/linter and TypeScript checks once the frontend toolchain
  exists. Add minimal runnable tests for geometry/coordinate conversion, stale
  response handling, and editing-to-preview behavior; use deterministic fixtures
  rather than live map services. Do not add dependencies for native capabilities.
