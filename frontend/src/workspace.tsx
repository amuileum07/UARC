import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { ReactNode } from "react";
import {
  checkElevation,
  desktopApi,
  previewDesign,
  submitDesign,
} from "./lib/bridge";
import type { ElevationCheck } from "./lib/bridge";
import { previewQueue } from "./lib/preview";
import { editDesign, placeLaunchSite } from "./lib/edit";
import type { InputSchema } from "./lib/forms";
import { defaultTerrainRequest, terrainMatchesSite } from "./lib/terrain";
import { telemetryColumns } from "./lib/telemetry";
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

interface Workspace {
  schema: InputSchema;
  design: RocketDesign;
  preview: { design: RocketDesign; result: DesignPreview } | null;
  previewState: "pending" | "ready" | "invalid";
  selection: string;
  setSelection: (id: string) => void;
  edit: (path: string[], value: unknown) => void;
  replace: (design: RocketDesign, saved?: boolean) => void;
  dirty: boolean;
  problems: Record<string, string>;
  fieldIssue: (id: string, message: string) => void;
  act: (operation: () => Promise<void>) => Promise<void>;
  save: () => Promise<void>;
  run: () => Promise<void>;
  saved: SavedDesignRecord[];
  runs: RunRecord[];
  selectedRun: string;
  selectRun: (id: string) => void;
  result: {
    design: RocketDesign;
    summary: FlightSummary;
    telemetry: TelemetryResult;
  } | null;
  elevation: ElevationCheck | null;
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
const Context = createContext<Workspace | null>(null);
export function useWorkspace() {
  const value = useContext(Context);
  if (!value) throw new Error("Missing workspace");
  return value;
}
export function WorkspaceProvider({
  initial,
  schema,
  children,
}: {
  initial: RocketDesign;
  schema: InputSchema;
  children: ReactNode;
}) {
  const [design, setDesign] = useState(initial);
  const latest = useRef(design);
  latest.current = design;
  const [preview, setPreview] = useState<Workspace["preview"]>(null);
  const [previewState, setPreviewState] =
    useState<Workspace["previewState"]>("pending");
  const [selection, setSelection] = useState(initial.components[0].id);
  const [dirty, setDirty] = useState(false);
  const [problems, setProblems] = useState<Record<string, string>>({});
  const [saved, setSaved] = useState<SavedDesignRecord[]>([]);
  const [runs, setRuns] = useState<RunRecord[]>([]);
  const [selectedRun, setSelectedRun] = useState("");
  const [result, setResult] = useState<Workspace["result"]>(null);
  const [elevation, setElevation] = useState<ElevationCheck | null>(null);
  const [terrainBusy, setTerrainBusy] = useState(false);
  const [terrainArea, setTerrainArea] = useState({
    radius_m: 1000,
    spacing_m: 30,
  });
  const [terrainAutoBusy, setTerrainAutoBusy] = useState(false);
  const [terrainAutoError, setTerrainAutoError] = useState("");
  const [terrainSource, setTerrainSource] = useState<
    NonNullable<TerrainRequest["provider"]>
  >(
    initial.environment.terrain?.provider === "unknown"
      ? "local"
      : initial.environment.terrain?.provider || "aws",
  );
  const pendingTerrain = useRef(false);
  const [vworldKey, setVworldKey] = useState("");
  const [mapMode, setMapMode] = useState<"design" | "result">("design");
  const [pickingSite, setPickingSite] = useState(false);
  const [time, setTime] = useState(0);
  const pendingRun = useRef(false);
  const fieldIssue = useCallback(
    (key: string, message: string) =>
      setProblems((old) => {
        const next = { ...old };
        if (message) next[key] = message;
        else delete next[key];
        return next;
      }),
    [],
  );
  const act = useCallback(
    async (operation: () => Promise<void>) => {
      try {
        await operation();
        fieldIssue("action", "");
      } catch (error) {
        fieldIssue(
          "action",
          error instanceof Error ? error.message : String(error),
        );
      }
    },
    [fieldIssue],
  );
  const queue = useMemo(
    () =>
      previewQueue(
        async (input: RocketDesign) => ({
          design: input,
          result: await previewDesign(input),
        }),
        (value) => {
          setPreview(value);
          setPreviewState("ready");
          setProblems((old) => {
            const next = { ...old };
            delete next.preview;
            return next;
          });
        },
        (error) => {
          setPreviewState("invalid");
          setProblems((old) => ({ ...old, preview: String(error) }));
        },
      ),
    [],
  );
  useEffect(() => {
    queue.push(design);
    setPreviewState("pending");
    setElevation(null);
  }, [design, queue]);
  useEffect(() => () => queue.dispose(), [queue]);
  useEffect(() => {
    let active = true;
    void checkElevation(design.environment)
      .then((value) => {
        if (active) setElevation(value);
      })
      .catch((error) => {
        if (active)
          setElevation({
            status: "unverified",
            message: String(error),
            difference_m: null,
            ground_elevation_m: null,
          });
      });
    return () => {
      active = false;
    };
  }, [design.environment]);
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const api = await desktopApi();
        const [history, documents] = await Promise.all([
          api.list_runs(),
          api.list_designs(),
        ]);
        if (active) {
          setRuns(history);
          setSaved(documents);
        }
      } catch (error) {
        if (active) setProblems((old) => ({ ...old, history: String(error) }));
      }
      if (active) timer = setTimeout(poll, 1200);
    }
    void poll();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, []);
  const selectedState = runs.find((r) => r.run_id === selectedRun)?.state;
  useEffect(() => {
    setResult(null);
    if (!selectedRun || selectedState !== "succeeded") return;
    let active = true;
    void act(async () => {
      const api = await desktopApi();
      const [snapshot, summary, telemetry] = await Promise.all([
        api.get_design(selectedRun),
        api.get_summary(selectedRun),
        api.get_telemetry(
          selectedRun,
          JSON.stringify({
            columns: telemetryColumns,
            max_points: 2000,
          }),
        ),
      ]);
      if (active) {
        setResult({ design: snapshot, summary, telemetry });
        setTime(summary.start_time_s);
      }
    });
    return () => {
      active = false;
    };
  }, [selectedRun, selectedState, act]);
  const edit = (path: string[], value: unknown) => {
    setDesign((old) => editDesign(old, path, value));
    setDirty(true);
    if (path[0] === "environment") setMapMode("design");
  };
  const placeSite = useCallback((latitude: number, longitude: number) => {
    setDesign((old) => placeLaunchSite(old, latitude, longitude));
    setDirty(true);
    setMapMode("design");
    setPickingSite(false);
  }, []);
  const replace = (value: RocketDesign, saved = false) => {
    if (dirty && !window.confirm("저장하지 않은 편집 내용을 바꿀까요?")) return;
    autoTerrain.push(null);
    setTerrainSource(
      value.environment.terrain?.provider === "unknown"
        ? "local"
        : value.environment.terrain?.provider || "aws",
    );
    setDesign(value);
    setDirty(!saved);
    setSelection(value.components[0].id);
    setMapMode("design");
    setPickingSite(false);
  };
  const save = () =>
    act(async () => {
      if (Object.keys(problems).some((key) => key.startsWith("field:")))
        throw new Error("편집 중인 입력을 적용하거나 수정한 뒤 저장하세요.");
      const snapshot = design;
      await (await desktopApi()).save_design(JSON.stringify(snapshot));
      if (latest.current === snapshot) setDirty(false);
    });
  const run = () =>
    act(async () => {
      if (pendingRun.current) return;
      if (
        terrainBusy ||
        terrainAutoBusy ||
        (terrainSource === "aws" &&
          !terrainAutoError &&
          defaultTerrainRequest(
            design.environment,
            terrainArea.radius_m,
            terrainArea.spacing_m,
          ))
      )
        throw new Error(
          "계산용 지형을 가져오는 중입니다. 완료한 뒤 실행하세요.",
        );
      if (
        previewState !== "ready" ||
        Object.keys(problems).some((k) => k.startsWith("field:"))
      )
        throw new Error("입력과 미리보기를 먼저 확인해 주세요.");
      pendingRun.current = true;
      try {
        const record = await submitDesign(design);
        setRuns((old) => [record, ...old]);
        setSelectedRun(record.run_id);
        setMapMode("result");
      } finally {
        pendingRun.current = false;
      }
    });
  const loadTerrain: Workspace["loadTerrain"] = (options, local) =>
    act(async () => {
      if (pendingTerrain.current) return;
      autoTerrain.push(null);
      setTerrainAutoError("");
      const environment = latest.current.environment;
      if (environment.datum !== "WGS84")
        throw new Error(
          "지형 조회 전에 좌표 기준을 WGS84로 지정해 주세요. 기존 좌표는 자동 변환하지 않습니다.",
        );
      setTerrainBusy(true);
      pendingTerrain.current = true;
      try {
        const api = await desktopApi();
        const area = {
          ...options,
          latitude: environment.latitude,
          longitude: environment.longitude,
        };
        const grid = local
          ? await api.select_terrain_file(JSON.stringify({ ...local, area }))
          : await api.get_terrain(JSON.stringify(area));
        if (!grid) return;
        if (latest.current.environment !== environment)
          throw new Error(
            "조회 중 발사 환경이 변경되어 지형을 적용하지 않았습니다. 다시 가져오세요.",
          );
        setDesign((old) => ({
          ...old,
          environment: {
            ...old.environment,
            terrain: grid,
            terrain_mode: "terrain",
          },
        }));
        setMapMode("design");
        setDirty(true);
      } finally {
        pendingTerrain.current = false;
        setTerrainBusy(false);
      }
    });
  const autoTerrain = useMemo(
    () =>
      previewQueue(
        async (area: TerrainRequest | null) => {
          if (!area) return null;
          setTerrainAutoBusy(true);
          setTerrainAutoError("");
          try {
            return {
              area,
              grid: await (
                await desktopApi()
              ).get_terrain(JSON.stringify(area)),
            };
          } finally {
            setTerrainAutoBusy(false);
          }
        },
        (response) => {
          if (
            !response ||
            latest.current.environment.terrain ||
            !terrainMatchesSite(latest.current.environment, response.area)
          )
            return;
          setDesign((old) =>
            old.environment.terrain ||
            !terrainMatchesSite(old.environment, response.area)
              ? old
              : {
                  ...old,
                  environment: {
                    ...old.environment,
                    terrain: response.grid,
                    terrain_mode: "terrain",
                  },
                },
          );
          setDirty(true);
        },
        () =>
          setTerrainAutoError(
            "AWS 기본 지형을 가져오지 못했습니다. 네트워크를 확인하고 다시 가져오거나 다른 소스를 선택하세요.",
          ),
        600,
      ),
    [],
  );
  const { latitude, longitude, datum, terrain } = design.environment;
  useEffect(() => {
    setTerrainAutoError("");
    autoTerrain.push(
      terrainSource === "aws"
        ? defaultTerrainRequest(
            { latitude, longitude, datum, terrain },
            terrainArea.radius_m,
            terrainArea.spacing_m,
          )
        : null,
    );
  }, [
    autoTerrain,
    terrainSource,
    latitude,
    longitude,
    datum,
    terrain,
    terrainArea.radius_m,
    terrainArea.spacing_m,
  ]);
  useEffect(() => () => autoTerrain.dispose(), [autoTerrain]);
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (dirty) event.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  return (
    <Context
      value={{
        schema,
        design,
        preview,
        previewState,
        selection,
        setSelection,
        edit,
        replace,
        dirty,
        problems,
        fieldIssue,
        act,
        save,
        run,
        saved,
        runs,
        selectedRun,
        selectRun: (id) => {
          setSelectedRun(id);
          setMapMode("result");
        },
        result,
        elevation,
        terrainBusy: terrainBusy || terrainAutoBusy,
        terrainSource,
        setTerrainSource: (source) => {
          setTerrainSource(source);
          if (
            source === "aws" &&
            latest.current.environment.terrain &&
            latest.current.environment.terrain.provider !== "aws"
          )
            void loadTerrain({ provider: "aws", ...terrainArea });
        },
        terrainAutoError,
        terrainArea,
        setTerrainArea,
        loadTerrain,
        vworldKey,
        setVworldKey,
        mapMode,
        setMapMode,
        pickingSite,
        setPickingSite,
        placeSite,
        time,
        setTime,
      }}
    >
      {children}
    </Context>
  );
}
