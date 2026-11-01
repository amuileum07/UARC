import { createContext, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import type { ElevationCheck } from "./lib/bridge";
import type { InputSchema } from "./lib/forms";
import type {
  DesignPreview,
  FlightSummary,
  RocketDesign,
  RunRecord,
  SavedDesignRecord,
  TelemetryResult,
  TerrainRequest,
  TerrainImportOptions,
} from "./lib/types";

export interface Workspace {
  schema: InputSchema;
  design: RocketDesign;
  preview: { design: RocketDesign; result: DesignPreview } | null;
  previewState: "pending" | "ready" | "invalid";
  selection: string;
  propertiesView: number;
  geometryField: string[] | null;
  setGeometryField: (path: string[] | null) => void;
  setSelection: (id: string) => void;
  edit: (path: string[], value: unknown) => void;
  removeComponent: (id: string) => void;
  replace: (design: RocketDesign, saved?: boolean) => void;
  dirty: boolean;
  problems: Record<string, string>;
  fieldIssue: (id: string, message: string) => void;
  act: (operation: () => Promise<void>, problem?: string) => Promise<void>;
  save: () => Promise<void>;
  run: () => Promise<void>;
  saved: SavedDesignRecord[];
  runs: RunRecord[];
  selectedRun: string;
  selectedRunState: RunRecord["state"] | undefined;
  resultView: number;
  selectRun: (id: string) => void;
  result: {
    runId: string;
    design: RocketDesign;
    summary: FlightSummary;
    telemetry: TelemetryResult;
  } | null;
  elevation: ElevationCheck | null;
  elevationIssue: string;
  weatherBusy: boolean;
  terrainBusy: boolean;
  terrainSource: NonNullable<TerrainRequest["provider"]>;
  setTerrainSource: (source: NonNullable<TerrainRequest["provider"]>) => void;
  terrainAutoError: string;
  terrainArea: { radius_m: number; spacing_m: number };
  setTerrainArea: (area: { radius_m: number; spacing_m: number }) => void;
  loadTerrain: (
    options: Omit<TerrainRequest, "latitude" | "longitude">,
    local?: Omit<TerrainImportOptions, "area">,
  ) => Promise<void>;
  vworldKey: string;
  setVworldKey: (key: string) => void;
  mapMode: "design" | "result";
  setMapMode: (mode: "design" | "result") => void;
  pickingSite: boolean;
  setPickingSite: (picking: boolean) => void;
  placeSite: (latitude: number, longitude: number) => void;
  time: number;
  setTime: (time: number) => void;
}
type DesignWorkspace = Pick<
  Workspace,
  | "schema"
  | "design"
  | "preview"
  | "previewState"
  | "selection"
  | "propertiesView"
  | "geometryField"
  | "setGeometryField"
  | "setSelection"
  | "edit"
  | "removeComponent"
  | "replace"
  | "dirty"
  | "problems"
  | "fieldIssue"
  | "act"
  | "save"
  | "run"
  | "saved"
>;
type SimulationWorkspace = Pick<
  Workspace,
  | "runs"
  | "selectedRun"
  | "selectedRunState"
  | "resultView"
  | "selectRun"
  | "result"
>;
type EnvironmentWorkspace = Pick<
  Workspace,
  | "act"
  | "edit"
  | "elevation"
  | "elevationIssue"
  | "weatherBusy"
  | "terrainBusy"
  | "terrainSource"
  | "setTerrainSource"
  | "terrainAutoError"
  | "terrainArea"
  | "setTerrainArea"
  | "loadTerrain"
  | "vworldKey"
  | "setVworldKey"
  | "mapMode"
  | "setMapMode"
  | "pickingSite"
  | "setPickingSite"
  | "placeSite"
> & {
  environment: RocketDesign["environment"];
  weatherProblem: string;
  terrainProblem: string;
};
type WorkspaceActions = Pick<
  Workspace,
  "act" | "fieldIssue" | "replace" | "problems"
>;
export const DesignContext = createContext<DesignWorkspace | null>(null);
export const SimulationContext = createContext<SimulationWorkspace | null>(
  null,
);
export const EnvironmentContext = createContext<EnvironmentWorkspace | null>(
  null,
);
export const ActionsContext = createContext<WorkspaceActions | null>(null);
const PlaybackContext = createContext<Pick<
  Workspace,
  "time" | "setTime"
> | null>(null);
export function useWorkspace() {
  const value = useContext(DesignContext);
  if (!value) throw new Error("Missing design workspace");
  return value;
}
export function useSimulation() {
  const value = useContext(SimulationContext);
  if (!value) throw new Error("Missing simulation workspace");
  return value;
}
export function useEnvironment() {
  const value = useContext(EnvironmentContext);
  if (!value) throw new Error("Missing environment workspace");
  return value;
}
export function useWorkspaceActions() {
  const value = useContext(ActionsContext);
  if (!value) throw new Error("Missing workspace actions");
  return value;
}
export function usePlayback() {
  const value = useContext(PlaybackContext);
  if (!value) throw new Error("Missing playback workspace");
  return value;
}
export function PlaybackProvider({ children }: { children: ReactNode }) {
  const { result } = useSimulation();
  const [time, setTime] = useState(0);
  useEffect(() => setTime(result?.summary.start_time_s ?? 0), [result]);
  const value = useMemo(() => ({ time, setTime }), [time]);
  return <PlaybackContext value={value}>{children}</PlaybackContext>;
}
