import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import {
  checkElevation,
  desktopApi,
  previewDesign,
  submitDesign,
} from "./lib/bridge";
import type { ElevationCheck } from "./lib/bridge";
import { previewQueue } from "./lib/preview";
import { watchHistory } from "./lib/history";
import {
  componentRemovalIssue,
  editDesign,
  placeLaunchSite,
  removeDesignComponent,
} from "./lib/edit";
import type { InputSchema } from "./lib/forms";
import {
  defaultTerrainRequest,
  terrainMatchesSite,
  launchElevationIssue,
} from "./lib/terrain";
import { telemetryColumns } from "./lib/telemetry";
import { automaticWeatherRequest, applyAutomaticWeather } from "./lib/weather";
import type {
  RocketDesign,
  RunRecord,
  SavedDesignRecord,
  TerrainRequest,
  WeatherRequest,
} from "./lib/types";

import {
  ActionsContext,
  DesignContext,
  EnvironmentContext,
  SimulationContext,
  PlaybackProvider,
} from "./workspaceContexts";
import type { Workspace } from "./workspaceContexts";
export {
  useWorkspace,
  useWorkspaceActions,
  useSimulation,
  useEnvironment,
  usePlayback,
} from "./workspaceContexts";

export function WorkspaceProvider({
  initial,
  schema,
  children,
}: {
  initial: RocketDesign;
  schema: InputSchema;
  children: ReactNode;
}) {
  const [design, setDesign] = useState(() =>
    editDesign(initial, ["environment"], initial.environment),
  );
  const latest = useRef(design);
  latest.current = design;
  const elevationIssue = launchElevationIssue(design.environment);
  const [preview, setPreview] = useState<Workspace["preview"]>(null);
  const [previewState, setPreviewState] =
    useState<Workspace["previewState"]>("pending");
  const [selection, setSelectedComponent] = useState(initial.components[0].id);
  const [propertiesView, setPropertiesView] = useState(0);
  const setSelection = useCallback((id: string) => {
    setSelectedComponent(id);
    // Re-selecting the same component must also reveal its properties tab.
    setPropertiesView((value) => value + 1);
  }, []);
  const [dirty, setDirty] = useState(false);
  const [problems, setProblems] = useState<Record<string, string>>({});
  const [saved, setSaved] = useState<SavedDesignRecord[]>([]);
  const [runs, setRuns] = useState<RunRecord[]>([]);
  const [selectedRun, setSelectedRun] = useState("");
  const [resultView, setResultView] = useState(0);
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
  const pendingRun = useRef(false);
  const fieldIssue = useCallback(
    (key: string, message: string) =>
      setProblems((old) => {
        if ((old[key] || "") === message) return old;
        const next = { ...old };
        if (message) next[key] = message;
        else delete next[key];
        return next;
      }),
    [],
  );
  const act = useCallback(
    async (operation: () => Promise<void>, problem = "action") => {
      fieldIssue(problem, "");
      try {
        await operation();
      } catch (error) {
        fieldIssue(
          problem,
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
          fieldIssue("preview", "");
        },
        (error) => {
          setPreviewState("invalid");
          fieldIssue("preview", String(error));
        },
      ),
    [fieldIssue],
  );
  useEffect(() => {
    queue.push(design);
    setPreviewState("pending");
  }, [design, queue]);
  useEffect(() => () => queue.dispose(), [queue]);
  useEffect(() => {
    let active = true;
    setElevation(null);
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
  useEffect(
    () =>
      watchHistory(
        (history, documents) => {
          // Both IPC lists are capped at 50 flat metadata records.
          setRuns((old) =>
            JSON.stringify(old) === JSON.stringify(history) ? old : history,
          );
          setSaved((old) =>
            JSON.stringify(old) === JSON.stringify(documents) ? old : documents,
          );
          fieldIssue("history", "");
        },
        (error) => fieldIssue("history", String(error)),
      ),
    [fieldIssue],
  );
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
        setResult({ runId: selectedRun, design: snapshot, summary, telemetry });
      }
    });
    return () => {
      active = false;
    };
  }, [selectedRun, selectedState, act]);
  const selectRun = useCallback((id: string) => {
    setSelectedRun(id);
    setMapMode("result");
    setPickingSite(false);
    setResultView((value) => value + 1);
  }, []);
  const edit = useCallback((path: string[], value: unknown) => {
    setDesign((old) => editDesign(old, path, value));
    setDirty(true);
    if (path[0] === "environment") setMapMode("design");
  }, []);
  const removeComponent = useCallback(
    (id: string) => {
      const current = latest.current;
      const issue = componentRemovalIssue(current, id);
      if (issue) {
        fieldIssue("action", issue);
        return;
      }
      const index = current.components.findIndex(
        (component) => component.id === id,
      );
      const remaining = current.components.filter(
        (component) => component.id !== id,
      );
      setDesign((old) => removeDesignComponent(old, id));
      setSelection(remaining[Math.min(index, remaining.length - 1)].id);
      setDirty(true);
      fieldIssue("action", "");
    },
    [fieldIssue, setSelection],
  );
  const placeSite = useCallback((latitude: number, longitude: number) => {
    setDesign((old) => placeLaunchSite(old, latitude, longitude));
    setDirty(true);
    setMapMode("design");
    setPickingSite(false);
  }, []);
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
              : editDesign(old, ["environment"], {
                  ...old.environment,
                  terrain: response.grid,
                  terrain_mode: "terrain",
                }),
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
  const autoWeather = useMemo(
    () =>
      previewQueue(
        async (request: WeatherRequest | null) => {
          if (!request) return null;
          return {
            request,
            profile: await (
              await desktopApi()
            ).get_weather(JSON.stringify(request)),
          };
        },
        (response) => {
          if (!response) return;
          const current = latest.current;
          if (
            applyAutomaticWeather(
              current,
              response.request,
              response.profile,
            ) === current
          )
            return;
          setDesign((old) =>
            applyAutomaticWeather(old, response.request, response.profile),
          );
          setDirty(true);
          fieldIssue("weather", "");
        },
        (error) =>
          fieldIssue(
            "weather",
            `기상 자동 갱신 실패: ${error instanceof Error ? error.message : String(error)} 시각 · 기상에서 다시 가져오세요.`,
          ),
        600,
      ),
    [fieldIssue],
  );
  const weatherQuery = JSON.stringify(
    automaticWeatherRequest(design.environment),
  );
  useEffect(() => {
    fieldIssue("weather", "");
    autoWeather.push(JSON.parse(weatherQuery));
  }, [autoWeather, weatherQuery, fieldIssue]);
  useEffect(() => () => autoWeather.dispose(), [autoWeather]);
  const replace = useCallback(
    (value: RocketDesign, saved = false) => {
      if (dirty && !window.confirm("저장하지 않은 편집 내용을 바꿀까요?"))
        return;
      autoTerrain.push(null);
      autoWeather.push(null);
      setTerrainSource(
        value.environment.terrain?.provider === "unknown"
          ? "local"
          : value.environment.terrain?.provider || "aws",
      );
      const normalized = editDesign(value, ["environment"], value.environment);
      setDesign(normalized);
      setDirty(!saved || normalized.environment !== value.environment);
      setSelection(value.components[0].id);
      setMapMode("design");
      setPickingSite(false);
    },
    [dirty, autoTerrain, autoWeather, setSelection],
  );
  const save = useCallback(
    () =>
      act(async () => {
        if (Object.keys(problems).some((key) => key.startsWith("field:")))
          throw new Error("편집 중인 입력을 적용하거나 수정한 뒤 저장하세요.");
        const snapshot = design;
        await (await desktopApi()).save_design(JSON.stringify(snapshot));
        if (latest.current === snapshot) setDirty(false);
      }),
    [act, design, problems],
  );
  const run = useCallback(
    () =>
      act(async () => {
        if (pendingRun.current) return;
        if (elevationIssue) throw new Error(terrainAutoError || elevationIssue);
        if (automaticWeatherRequest(design.environment))
          throw new Error(
            problems.weather ||
              "기상 자료를 자동 갱신 중입니다. 완료한 뒤 실행하세요.",
          );
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
          selectRun(record.run_id);
        } finally {
          pendingRun.current = false;
        }
      }),
    [
      act,
      elevationIssue,
      terrainAutoError,
      design,
      problems,
      terrainBusy,
      terrainAutoBusy,
      terrainSource,
      terrainArea,
      previewState,
      selectRun,
    ],
  );
  const loadTerrain: Workspace["loadTerrain"] = useCallback(
    (options, local) =>
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
          setDesign((old) =>
            editDesign(old, ["environment"], {
              ...old.environment,
              terrain: grid,
              terrain_mode: "terrain",
            }),
          );
          setMapMode("design");
          setDirty(true);
        } finally {
          pendingTerrain.current = false;
          setTerrainBusy(false);
        }
      }, "terrain"),
    [act, autoTerrain],
  );
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (dirty) event.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  const changeTerrainSource = useCallback(
    (source: NonNullable<TerrainRequest["provider"]>) => {
      setTerrainSource(source);
      if (
        source === "aws" &&
        latest.current.environment.terrain &&
        latest.current.environment.terrain.provider !== "aws"
      )
        void loadTerrain({ provider: "aws", ...terrainArea });
    },
    [loadTerrain, terrainArea],
  );
  const selectedResult =
    result?.runId === selectedRun && selectedState === "succeeded"
      ? result
      : null;
  const simulation = useMemo(
    () => ({
      runs,
      selectedRun,
      selectedRunState: selectedState,
      resultView,
      selectRun,
      result: selectedResult,
    }),
    [runs, selectedRun, selectedState, resultView, selectRun, selectedResult],
  );
  const actions = useMemo(
    () => ({ act, fieldIssue, replace, problems }),
    [act, fieldIssue, replace, problems],
  );
  const designWorkspace = useMemo(
    () => ({
      schema,
      design,
      preview,
      previewState,
      selection,
      propertiesView,
      setSelection,
      edit,
      removeComponent,
      replace,
      dirty,
      problems,
      fieldIssue,
      act,
      save,
      run,
      saved,
    }),
    [
      schema,
      design,
      preview,
      previewState,
      selection,
      propertiesView,
      setSelection,
      edit,
      removeComponent,
      replace,
      dirty,
      problems,
      fieldIssue,
      act,
      save,
      run,
      saved,
    ],
  );
  const weatherBusy = weatherQuery !== "null" && !problems.weather;
  const weatherProblem = problems.weather || "";
  const terrainProblem = problems.terrain || "";
  const environment = useMemo(
    () => ({
      environment: design.environment,
      act,
      edit,
      elevation,
      elevationIssue,
      weatherBusy,
      weatherProblem,
      terrainProblem,
      terrainBusy: terrainBusy || terrainAutoBusy,
      terrainSource,
      setTerrainSource: changeTerrainSource,
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
    }),
    [
      design.environment,
      act,
      edit,
      elevation,
      elevationIssue,
      weatherBusy,
      weatherProblem,
      terrainProblem,
      terrainBusy,
      terrainAutoBusy,
      terrainSource,
      changeTerrainSource,
      terrainAutoError,
      terrainArea,
      loadTerrain,
      vworldKey,
      mapMode,
      pickingSite,
      placeSite,
    ],
  );
  return (
    <ActionsContext value={actions}>
      <DesignContext value={designWorkspace}>
        <EnvironmentContext value={environment}>
          <SimulationContext value={simulation}>
            <PlaybackProvider>{children}</PlaybackProvider>
          </SimulationContext>
        </EnvironmentContext>
      </DesignContext>
    </ActionsContext>
  );
}
