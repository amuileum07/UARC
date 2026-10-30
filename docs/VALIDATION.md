# Backend verification — 2026-10-25

## Intel Mac: avoid MSAA before the first GPU fault (2026-10-30)

[Run 40997785694](https://github.com/amuileum07/UARC/actions/runs/40997785694)
at `872f053` passed prepare and the complete Windows, Linux and Mac arm64 jobs.
This confirms the Linux native-close changes in the hosted Xvfb environment.
Intel Mac alone failed: both the initial and non-MSAA retry contexts were
already lost during creation. The process then closed normally, with job cleanup
logged, instead of waiting for the old GUI deadline.

The Intel job used image `20260824.0482.1` and macOS 15.7.9. That exact image is
covered by [runner-images issue 14836](https://github.com/actions/runner-images/issues/14836),
where maintainers reproduced virtual-GPU hangs/wrong results with MSAA. The
report notes that subsequent requests can remain broken after a fault. UARC
still requested MSAA before its fallback, and Cesium separately defaulted to
4x scene MSAA. This is a supported hypothesis for this run, not a driver-level
diagnosis of UARC's VM.

Both engines now avoid MSAA from the outset: shared canvas attributes disable
antialiasing, and Cesium scene samples are explicitly one. No user-agent or CPU
heuristic is used. The rocket helper no longer requests an MSAA context before
retrying. Live contexts, shader capabilities, real 3D frames and normal process
exit remain mandatory. Reports include the actual canvas attributes and scene
sample count; Intel CI also logs bounded, read-only model/graphics diagnostics.

The change affects edge smoothing, not simulation inputs/results or geometry.
It must still be confirmed on a new Intel Mac job. A 2D fallback or an absent
WebGL context cannot pass the acceptance check.

There is also a related Intel-hosted WebKit limitation in
[WebKit bug 278277](https://bugs.webkit.org/show_bug.cgi?id=278277); the current
[Playwright Modernizr tests](https://github.com/microsoft/playwright/blob/main/tests/library/modernizr.spec.ts)
exclude Intel macOS WebKit WebGL cases with that reference. Those reports do not
prove UARC's exact driver failure or imply all physical Intel Macs lack WebGL.
The harness therefore now runs an independent, library-free native WebGL 2
triangle/pixel-readback probe before loading the application UI, in separate
test data. If that also fails, the failure predates UARC's frontend and needs a
GPU-capable Intel environment, rather than further guessed renderer changes.
The probe and the original full frontend checks are all required.

Locally, a new Linux bundle/archive containing the single-sample settings passed
the complete Xvfb scenario. The independent probe read back `[255, 0, 0, 255]`;
both app launches reported `antialias=false` for both engines and Cesium samples
equal to one, with identical saved results for run
`647b23bf6f3c41e0a472c5cb170cb297`. All three native processes exited normally.
Diagnostics are under `/tmp/uarc-run40997785694-preflight`. All 48 frontend/driver
tests and 12 focused Python acceptance tests passed, as did Ruff lint/format,
Biome (both external JavaScript probes included), TypeScript, the frontend build,
Prettier checks and YAML/diff validation. Intel native acceptance remains
unverified until the updated workflow runs.

## Desktop acceptance: remaining close and WebGL failures (2026-10-30)

[Run 40994359625](https://github.com/amuileum07/UARC/actions/runs/40994359625)
at `73b9a55` completed prepare and all four native builds/archives. Windows and
Mac arm64 passed the entire archive/UI/normal-relaunch scenario. Their reports
identified SwiftShader and Apple GPU respectively, with identical stored flight
results after relaunch.

Linux produced successful first and reopened UI reports, including both WebGL 2
canvases, but the reopened process failed to exit within 180 seconds. The job
correctly failed despite its successful report. Logs contained repeated
DMA-BUF acquisition/null-texture failures and Qt's warning about Mesa software
rasterization. The CI compositor now uses software bitmaps while preserving
WebGL through llvmpipe. The Promise callback also requests native close from a
separate thread, allowing Qt's WebChannel callback to return before page
destruction. Debug logs now identify the native-loop and job-cleanup boundaries;
the old report alone did not locate the operation that blocked.

Mac Intel passed input edit/save/load and failed during Three.js initialization:
WebKit returned null for `getShaderPrecisionFormat`, before the first rendered
rocket canvas. Initialization now checks the actual context/shader capabilities,
releases an unusable context, and retries once without MSAA. If both attempts
fail, the app keeps its 2D fallback and the strict 3D acceptance check still
fails. This is a bounded recovery attempt, not confirmation that the hosted
Intel GPU supports the scenario. The next native run must establish that.

Focused regressions cover closing outside the Promise callback thread, report
publication before close, lost contexts, null precision results, failed retries
and ordinary multisampled initialization. The full backend suite passed 222
tests with five Windows-only tests skipped on Linux; frontend/driver tests
passed all 48 cases. Ruff, Biome, TypeScript and the production frontend build
passed.

A fresh Linux bundle containing these application changes was built and
archived as `UARC-v0.1.1-linux-x86_64.tar.gz`. The complete archive scenario
passed on both the desktop display and Xvfb at 1280x1024x24, using the updated
CI compositor flags. Xvfb was unpacked under `/tmp/uarc-xvfb-runtime`; no system
package was installed. Both Xvfb launches reported real llvmpipe WebGL 2
rendering, matching flight results for run `2aa50118d0f940678b07eca04f779a50`,
and normal exit. Their logs reached both `Native webview event loop stopped`
and `Simulation jobs closed`, without the earlier DMA-BUF/null-texture failures.
Diagnostics are under `/tmp/uarc-run40994359625-xvfb`. Hosted native verification
of the new code, especially the Intel Mac recovery path, remains pending.

## First desktop acceptance matrix failures (2026-10-30)

[Run 40991469565](https://github.com/amuileum07/UARC/actions/runs/40991469565)
at `32211e9` passed prepare, all four native builds, final archive creation and
the relocated CLI worker/file checks. All four jobs then failed the new UI
acceptance step:

- Windows stopped before launching the GUI: printing the Korean extraction path
  raised `UnicodeEncodeError` on the parent runner's cp1252 stdout. The child
  UTF-8 setting does not change its parent's stream. Launcher logs now use ASCII
  path escapes; a regression runs `run_ui` with a strict cp1252 output stream.
- Ubuntu reached design edit/save/load but failed to create WebGL 2 contexts.
  Chromium reported `WebGL2 blocklisted` for Mesa llvmpipe. The Xvfb CI step now
  explicitly selects Mesa software rendering and ignores that GPU blocklist;
  both rendered 3D canvases and a live context remain required.
- Mac arm64 timed out waiting for the JSON editor; Intel timed out waiting for
  the edited mass. The app header can mount before Dockview initializes, and
  synthetic DOM input can precede React's state commit. The script now waits for
  an existing/selected dock tab and React's committed textarea value, and yields
  browser action tasks. These races are covered by focused JavaScript tests.

The native reports confirm that both Mac frontends loaded with a working bridge.
They no longer reproduce the earlier missing-document/startup timeout. Native
acceptance of these changes still needs a new workflow run; a repaired test
harness is not evidence that later steps passed on Windows or either Mac.

Locally, the final script passed the complete existing Linux archive check with
the same software-rendering settings: both canvases reported
`ANGLE (Mesa, llvmpipe (LLVM 15.0.7 256 bits), OpenGL 4.5)`. Both normal GUI
launches succeeded and loaded the identical result for run
`b78bb1d4ab7e495ba5984154e8069744`. This included the explicit React input-commit
wait. The archive's application code/assets were unchanged; this follow-up only
changes the external acceptance harness, tests and CI environment.

All 11 focused Python acceptance tests and all 44 frontend/driver tests passed.
Ruff lint/format, Biome (including the full UI-check JavaScript), TypeScript,
the new test's Prettier check and YAML/diff checks passed. A new manual dispatch
on the updated commit is required; rerunning the old run retains its old SHA.

## Final desktop archive and shipping UI acceptance (2026-10-30)

The separate `Desktop acceptance` workflow builds all four native targets and
checks the final extracted archive, production frontend, normal close and
relaunch. It has read-only permissions and no release/version/publishing steps.
The release workflow and its existing gates are unchanged.

Locally, a fresh Linux PyInstaller bundle was archived with the release script,
extracted under `UARC 설치 한글 .../압축 해제 폴더/UARC`, and executed outside the
checkout. The relocated CLI passed preview, worker flights, compressed NetCDF4
weather, history, CSV, saved designs, OpenRocket import, cancellation and reaping.
The actual shipped frontend then passed both launches:

- Change payload mass from 1.00 to 1.05 kg through the JSON editor and validator.
- Rename/save two designs and load the first through the project explorer.
- Render the rocket with a live WebGL 2 context, click simulate, and display
  metrics, the result chart and a rendered local-terrain 3D trajectory.
- Close through the native window API and exit successfully, then repeat startup
  with the same data and load the original design and completed run through UI.

Both reports were successful and had identical summaries for run
`912ec15e2077423ebc2c703c2f1e14a5`. A read-only database inspection confirmed two
designs and one run. No forced process cleanup was needed. The local machine
lacked `xvfb`, so this run used its desktop display; the workflow installs `xvfb`
on the Linux runner.

Frontend lint/types, all 42 frontend tests and production build passed. The
backend full suite passed 218 tests with five Windows-only cases skipped on
Linux; the final acceptance harness tests are checked separately. Ruff and diff
checks passed. Reports/logs are retained locally under
`/tmp/uarc-acceptance-checks-20261030` and the workflow uploads per-target
diagnostics even on failure.

The new workflow has not yet run on GitHub Actions. This does not confirm the
new GUI scenario on Windows, either Mac architecture, or the hosted Linux
display. GPU image quality, online providers, native dialogs and missing-runtime
behavior on clean VMs remain outside this automated scenario.

## Mac test-fixture path follow-up (2026-10-30)

[Run 40913631718](https://github.com/amuileum07/UARC/actions/runs/40913631718)
at `2e1853c` completed the full Windows and Linux jobs successfully. Both Mac
jobs failed in the focused unit checks before building or running the GUI.
The deadline test mocked `Popen` but supplied a nonexistent `fake-uarc` command;
Darwin's preceding `shutil.which()` check therefore raised `FileNotFoundError`.
The early-exit/logging fixture had the same latent omission. Both were reproduced
locally by selecting the Darwin code path.

Both fixtures now supply the real `sys.executable` path while keeping process
creation mocked. Each exercises the Linux, Windows and Darwin branches, requiring
the intended timeout/early-exit result and an actual call to the mocked launcher.
Application/runtime code and command validation are unchanged.

The GUI portability, GUI-report and focused URL tests passed 14 cases locally;
the native Windows file-lock case was skipped on Linux. Ruff lint/format and
diff checks passed. These branch checks repair the Mac unit-test gate; native
Mac GUI acceptance remains unverified until the next workflow run reaches it.

## Windows process tree and Cocoa URL follow-up (2026-10-30)

[Run 40900576819](https://github.com/amuileum07/UARC/actions/runs/40900576819)
at `18e9748` built all four executables and passed every frozen worker/file check,
including both Mac architectures. Linux completed its whole job. Windows passed
the installed GUI/browser/bridge/save checks, then failed temporary-directory
cleanup with WinError 32 on `.owner.lock`. Both Mac jobs still received no
committed GUI report, despite Cocoa's `loaded` message. Publication was skipped.

The Windows harness terminated the installed console launcher instead of its
complete process tree. A Python child can retain the application's owner lock.
Cleanup now uses `taskkill /PID <this test's pid> /T /F` before waiting and deleting
temporary data. It does not select unrelated processes by image name, and an
unsuccessful tree termination remains a test failure. A native Windows regression
starts a real Python launcher/child pair, proves the child has locked a file,
then requires tree cleanup to release it. It is skipped on Linux and runs in
the Windows matrix job.

Tracing pywebview's actual window initialization reproduced a resolved Cocoa URL
containing raw `검증 page.html`. The pinned Cocoa backend quotes only spaces before
passing it to NSURL. A synchronous public `initialized` handler now percent-encodes
Unicode/spaces before navigation, preserving IPv6/query/fragment delimiters and
existing escapes. Tests exercise real Window initialization and real encoded
Korean-file HTTP retrieval, including the Mac WSGI substitute. Mac matrix tests
also log whether Foundation accepts the raw Unicode URL and assert that it
accepts the encoded URL. The earlier logs did not identify the actual loaded
document, so this remains a native acceptance issue pending another Mac run.
Debug output now records the URL/title/document/bridge state and the probe's
current JavaScript stage, allowing a navigation error page to be identified.

The focused launcher/URL checks run on every native matrix OS before packaging.
The full Linux suite completed 216 tests in 90.249 s: 211 passed and five
Windows-only tests skipped (four Tk GUI tests plus the new native file-lock
regression). Ruff lint/format, workflow parsing and diff checks passed. A new
wheel passed fresh dependency installation, native I/O, spawned simulation/history,
actual Qt GUI/bridge/save and an identical offline sdist rebuild. A newly rebuilt
Linux executable passed all frozen worker/file/cancellation operations and the
actual GUI/bridge/save check; its debug log identified the intended UTF-8 page.
These checks do not confirm native Windows cleanup or Mac GUI success for this
patch; the next matrix run must do that.

## Frozen startup and bridge-report follow-up (2026-10-30)

The new user-supplied Intel Mac log reaches the built executable's first real
`--simulate` run and exceeds the bundle smoke check's 60-second limit. The
preview already passed. The arm64 attachment reaches Cocoa page load, bridge
injection and `loaded`, but receives no HTTP callback. The earlier DNS change
alone did not complete Mac GUI acceptance. The two failures occur in different
checks; the supplied Intel traceback omits captured child stdout/stderr.

Tracing frozen startup found that PyInstaller's Matplotlib runtime hook creates
a fresh font-cache directory for every process. RocketPy eagerly imports plotting
modules, and a cold Matplotlib font manager invokes `system_profiler` on Mac.
The frozen entry point now defaults to Matplotlib 3.11's documented
[`MPL_IGNORE_SYSTEM_FONTS`](https://matplotlib.org/stable/install/environment_variables_faq.html)
before spawn dispatch and numerical imports. Hosts and workers use bundled fonts;
UARC's frontend plots retain their browser fonts. An explicit existing setting is
preserved. A cold-import regression forces system-font commands to fail: the old
entry point fails and the updated entry point loads real bundled fonts. The
precise blocked frame on the Intel runner remains unconfirmed.

GUI verification now records its stage/result through the existing `save_design`
bridge, with a per-launch token in a bounded design name. The harness reads
committed names from its temporary database in read-only mode. Browser feature
checks and the real design preview still precede success. The extra cross-origin
HTTP callback server, sockets and report threads were removed. This eliminates
that auxiliary reporting dependency; the attachment did not include a captured
WebKit network error. Malformed, uncommitted or wrong-token records cannot pass,
and database waits remain bounded. Obsolete HTTP-server tests were replaced by
real bridge-save and SQLite isolation/timeout checks. Bundle command timeouts now
retain partial output and existing progress/runtime/error metadata before cleanup.
The 60-second checks and 90-second GUI caller limit remain unchanged.

Validation on Linux:

- Backend suite: 210 tests in 114.306 s; 206 passed and four Windows Tk GUI tests
  skipped. Ruff lint/format and diff checks passed.
- A newly built wheel passed fresh installation, native GeoTIFF/NetCDF4 I/O,
  spawned flight/history, actual Qt browser/bridge/save verification, and an
  identical offline sdist rebuild.
- A newly built full Linux executable passed frozen preview/flights, compressed
  NetCDF4 weather, history, saved designs, OpenRocket import, CSV export and
  cancellation/reaping, followed by actual native GUI/browser/bridge/save checks.
- The probe JavaScript passed Node VM assertions for success, a missing secure
  context, and long errors containing JSON escape characters; all report names
  remained within the 128-character schema limit.

Actual macOS Cocoa/frozen-worker and Windows native reruns are still required.
These local results do not certify their execution or establish the exact Intel
Mac timeout cause.

## Mac loopback DNS startup follow-up (2026-10-29)

The latest user-supplied arm64/x64 logs at `973a44e` show the report thread in
`select()` and the main thread in `Queue.get()`. These are normal waiting frames,
not evidence of the previously suspected callback deadlock. No JavaScript report
arrived before the outer 90-second limit, which also hid the child's temporary
log.

Tracing both servers found a separate startup dependency on reverse DNS:
`HTTPServer.server_bind()` calls `socket.getfqdn()` after binding but before
listening. The harness did this before starting its inner 60-second deadline.
pywebview 6.2.1's asynchronous WSGI server also takes this path, returning a URL
before it is listening. A slow lookup can therefore both consume the caller's
time budget and cause WKWebView's first navigation to fail. This matches a
[reported macOS 15+ runner resolver problem](https://github.com/actions/setup-python/issues/1223),
where loopback lookups take over 30 seconds. The supplied logs do not contain
the actual Mac child stack, so this matching cause still requires a native Mac
rerun for confirmation.

The callback server now uses `ThreadingTCPServer` with the existing HTTP request
handler, avoiding reverse DNS entirely. On Mac, `prepare_desktop_runtime()`
substitutes a WSGI server that binds numeric loopback addresses without DNS and
sets the same WSGI environment; non-loopback binds retain stdlib behavior.
Bottle asset routing and bridge endpoints remain in place. This setup runs for
both wheel and frozen launches. The harness's deadline now includes setup, and
native child/debug output streams during the wait. The 60/90-second limits were
not increased. CI builds and checks the native worker before GUI verification;
both GUI checks remain mandatory for publication.

Before the fix, forcing `getfqdn()` to raise reproduced failures in both server
startup paths. The new regression tests keep that failure enabled and verify a
real callback POST and real UTF-8 asset GET through pywebview's Bottle server,
including both frozen/unfrozen Mac runtime branches. The Linux backend suite
completed 208 tests in 91.817 s: 204 passed, four Windows Tk GUI tests skipped.
Ruff lint/format and diff checks passed. A newly built wheel passed fresh Linux
installation, native GeoTIFF/NetCDF4 I/O, spawned flight/history, real Qt GUI and
Python bridge preview, and identical offline sdist rebuilding. A separate real
Linux Qt launch also passed browser/bridge checks with the Mac server substitute
installed and every Python `getfqdn()` call forced to fail. These checks do not
constitute macOS Cocoa or Windows native execution.

## Socket-handle and supervision regression follow-up (2026-10-29)

Subsequent user-supplied logs for the changes in `492c147` exposed a Windows
regression: the harness passed a Windows SOCKET handle to CRT-fd-only
`os.get_inheritable()`. The socket now uses `socket.get_inheritable()`; the log
file retains the CRT descriptor check. A Windows-handle emulation regression
ensures the socket is never passed to the CRT API and startup reaches `Popen`.

Mac now printed a started PID, showing that process creation returned, but it
still hit the outer 90-second timeout without the inner shutdown message.
Investigation proved that `server.timeout` only bounds selector waits, leaving
the listener's `accept()` unbounded after stale readiness. A deterministic test
reproduces that gap; an actual listener timeout bounds it. HTTP dispatch now
runs in a daemon thread started only after the desktop launch, so blocked
callback handling cannot hold the main queue/deadline supervisor. Stop-event
cleanup and a one-second join avoid unbounded server shutdown waits. The
20-second stack watchdog stays armed throughout the run instead of being
cancelled immediately after process creation. Actual Mac blocked frames have
not yet been captured, so this is not a claim that its GUI failure is resolved.

The six existing harness regressions and three new portability/fault-injection
checks passed locally. New cases cover Windows socket-handle separation, stale
selector readiness, and stuck callback handling that must still fail promptly
and stop the desktop child. Fresh Linux wheel installation, native I/O, spawned
flight/history, real GUI/bridge and offline sdist rebuild passed. The Darwin
launch branch also passed with a real Linux Qt executable; it did not run on a
Mac kernel. Windows/Mac native CI must be rerun before claiming success.

## Mac process-creation follow-up (2026-10-29)

[Run 40880198457](https://github.com/amuileum07/UARC/actions/runs/40880198457)
at `5b8fd19575f983c455ca9f5d23137c494d3c2fd7` passed the complete Windows and
Linux native jobs. Both Mac jobs still stopped after `GUI launching`, without
the inner 60-second loop's shutdown message, and hit the outer 90-second limit.
Thus the previous callback-server fix did not resolve the Mac CI failure.

The log localizes the new investigation to process creation before the GUI
deadline begins. [CPython 3.13.5's spawn gate](https://github.com/python/cpython/blob/v3.13.5/Lib/subprocess.py#L1681)
shows that the previous `cwd=root` option forced a fork/exec path on macOS after
the report server thread started. A specific native deadlock is still an
inference, since the old job did not capture a parent stack.

The harness now uses the same absolute launcher through `posix_spawn` on Darwin,
temporarily changes its own cwd before launch, and preserves non-inheritable
listener/log descriptors. It services the threaded report server from the main
poll loop after launch, removing the pre-launch server thread and shutdown wait.
It prints a started PID and dumps the parent stack after 20 seconds if process
creation stalls. The actual browser checks and 60/90-second deadlines remain.

Validation: all six GUI-harness regression tests passed, including a real
executable/shebang invocation that verifies the public `os.posix_spawn` call,
cwd restoration on success/failure, and absence of a pre-launch server thread.
Ruff lint/format and diff checks passed. Fresh Linux wheel GUI/native-I/O/flight
and offline sdist-rebuild checks passed. The Darwin launch branch also opened a
real Linux Qt executable and completed browser/bridge checks. That branch check
ran on Linux, not macOS: a successful native Mac rerun is still required.

## Native GUI CI failure follow-up (2026-10-29)

The [failed 0.1.1 attempt](https://github.com/amuileum07/UARC/actions/runs/40876699094)
at `d41b06eb3d155ac135a8943022af055692d777dc` installed the wheel successfully
on all four runners, then failed verification. No release was published.

- Linux had already installed `libxcb-cursor0`; the generic Qt warning did not
  prove the cursor library was absent. The apt closure omitted the independent
  Qt dependency `libxcb-shape.so.0`. CI now installs `libxcb-shape0` and checks
  the platform plugin and WebEngine process with `ldd` before opening a window.
  The failed runner did not record loader details, so shape being its precise
  missing SONAME remains an inference pending a native rerun.
- Windows compared an unresolved `RUNNER~1` asset path with a resolved target.
  An actual installed-wheel probe through a symlink alias reproduced the same
  assertion on Linux. The original probe failed; resolving both asset paths
  passed while retaining file-existence and installation-origin checks.
- The Mac harness could block its single-threaded report server on a browser's
  preopened idle connection, including during shutdown. Four offline regression
  tests now cover idle connections, incomplete request bodies, preflight/invalid
  reports, and native failure-log preservation. Concurrent request handling and
  finite socket timeouts remove that reproduced hang. The old Mac log did not
  establish whether a separate renderer/JavaScript issue was also present; the
  new stage diagnostics will show it on rerun.

After the fixes, the full Linux backend suite passed 201 tests (four Windows UI
tests skipped) in 92.651 s; Ruff lint/format and diff checks passed. A fresh wheel
environment passed native I/O, spawned simulation/history, actual Qt GUI/bridge
preview, and identical offline sdist rebuild. The exact Linux workflow preflight
passed locally and correctly rejected simulated missing-library and `ldd` errors.
Windows and Mac native CI reruns are still required; these local checks do not
certify their GUI success.

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
