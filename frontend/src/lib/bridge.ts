/** The desktop bridge accepts only JSON data, never Python runtime objects. */
export type JsonValue = null | boolean | number | string | JsonValue[] | JsonObject;
export type JsonObject = { [key: string]: JsonValue };
export type ConfigKind = "environment" | "motor" | "rocket" | "flight" | "simulation" | "design";

interface DesktopApi {
  validate_config(kind: ConfigKind, payloadJson: string): Promise<JsonObject>;
  preview_design(payloadJson: string): Promise<JsonObject>;
  submit_design(payloadJson: string): Promise<JsonObject>;
  get_design(runId: string): Promise<JsonObject>;
  get_design_report(runId: string): Promise<JsonObject>;
  rerun(runId: string): Promise<JsonObject>;
}

declare global {
  interface Window {
    pywebview?: { api: DesktopApi };
  }
}

function desktopApi(): Promise<DesktopApi> {
  if (window.pywebview?.api) return Promise.resolve(window.pywebview.api);

  return new Promise((resolve, reject) => {
    const ready = () => {
      if (!window.pywebview?.api) return;
      clearTimeout(timeout);
      window.removeEventListener("pywebviewready", ready);
      resolve(window.pywebview.api);
    };
    const timeout = setTimeout(() => {
      window.removeEventListener("pywebviewready", ready);
      reject(new Error("Open the app in its UARC desktop window to use Python features."));
    }, 10_000);
    window.addEventListener("pywebviewready", ready);
    ready();
  });
}

export async function validateConfig(kind: ConfigKind, input: JsonObject): Promise<JsonObject> {
  const api = await desktopApi();
  return api.validate_config(kind, JSON.stringify(input));
}

export async function previewDesign(input: JsonObject): Promise<JsonObject> {
  const api = await desktopApi();
  return api.preview_design(JSON.stringify(input));
}

export async function submitDesign(input: JsonObject): Promise<JsonObject> {
  const api = await desktopApi();
  return api.submit_design(JSON.stringify(input));
}

export async function getDesign(runId: string): Promise<JsonObject> {
  const api = await desktopApi();
  return api.get_design(runId);
}

export async function getDesignReport(runId: string): Promise<JsonObject> {
  const api = await desktopApi();
  return api.get_design_report(runId);
}

export async function rerunSimulation(runId: string): Promise<JsonObject> {
  const api = await desktopApi();
  return api.rerun(runId);
}
