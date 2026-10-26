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
import { editDesign } from "./lib/edit";
import type {
  DesignPreview,
  FlightSummary,
  RocketDesign,
  RunRecord,
  SavedDesignRecord,
  TelemetryResult,
} from "./lib/types";

interface Workspace {
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
  loadTerrain: () => Promise<void>;
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
  children,
}: {
  initial: RocketDesign;
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
            columns: [
              "time_s",
              "x_m",
              "y_m",
              "z_asl_m",
              "vx_m_s",
              "vy_m_s",
              "vz_m_s",
            ],
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
  };
  const replace = (value: RocketDesign, saved = false) => {
    if (dirty && !window.confirm("저장하지 않은 편집 내용을 바꿀까요?")) return;
    setDesign(value);
    setDirty(!saved);
    setSelection(value.components[0].id);
  };
  const save = () =>
    act(async () => {
      const snapshot = design;
      await (await desktopApi()).save_design(JSON.stringify(snapshot));
      if (latest.current === snapshot) setDirty(false);
    });
  const run = () =>
    act(async () => {
      if (pendingRun.current) return;
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
      } finally {
        pendingRun.current = false;
      }
    });
  const loadTerrain = () =>
    act(async () => {
      if (terrainBusy) return;
      const environment = design.environment;
      if (environment.datum !== "WGS84")
        throw new Error(
          "지형 조회 전에 좌표 기준을 WGS84로 지정해 주세요. 기존 좌표는 자동 변환하지 않습니다.",
        );
      setTerrainBusy(true);
      try {
        const grid = await (
          await desktopApi()
        ).get_terrain(
          JSON.stringify({
            latitude: environment.latitude,
            longitude: environment.longitude,
            radius_m: 1000,
          }),
        );
        const current = latest.current.environment;
        if (
          current.latitude === environment.latitude &&
          current.longitude === environment.longitude &&
          current.datum === environment.datum
        ) {
          setDesign((old) => ({
            ...old,
            environment: { ...old.environment, terrain: grid },
          }));
          setDirty(true);
        }
      } finally {
        setTerrainBusy(false);
      }
    });
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
        selectRun: setSelectedRun,
        result,
        elevation,
        terrainBusy,
        loadTerrain,
        time,
        setTime,
      }}
    >
      {children}
    </Context>
  );
}
