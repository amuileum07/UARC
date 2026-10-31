import type {
  DesignPreview,
  DesignReport,
  EnvironmentConfig,
  FlightSummary,
  LocationResult,
  RocketDesign,
  RunRecord,
  SavedDesignRecord,
  TelemetryResult,
  TerrainGrid,
  WeatherProfile,
  WeatherTable,
  ImportedFile,
  OpenRocketImport,
} from "./types";
import type { InputSchema } from "./forms";
import type { MaterialCatalog } from "./materials";

export type JsonValue =
  | null
  | boolean
  | number
  | string
  | JsonValue[]
  | JsonObject;
export type JsonObject = { [key: string]: JsonValue };
export type ConfigKind =
  | "environment"
  | "motor"
  | "rocket"
  | "flight"
  | "simulation"
  | "design"
  | "openrocket_options";
export interface ElevationCheck {
  status: "ok" | "warning" | "unverified";
  message: string;
  ground_elevation_m: number | null;
  difference_m: number | null;
}
interface DesktopApi {
  report_frontend_error(input: string): Promise<boolean>;
  validate_config(kind: "design", input: string): Promise<RocketDesign>;
  validate_config(kind: ConfigKind, input: string): Promise<JsonObject>;
  get_example_design(): Promise<RocketDesign>;
  get_material_catalog(): Promise<MaterialCatalog>;
  open_material_reference(id: string): Promise<boolean>;
  import_design_file(): Promise<RocketDesign | null>;
  export_design_file(input: string): Promise<string | null>;
  get_config_schema(kind: ConfigKind): Promise<InputSchema>;
  preview_design(input: string): Promise<DesignPreview>;
  submit_design(input: string): Promise<RunRecord>;
  save_design(input: string): Promise<SavedDesignRecord>;
  list_designs(): Promise<SavedDesignRecord[]>;
  get_saved_design(id: string): Promise<RocketDesign>;
  get_design(id: string): Promise<RocketDesign>;
  get_design_report(id: string): Promise<DesignReport>;
  rerun(id: string): Promise<RunRecord>;
  list_runs(): Promise<RunRecord[]>;
  get_run(id: string): Promise<RunRecord>;
  cancel_run(id: string): Promise<RunRecord>;
  get_summary(id: string): Promise<FlightSummary>;
  get_telemetry(id: string, query: string): Promise<TelemetryResult>;
  get_terrain(input: string): Promise<TerrainGrid>;
  select_terrain_file(input: string): Promise<TerrainGrid | null>;
  open_terrain_portal(
    provider: "aws" | "local" | "opentopography" | "vworld",
  ): Promise<boolean>;
  check_elevation(input: string): Promise<ElevationCheck>;
  search_locations(input: string): Promise<LocationResult[]>;
  get_weather(input: string): Promise<WeatherProfile>;
  select_input_file(): Promise<ImportedFile | null>;
  preview_weather_file(
    path: string,
    sheet?: string | null,
  ): Promise<WeatherTable>;
  import_weather_file(path: string, options: string): Promise<WeatherProfile>;
  import_openrocket(path: string, options: string): Promise<OpenRocketImport>;
  export_csv(id: string): Promise<string | null>;
}
declare global {
  interface Window {
    pywebview?: { api: DesktopApi };
    CESIUM_BASE_URL?: string;
  }
}

export function desktopApi(): Promise<DesktopApi> {
  // pywebview may publish an empty API object before registering its methods.
  if (window.pywebview?.api && Object.keys(window.pywebview.api).length)
    return Promise.resolve(window.pywebview.api);
  return new Promise((resolve, reject) => {
    const ready = () => {
      if (!window.pywebview?.api || !Object.keys(window.pywebview.api).length)
        return;
      clearTimeout(timeout);
      window.removeEventListener("pywebviewready", ready);
      resolve(window.pywebview.api);
    };
    const timeout = setTimeout(() => {
      window.removeEventListener("pywebviewready", ready);
      reject(
        new Error(
          "Open the app in its UARC desktop window to use Python features.",
        ),
      );
    }, 10_000);
    window.addEventListener("pywebviewready", ready);
    ready();
  });
}
export async function validateConfig(kind: ConfigKind, input: JsonObject) {
  return (await desktopApi()).validate_config(kind, JSON.stringify(input));
}
export async function previewDesign(input: RocketDesign) {
  return (await desktopApi()).preview_design(JSON.stringify(input));
}
export async function submitDesign(input: RocketDesign) {
  return (await desktopApi()).submit_design(JSON.stringify(input));
}
export async function getDesign(id: string) {
  return (await desktopApi()).get_design(id);
}
export async function getDesignReport(id: string) {
  return (await desktopApi()).get_design_report(id);
}
export async function rerunSimulation(id: string) {
  return (await desktopApi()).rerun(id);
}
export async function checkElevation(input: EnvironmentConfig) {
  return (await desktopApi()).check_elevation(JSON.stringify(input));
}
