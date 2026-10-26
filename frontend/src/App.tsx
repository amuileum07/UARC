import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { DockviewReact, themeLight } from "dockview-react";
import type { DockviewApi, DockviewReadyEvent } from "dockview-react";
import { desktopApi } from "./lib/bridge";
import type { RocketDesign } from "./lib/types";
import { WorkspaceProvider, useWorkspace } from "./workspace";
import { Explorer, Properties } from "./features/rocket/Editor";
import { RocketView } from "./features/rocket/RocketView";
import { EnvironmentEditor } from "./features/environment/Environment";
const TerrainMap = lazy(() =>
  import("./features/environment/TerrainMap").then((module) => ({
    default: module.TerrainMap,
  })),
);
function MapPanel() {
  return (
    <Suspense fallback={<p className="empty">지도 엔진을 불러오는 중…</p>}>
      <TerrainMap />
    </Suspense>
  );
}
import { Jobs, Results } from "./features/results/Results";
import { DesignJson } from "./components/DesignJson";

const panels = {
  explorer: Explorer,
  properties: Properties,
  rocket: RocketView,
  environment: EnvironmentEditor,
  map: MapPanel,
  jobs: Jobs,
  results: Results,
  json: DesignJson,
};
const titles = {
  explorer: "프로젝트",
  properties: "속성",
  rocket: "로켓 설계",
  environment: "발사 환경",
  map: "지형 · 궤적",
  jobs: "작업 · 문제",
  results: "비행 결과",
  json: "설계 JSON",
};
function defaultLayout(api: DockviewApi) {
  api.clear();
  api.addPanel({ id: "rocket", component: "rocket", title: titles.rocket });
  for (const id of ["map", "results", "json"] as const)
    api.addPanel({
      id,
      component: id,
      title: titles[id],
      position: { referencePanel: "rocket" },
    });
  api.addPanel({
    id: "explorer",
    component: "explorer",
    title: titles.explorer,
    initialWidth: 230,
    position: { referencePanel: "rocket", direction: "left" },
  });
  api.addPanel({
    id: "properties",
    component: "properties",
    title: titles.properties,
    initialWidth: 285,
    position: { referencePanel: "rocket", direction: "right" },
  });
  api.addPanel({
    id: "environment",
    component: "environment",
    title: titles.environment,
    position: { referencePanel: "properties" },
  });
  api.addPanel({
    id: "jobs",
    component: "jobs",
    title: titles.jobs,
    initialHeight: 180,
    position: { referencePanel: "rocket", direction: "below" },
  });
  api.getPanel("rocket")?.api.setActive();
  api.getPanel("properties")?.api.setActive();
}
function Workspace() {
  const w = useWorkspace();
  const api = useRef<DockviewApi | null>(null);
  const subscription = useRef<{ dispose: () => void } | null>(null);
  const [layoutIssue, setLayoutIssue] = useState("");
  const ready = ({ api: dock }: DockviewReadyEvent) => {
    api.current = dock;
    let restored = false;
    try {
      const saved = localStorage.getItem("uarc-layout-v1");
      if (saved) {
        dock.fromJSON(JSON.parse(saved));
        restored = true;
      }
    } catch {
      setLayoutIssue("배치를 복원하지 못해 기본 배치를 사용합니다.");
    }
    if (!restored) defaultLayout(dock);
    subscription.current = dock.onDidLayoutChange(() => {
      try {
        localStorage.setItem("uarc-layout-v1", JSON.stringify(dock.toJSON()));
      } catch {
        setLayoutIssue("배치를 저장할 수 없습니다.");
      }
    });
  };
  useEffect(() => () => subscription.current?.dispose(), []);
  const open = (id: keyof typeof panels) => {
    const current = api.current;
    if (!current) return;
    const panel =
      current.getPanel(id) ||
      current.addPanel({ id, component: id, title: titles[id] });
    panel.api.setActive();
  };
  const actions = useRef({ save: w.save, run: w.run });
  actions.current = { save: w.save, run: w.run };
  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        void actions.current.save();
      }
      if (event.key === "F5") {
        event.preventDefault();
        void actions.current.run();
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, []);
  return (
    <div className="app">
      <header className="app-header">
        <div className="brand">UARC</div>
        <div className="project-title">
          {w.design.name}
          {w.dirty ? " · 수정됨" : ""}
        </div>
        <button type="button" onClick={() => void w.save()} title="Ctrl+S">
          저장
        </button>
        <button
          type="button"
          className="primary"
          disabled={
            w.previewState !== "ready" ||
            Object.keys(w.problems).some((k) => k.startsWith("field:"))
          }
          onClick={() => void w.run()}
          title="F5"
        >
          ↗ 시뮬레이션 실행
        </button>
      </header>
      <nav className="app-nav" aria-label="작업 공간">
        <button type="button" onClick={() => open("rocket")}>
          설계
        </button>
        <button
          type="button"
          onClick={() => {
            open("environment");
            open("map");
          }}
        >
          발사장
        </button>
        <button type="button" onClick={() => open("results")}>
          분석
        </button>
        <details className="view-menu">
          <summary>보기</summary>
          <div>
            {(Object.keys(panels) as Array<keyof typeof panels>).map((id) => (
              <button type="button" key={id} onClick={() => open(id)}>
                {titles[id]}
              </button>
            ))}
          </div>
        </details>
        <button
          type="button"
          onClick={() => {
            if (api.current) defaultLayout(api.current);
          }}
        >
          배치 초기화
        </button>
      </nav>
      <main className="dock-host">
        <DockviewReact
          components={panels}
          onReady={ready}
          theme={themeLight}
          getTabContextMenuItems={() => [
            "close",
            "closeOthers",
            "separator",
            "maximize",
          ]}
        />
      </main>
      <footer className="statusbar">
        <span>SI · m / kg / s</span>
        <span>기체 좌표: tail → nose</span>
        <span>
          {w.design.environment.terrain_mode === "terrain"
            ? "지형 지면"
            : "평면 지면"}
        </span>
        <span aria-live="polite">
          {layoutIssue ||
            (w.previewState === "ready"
              ? "설계 검증됨"
              : w.previewState === "pending"
                ? "미리보기 계산 중"
                : "입력 오류 확인")}
        </span>
        <span>
          {w.runs.filter((r) => r.state === "running").length} 실행 중
        </span>
      </footer>
    </div>
  );
}
export function App() {
  const [initial, setInitial] = useState<RocketDesign | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    void desktopApi()
      .then((api) => api.get_example_design())
      .then((design) => {
        if (active) setInitial(design);
      })
      .catch((reason) => {
        if (active) setError(String(reason));
      });
    return () => {
      active = false;
    };
  }, []);
  if (!initial)
    return (
      <main className="startup">
        <div className="brand">UARC</div>
        <h1>Rocket workspace</h1>
        <p role="status">{error || "Python 계산 엔진에 연결하고 있습니다…"}</p>
        {error && (
          <p>
            UARC 데스크톱 앱에서 실행하세요:{" "}
            <code>uv run uarc --dev-url http://localhost:5173</code>
          </p>
        )}
      </main>
    );
  return (
    <WorkspaceProvider initial={initial}>
      <Workspace />
    </WorkspaceProvider>
  );
}
