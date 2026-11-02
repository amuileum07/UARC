import { createRoot } from "react-dom/client";
import { useLayoutEffect } from "react";
import { DesignJson } from "../src/components/DesignJson";
import { desktopApi } from "../src/lib/bridge";
import {
  WorkspaceProvider,
  useWorkspace,
  useSimulation,
  useEnvironment,
  usePlayback,
} from "../src/workspace";

// A native browser probe, kept outside the shipping entry point. Run through
// Vite and --check-ui; its promise reports actual React renders, not DOM changes.
const renders = { design: 0, environment: 0, simulation: 0, playback: 0 };
let controls:
  | {
      design: ReturnType<typeof useWorkspace>;
      environment: ReturnType<typeof useEnvironment>;
      simulation: ReturnType<typeof useSimulation>;
      playback: ReturnType<typeof usePlayback>;
    }
  | undefined;
function DesignProbe() {
  useWorkspace();
  renders.design++;
  return null;
}
function EnvironmentProbe() {
  useEnvironment();
  renders.environment++;
  return null;
}
function SimulationProbe() {
  useSimulation();
  renders.simulation++;
  return null;
}
function PlaybackProbe() {
  usePlayback();
  renders.playback++;
  return null;
}
function Controls() {
  controls = {
    design: useWorkspace(),
    environment: useEnvironment(),
    simulation: useSimulation(),
    playback: usePlayback(),
  };
  return null;
}
function EarlyJsonInput() {
  useLayoutEffect(() => {
    // Input can arrive before the editor's initial passive effects have run.
    const editor = document.querySelector<HTMLTextAreaElement>("#design-json");
    if (!editor) throw Error("Missing JSON editor");
    const design = JSON.parse(editor.value);
    design.components.find(
      (part: { id: string }) => part.id === "payload",
    ).mass = 1.05;
    Object.getOwnPropertyDescriptor(
      HTMLTextAreaElement.prototype,
      "value",
    )?.set?.call(editor, JSON.stringify(design));
    editor.dispatchEvent(new Event("input", { bubbles: true }));
  }, []);
  return null;
}
const painted = async () => {
  await new Promise(requestAnimationFrame);
  await new Promise((resolve) => setTimeout(resolve, 0));
};
async function wait(read: () => boolean) {
  const deadline = performance.now() + 45_000;
  while (!read()) {
    if (performance.now() > deadline) throw Error("Workspace probe timed out");
    await painted();
  }
}
function current() {
  if (!controls) throw Error("Workspace controls not mounted");
  return controls;
}
function delta(before: typeof renders) {
  return {
    design: renders.design - before.design,
    environment: renders.environment - before.environment,
    simulation: renders.simulation - before.simulation,
    playback: renders.playback - before.playback,
  };
}
async function verify() {
  const api = await desktopApi();
  const [initial, schema] = await Promise.all([
    api.get_example_design(),
    api.get_config_schema("design"),
  ]);
  while (initial.components.length < 64) {
    initial.components.push({
      component_type: "mass",
      id: `probe-${initial.components.length}`,
      name: "Context probe mass",
      position: 0.1,
      mass: 0.001,
    });
  }
  const element = document.getElementById("root");
  if (!element) throw Error("Missing probe root");
  const root = createRoot(element);
  const listRuns = api.list_runs;
  const checkElevation = api.check_elevation;
  let elevationRequests = 0;
  api.check_elevation = async (...args) => {
    const request = ++elevationRequests;
    const value = await checkElevation(...args);
    // Keep the JSON replacement's elevation check in flight after its preview.
    // This exercises slow IPC without depending on the host browser's timing.
    if (request === 2) await new Promise((resolve) => setTimeout(resolve, 500));
    return value;
  };
  try {
    root.render(
      <WorkspaceProvider initial={initial} schema={schema}>
        <DesignProbe />
        <EnvironmentProbe />
        <SimulationProbe />
        <PlaybackProbe />
        <Controls />
        <DesignJson />
        <EarlyJsonInput />
      </WorkspaceProvider>,
    );
    await wait(
      () =>
        controls?.design.previewState === "ready" &&
        controls.design.preview?.design === controls.design.design &&
        !!controls.environment.elevation,
    );
    await painted();
    const editor = document.querySelector<HTMLTextAreaElement>("#design-json");
    if (
      !editor ||
      JSON.parse(editor.value).components.find(
        (part: { id: string }) => part.id === "payload",
      ).mass !== 1.05
    )
      throw Error("Initial effects erased JSON input");
    const previousElevation = current().environment.elevation;
    document.querySelector<HTMLButtonElement>(".json-panel button")?.click();
    await wait(() => {
      const workspace = current().design;
      const part = workspace.design.components.find(
        (part) => part.id === "payload",
      );
      return (
        part?.component_type === "mass" &&
        part.mass === 1.05 &&
        workspace.previewState === "ready" &&
        workspace.preview?.design === workspace.design &&
        // JSON replacement also starts a new elevation check. Exclude both
        // asynchronous completions from the playback-only render counters.
        !!current().environment.elevation &&
        current().environment.elevation !== previousElevation
      );
    });
    let before = { ...renders };
    for (let frame = 1; frame <= 60; frame++) {
      current().playback.setTime(frame / 60);
      await painted();
    }
    await wait(() => current().playback.time === 1);
    const playback = delta(before);
    if (
      playback.design ||
      playback.environment ||
      playback.simulation ||
      !playback.playback
    )
      throw Error(
        `Playback leaked into another context: ${JSON.stringify(playback)}`,
      );
    before = { ...renders };
    const payload = initial.components.findIndex(
      (part) => part.id === "payload",
    );
    if (payload < 0) throw Error("Missing payload fixture");
    for (let edit = 0; edit < 20; edit++) {
      current().design.edit(
        ["components", String(payload), "mass"],
        0.5 + edit / 100,
      );
      await painted();
    }
    await wait(() => {
      const workspace = current().design;
      const part = workspace.design.components[payload];
      return (
        workspace.previewState === "ready" &&
        workspace.preview?.design === workspace.design &&
        part.component_type === "mass" &&
        part.mass === 0.5 + 19 / 100
      );
    });
    const editing = delta(before);
    if (
      !editing.design ||
      editing.environment ||
      editing.simulation ||
      editing.playback
    )
      throw Error(
        `Design edits leaked into another context: ${JSON.stringify(editing)}`,
      );
    if (!current().environment.elevation)
      throw Error("A rocket edit erased launch-elevation verification");
    before = { ...renders };
    api.list_runs = async () => [
      {
        run_id: "a".repeat(32),
        state: "queued",
        stage: "queued",
        worker_pid: null,
        created_at: new Date().toISOString(),
        started_at: null,
        finished_at: null,
        peak_rss_bytes: 0,
        error: null,
      },
    ];
    window.dispatchEvent(new Event("uarc:history-changed"));
    await wait(() => current().simulation.runs.length === 1);
    const history = delta(before);
    if (
      history.design ||
      history.environment ||
      history.playback ||
      !history.simulation
    )
      throw Error(
        `History leaked into another context: ${JSON.stringify(history)}`,
      );
    return {
      ok: true,
      phase: "workspace",
      components: 64,
      json_input_preserved: true,
      elevation_checks: elevationRequests,
      playback,
      editing,
      history,
    };
  } finally {
    api.list_runs = listRuns;
    api.check_elevation = checkElevation;
    root.unmount();
  }
}
declare global {
  interface Window {
    __uarcWorkspaceCheck: Promise<unknown>;
  }
}
window.__uarcWorkspaceCheck = verify().catch((error: unknown) => ({
  ok: false,
  phase: "workspace",
  error: String(error),
}));
