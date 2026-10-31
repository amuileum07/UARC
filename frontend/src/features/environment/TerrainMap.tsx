import { useEffect, useMemo, useRef, useState } from "react";
import * as Cesium from "cesium";
import { desktopApi } from "../../lib/bridge";
import { reportFrontendError } from "../../lib/diagnostics";
import { flightPath, nearestTimeIndex } from "../../lib/geography";
import { runStateLabels } from "../../lib/telemetry";
import { webglContextAttributes } from "../../lib/webgl";
import { useWorkspace } from "../../workspace";
import { awsTerrainProvider } from "./awsTerrain";
import {
  frameMap,
  terrainBounds,
  terrainMaterial,
  terrainProvider,
  terrainWire,
} from "./mapTerrain";

export function TerrainMap() {
  const w = useWorkspace();
  const container = useRef<HTMLDivElement>(null);
  const viewer = useRef<Cesium.Viewer | null>(null);
  const marker = useRef<Cesium.Entity | null>(null);
  const [mode, setMode] = useState<"2D" | "3D">("3D");
  const [imagery, setImagery] = useState<"none" | "osm" | "vworld">("none");
  const [vworldDraft, setVworldDraft] = useState(w.vworldKey);
  const [renderError, setRenderError] = useState("");
  const [imageryError, setImageryError] = useState("");
  const [terrainError, setTerrainError] = useState("");
  const [streamError, setStreamError] = useState("");
  const [streamFallback, setStreamFallback] = useState(false);
  const [showGrid, setShowGrid] = useState(false);
  const [dataError, setDataError] = useState("");
  const [ready, setReady] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const result = w.mapMode === "result" ? w.result : null;
  const waiting = w.mapMode === "result" && !result;
  const env = result?.design.environment || w.design.environment;
  const grid = env.terrain;
  const streamAWS =
    grid?.provider === "aws" || (!grid && w.terrainSource === "aws");
  const hasTerrain = !!grid || streamAWS;
  const terrainOffset =
    grid && grid.reference !== "ellipsoid" ? (env.geoid_undulation_m ?? 0) : 0;
  const terrainShape = useMemo(
    () => (grid ? terrainBounds(grid, terrainOffset) : null),
    [grid, terrainOffset],
  );
  const terrainRange = terrainShape
    ? `${terrainShape.minimum.toFixed(0)}–${terrainShape.maximum.toFixed(0)} m`
    : "";
  const flightOffset =
    env.elevation_reference === "ellipsoid" ? 0 : (env.geoid_undulation_m ?? 0);
  const launch = useMemo(
    () =>
      Cesium.Cartesian3.fromDegrees(
        env.longitude,
        env.latitude,
        env.elevation + flightOffset,
      ),
    [env.longitude, env.latitude, env.elevation, flightOffset],
  );
  const meshLines = useMemo(
    () => (showGrid && grid ? terrainWire(grid, terrainOffset) : []),
    [grid, terrainOffset, showGrid],
  );
  const trajectory = useMemo(() => {
    try {
      const path = result
        ? flightPath(result.telemetry, result.design.environment)
        : [];
      const points = path.map(({ latitude, longitude, height }) =>
        Cesium.Cartesian3.fromDegrees(longitude, latitude, height),
      );
      return { points, times: path.map((point) => point.time), error: "" };
    } catch (reason) {
      return { points: [], times: [], error: String(reason) };
    }
  }, [result]);
  const sitePoints = useMemo(
    () => [launch, ...(terrainShape?.points ?? [])],
    [launch, terrainShape],
  );
  const allPoints = useMemo(
    () =>
      trajectory.points.length > 1
        ? [launch, ...trajectory.points]
        : sitePoints,
    [launch, sitePoints, trajectory],
  );
  const pendingFrame = useRef(true);
  const minimumRadius = trajectory.points.length > 1 ? 30 : 750;
  const framing = useRef({ mode, points: allPoints, minimumRadius });
  framing.current = { mode, points: allPoints, minimumRadius };
  const selectedPosition = useMemo(
    () => trajectory.points[nearestTimeIndex(trajectory.times, w.time)],
    [w.time, trajectory],
  );
  const latestPosition = useRef(selectedPosition);
  latestPosition.current = selectedPosition;
  useEffect(() => {
    if (w.mapMode === "result" && w.resultView > 0) setMode("3D");
  }, [w.mapMode, w.resultView]);
  // biome-ignore lint/correctness/useExhaustiveDependencies: attempt explicitly recreates the Cesium viewer after a render failure.
  useEffect(() => {
    if (!container.current) return;
    setReady(false);
    pendingFrame.current = true;
    setRenderError("");
    let current: Cesium.Viewer;
    try {
      // This viewer uses local terrain and OSM, not Cesium ion services.
      Cesium.CreditDisplay.cesiumCredit = new Cesium.Credit("");
      current = new Cesium.Viewer(container.current, {
        baseLayer: false,
        baseLayerPicker: false,
        geocoder: false,
        homeButton: false,
        sceneModePicker: false,
        navigationHelpButton: false,
        animation: false,
        timeline: false,
        fullscreenButton: false,
        infoBox: false,
        selectionIndicator: false,
        requestRenderMode: true,
        showRenderLoopErrors: false,
        contextOptions: { webgl: { ...webglContextAttributes } },
        // Cesium defaults to 4x MSAA even when the canvas disables antialiasing.
        msaaSamples: 1,
        maximumRenderTimeChange: Infinity,
        terrainProvider: new Cesium.EllipsoidTerrainProvider(),
      });
    } catch (reason) {
      container.current.replaceChildren();
      reportFrontendError("renderer", reason, "Cesium initialization");
      setRenderError(
        `지도를 시작할 수 없습니다: ${String(reason)}. 환경 패널의 좌표 입력은 계속 사용할 수 있습니다.`,
      );
      return;
    }
    current.scene.globe.baseColor = Cesium.Color.fromCssColorString("#dddddd");
    current.scene.backgroundColor = Cesium.Color.fromCssColorString("#f4f4f4");
    current.scene.canvas.dataset.msaaSamples = String(
      current.scene.msaaSamples,
    );
    current.scene.globe.depthTestAgainstTerrain = true;
    if (current.scene.skyAtmosphere) current.scene.skyAtmosphere.show = false;
    const removeError = current.scene.renderError.addEventListener(
      (_scene: Cesium.Scene, reason: unknown) => {
        reportFrontendError("renderer", reason, "Cesium render");
        setRenderError(`지도 렌더링 실패: ${String(reason)}`);
      },
    );
    const removeRendered = current.scene.postRender.addEventListener(() => {
      current.scene.canvas.dataset.rendered = "true";
    });
    viewer.current = current;
    setReady(true);
    const observer = new ResizeObserver(() => {
      const visible =
        !!container.current?.clientWidth && !!container.current.clientHeight;
      current.useDefaultRenderLoop = visible;
      if (visible) {
        current.resize();
        if (pendingFrame.current) {
          frameMap(
            current,
            framing.current.mode,
            framing.current.points,
            framing.current.minimumRadius,
          );
          pendingFrame.current = false;
        } else current.scene.requestRender();
      }
    });
    observer.observe(container.current);
    return () => {
      observer.disconnect();
      removeError();
      removeRendered();
      marker.current = null;
      viewer.current = null;
      current.destroy();
    };
  }, [attempt]);
  useEffect(() => {
    const current = viewer.current;
    if (!ready || !current) return;
    setTerrainError("");
    setStreamError("");
    setStreamFallback(false);
    let active = true;
    try {
      current.terrainProvider = streamAWS
        ? awsTerrainProvider(
            grid,
            terrainOffset,
            (reason) => {
              if (active) {
                reportFrontendError("renderer", reason, "AWS terrain streaming");
                setStreamError(
                  `AWS 주변 지형 표시 실패: ${String(reason)}. 저장된 고도 영역은 유지되며, 가져오지 못한 영역은 기준 타원체로 표시됩니다.`,
                );
              }
            },
            () => {
              if (active) setStreamFallback(true);
            },
          )
        : grid
          ? terrainProvider(grid, terrainOffset)
          : new Cesium.EllipsoidTerrainProvider();
    } catch (reason) {
      reportFrontendError("renderer", reason, "Cesium terrain provider");
      current.terrainProvider = new Cesium.EllipsoidTerrainProvider();
      setTerrainError(String(reason));
    }
    current.scene.requestRender();
    return () => {
      active = false;
    };
  }, [grid, terrainOffset, ready, streamAWS]);
  useEffect(() => {
    const current = viewer.current;
    if (!ready || !current || !hasTerrain || mode !== "3D") return;
    const material = terrainMaterial();
    current.scene.globe.material = material;
    current.scene.requestRender();
    return () => {
      if (!current.isDestroyed()) current.scene.globe.material = undefined;
      material.destroy();
    };
  }, [hasTerrain, mode, ready]);
  useEffect(() => {
    const current = viewer.current;
    if (!ready || !current || !w.pickingSite || w.mapMode !== "design") return;
    const handler = new Cesium.ScreenSpaceEventHandler(current.scene.canvas);
    handler.setInputAction(
      (event: Cesium.ScreenSpaceEventHandler.PositionedEvent) => {
        const ray = current.camera.getPickRay(event.position);
        const point =
          (ray && current.scene.globe.pick(ray, current.scene)) ||
          current.camera.pickEllipsoid(
            event.position,
            current.scene.globe.ellipsoid,
          );
        if (!point) {
          setDataError(
            "지표면을 선택하세요. 환경 패널에서 위도·경도를 직접 입력할 수도 있습니다.",
          );
          return;
        }
        const location = Cesium.Cartographic.fromCartesian(point);
        setDataError("");
        w.placeSite(
          Cesium.Math.toDegrees(location.latitude),
          Cesium.Math.toDegrees(location.longitude),
        );
      },
      Cesium.ScreenSpaceEventType.LEFT_CLICK,
    );
    const cancelPicking = (event: KeyboardEvent) => {
      if (event.key === "Escape") w.setPickingSite(false);
    };
    window.addEventListener("keydown", cancelPicking);
    return () => {
      handler.destroy();
      window.removeEventListener("keydown", cancelPicking);
    };
  }, [ready, w.pickingSite, w.mapMode, w.placeSite, w.setPickingSite]);
  useEffect(() => {
    const current = viewer.current;
    if (!ready || !current) return;
    const targetMode =
      mode === "2D" ? Cesium.SceneMode.SCENE2D : Cesium.SceneMode.SCENE3D;
    if (current.scene.mode !== targetMode) {
      if (mode === "2D") current.scene.morphTo2D(0);
      else current.scene.morphTo3D(0);
    }
    if (!container.current?.clientWidth || !container.current.clientHeight) {
      pendingFrame.current = true;
      return;
    }
    frameMap(current, mode, allPoints, minimumRadius);
    pendingFrame.current = false;
  }, [mode, ready, allPoints, minimumRadius]);
  useEffect(() => {
    const current = viewer.current;
    if (!ready || !current) return;
    setImageryError("");
    current.imageryLayers.removeAll();
    let removeError: (() => void) | undefined;
    if (imagery !== "none") {
      if (imagery === "vworld" && !w.vworldKey) {
        setImageryError(
          "VWorld API 키를 입력하고 연결을 누르세요. 고도 자료는 유지됩니다.",
        );
        current.scene.requestRender();
        return;
      }
      const provider =
        imagery === "vworld"
          ? new Cesium.UrlTemplateImageryProvider({
              url: `https://api.vworld.kr/req/wmts/1.0.0/${encodeURIComponent(w.vworldKey)}/Satellite/{z}/{y}/{x}.jpeg`,
              maximumLevel: 19,
              credit: new Cesium.Credit(
                '<a href="https://www.vworld.kr/">공간정보 오픈플랫폼 VWorld</a>',
                true,
              ),
            })
          : new Cesium.OpenStreetMapImageryProvider({
              url: "https://tile.openstreetmap.org/",
              maximumLevel: 18,
              credit: new Cesium.Credit(
                '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>',
                true,
              ),
            });
      removeError = provider.errorEvent.addEventListener(() =>
        setImageryError(
          imagery === "vworld"
            ? "VWorld 배경 요청 실패. API 키·WMTS 권한·등록 서비스 주소를 확인하세요. 고도 자료는 유지됩니다."
            : "배경 지도 연결 실패. 고도 자료·좌표·궤적은 별도로 표시됩니다.",
        ),
      );
      const layer = current.imageryLayers.addImageryProvider(provider);
      layer.saturation = 0;
    }
    current.scene.requestRender();
    return () => {
      removeError?.();
    };
  }, [imagery, ready, w.vworldKey]);
  useEffect(() => {
    const current = viewer.current;
    if (!ready || !current) return;
    current.entities.removeAll();
    marker.current = null;
    setDataError(trajectory.error);
    current.entities.add({
      id: "launch-site",
      position: launch,
      point: {
        pixelSize: 9,
        color: Cesium.Color.WHITE,
        outlineColor: Cesium.Color.BLACK,
        outlineWidth: 2,
        disableDepthTestDistance: Infinity,
      },
      label: {
        text: result ? "실행 발사점" : "발사점",
        font: "12px sans-serif",
        pixelOffset: new Cesium.Cartesian2(0, -18),
        fillColor: Cesium.Color.BLACK,
        showBackground: true,
        backgroundColor: Cesium.Color.WHITE.withAlpha(0.8),
        disableDepthTestDistance: Infinity,
      },
    });
    if (grid)
      current.entities.add({
        polyline: {
          positions: Cesium.Cartesian3.fromDegreesArray([
            grid.west,
            grid.south,
            grid.east,
            grid.south,
            grid.east,
            grid.north,
            grid.west,
            grid.north,
            grid.west,
            grid.south,
          ]),
          clampToGround: true,
          width: 1,
          material: Cesium.Color.fromCssColorString("#888888"),
        },
      });
    for (const positions of showGrid ? meshLines : [])
      current.entities.add({
        polyline: {
          positions,
          width: 1,
          material: Cesium.Color.fromCssColorString("#777777").withAlpha(0.7),
          arcType: Cesium.ArcType.NONE,
        },
      });
    if (trajectory.points.length > 1) {
      current.entities.add({
        id: "flight-trajectory",
        polyline: {
          positions: trajectory.points,
          width: 4,
          material: new Cesium.PolylineOutlineMaterialProperty({
            color: Cesium.Color.WHITE,
            outlineColor: Cesium.Color.BLACK,
            outlineWidth: 1,
          }),
          clampToGround: false,
          arcType: Cesium.ArcType.NONE,
        },
      });
      marker.current = current.entities.add({
        id: "flight-position",
        position: latestPosition.current || trajectory.points[0],
        point: {
          pixelSize: 8,
          color: Cesium.Color.WHITE,
          outlineColor: Cesium.Color.BLACK,
          outlineWidth: 2,
          disableDepthTestDistance: Infinity,
        },
      });
    }
    const summary = result?.summary;
    if (
      summary?.landed &&
      summary.impact_latitude != null &&
      summary.impact_longitude != null
    )
      current.entities.add({
        id: "impact-site",
        position: Cesium.Cartesian3.fromDegrees(
          summary.impact_longitude,
          summary.impact_latitude,
          (summary.impact_elevation_m ?? 0) + flightOffset,
        ),
        point: {
          pixelSize: 11,
          color: Cesium.Color.BLACK,
          disableDepthTestDistance: Infinity,
        },
        label: {
          text: "예측 착륙",
          font: "12px sans-serif",
          pixelOffset: new Cesium.Cartesian2(0, -20),
          showBackground: true,
          disableDepthTestDistance: Infinity,
        },
      });
    current.scene.requestRender();
  }, [
    launch,
    meshLines,
    trajectory,
    result,
    flightOffset,
    ready,
    showGrid,
    grid,
  ]);
  useEffect(() => {
    const current = viewer.current;
    if (!ready || !current || !marker.current || !selectedPosition) return;
    marker.current.position = new Cesium.ConstantPositionProperty(
      selectedPosition,
    );
    current.scene.requestRender();
  }, [selectedPosition, ready]);
  const heightApproximate =
    env.elevation_reference === "unknown" ||
    grid?.reference === "unknown" ||
    (!!grid &&
      env.elevation_reference !== grid.reference &&
      env.elevation_reference !== "ellipsoid" &&
      grid.reference !== "ellipsoid") ||
    (env.geoid_undulation_m == null &&
      (env.elevation_reference !== "ellipsoid" ||
        (!!grid && grid.reference !== "ellipsoid")));
  return (
    <section className="view-panel">
      <div className="panel-toolbar">
        <label>
          표시 자료{" "}
          <select
            value={w.mapMode}
            onChange={(event) => {
              w.setPickingSite(false);
              w.setMapMode(
                event.target.value === "result" ? "result" : "design",
              );
            }}
          >
            <option value="design">편집 중인 발사장</option>
            <option value="result" disabled={!w.result}>
              선택 실행 결과
            </option>
          </select>
        </label>
        <fieldset className="segmented" aria-label="지도 보기">
          {(["2D", "3D"] as const).map((view) => (
            <button
              type="button"
              key={view}
              aria-pressed={mode === view}
              onClick={() => setMode(view)}
            >
              {view}
            </button>
          ))}
        </fieldset>
        <button
          type="button"
          disabled={!ready}
          onClick={() => {
            if (viewer.current) frameMap(viewer.current, mode, sitePoints);
          }}
        >
          발사장 맞춤
        </button>
        {result && (
          <button
            type="button"
            disabled={!ready}
            onClick={() => {
              if (viewer.current)
                frameMap(viewer.current, mode, allPoints, minimumRadius);
            }}
          >
            전체 궤적
          </button>
        )}
        <label>
          <input
            type="checkbox"
            checked={showGrid}
            onChange={(event) => setShowGrid(event.target.checked)}
          />{" "}
          고도 격자
        </label>
        <button
          type="button"
          aria-pressed={w.pickingSite}
          onClick={() => {
            w.setMapMode("design");
            w.setPickingSite(!w.pickingSite);
          }}
        >
          {w.pickingSite ? "선택 취소 · Esc" : "발사점 선택"}
        </button>
        <label>
          배경 지도{" "}
          <select
            value={imagery}
            onChange={(event) => {
              const value = event.target.value;
              if (value !== "none" && value !== "osm" && value !== "vworld")
                return;
              setImagery(value);
              if (value === "vworld")
                void w.act(async () => {
                  await (await desktopApi()).open_terrain_portal("vworld");
                });
            }}
          >
            <option value="none">없음</option>
            <option value="osm">OpenStreetMap</option>
            <option value="vworld">VWorld · 위성영상 · API 키</option>
          </select>
        </label>
        {imagery === "vworld" && (
          <>
            <label>
              VWorld API 키{" "}
              <input
                type="password"
                autoComplete="off"
                spellCheck={false}
                maxLength={256}
                value={vworldDraft}
                onChange={(event) => setVworldDraft(event.target.value)}
              />
            </label>
            <button
              type="button"
              disabled={!vworldDraft.trim()}
              onClick={() => w.setVworldKey(vworldDraft.trim())}
            >
              연결
            </button>
            <button
              type="button"
              onClick={() =>
                void w.act(async () => {
                  await (await desktopApi()).open_terrain_portal("vworld");
                })
              }
            >
              키 발급 사이트
            </button>
          </>
        )}
      </div>
      {imagery === "vworld" && (
        <p className="caption">
          키는 현재 앱 메모리에서만 사용합니다. VWorld에서 등록한 서비스
          URL·허용 도메인과 이 앱의 실행 주소가 맞아야 합니다.
        </p>
      )}
      {w.pickingSite && (
        <p className="notice" role="status">
          지표면을 클릭하면 발사점으로 지정합니다. 발사 고도는 유지됩니다. 취소:
          Esc.
        </p>
      )}
      {[
        renderError,
        imageryError,
        terrainError,
        streamError,
        dataError,
        w.terrainAutoError,
      ]
        .filter(Boolean)
        .map((message) => (
          <p className="notice warning" role="status" key={message}>
            {message}
          </p>
        ))}
      {renderError && (
        <button
          type="button"
          onClick={() => {
            setReady(false);
            setAttempt((value) => value + 1);
          }}
        >
          지도 다시 시작
        </button>
      )}
      {waiting && (
        <p className="empty" role="status">
          {w.selectedRun
            ? `실행 ${w.selectedRun.slice(0, 8)} · ${runStateLabels[w.selectedRunState ?? ""] || "상태 확인 중"}${w.selectedRunState === "succeeded" ? " · 궤적 불러오는 중…" : ""}`
            : "실행 이력에서 결과를 선택하세요."}
        </p>
      )}
      {w.terrainBusy && (
        <p className="caption map-status" role="status">
          AWS/선택한 소스의 계산용 고도를 가져오는 중…
        </p>
      )}
      <div
        ref={container}
        className="map-host"
        hidden={waiting}
        data-picking={w.pickingSite}
        role="img"
        aria-label="발사장 지형과 비행 궤적"
      />
      {!waiting && (
        <details className="map-info">
          <summary>
            지도 정보 · 도움말
            {streamFallback ? " · 일부 낮은 해상도 지형" : ""}
            {heightApproximate ? " · 고도 기준 미확인" : ""}
          </summary>
          {result && (
            <p className="caption" role="status">
              실행 {result.runId.slice(0, 8)} · {mode} 궤적 · 선택 시간{" "}
              {w.time.toFixed(2)} s · 당시 발사 환경·고도 자료 사용
              {result.telemetry.decimated ? " · 간추린 궤적" : ""}
            </p>
          )}
          <p className="caption">
            {env.latitude.toFixed(5)}°, {env.longitude.toFixed(5)}° ·{" "}
            {terrainError
              ? "3D 지형 사용 불가 · 타원체 표면 표시"
              : grid
                ? `${mode === "3D" ? "3D 지형 · 높이 배율 1× · " : ""}${grid.source.split(";")[0]} · 고도 ${terrainRange} · 표본 간격 ${grid.sampling_distance_m.toFixed(0)} m · ${streamAWS ? "경계 밖 AWS 참고 지형" : "격자 밖 기준 타원체"}`
                : streamAWS
                  ? "AWS 주변 지형 · 계산용 고도 영역 없음"
                  : "고도 자료 없음 · 타원체 표면 표시"}
            {heightApproximate
              ? " · 고도 기준/N 미확인: 3D 절대 높이는 근사 표시"
              : ""}
          </p>
          {streamAWS && (
            <p className="caption">
              AWS 실제 고도 · 높이 배율 1×. 경계 안은 저장된 계산용 고도, 경계
              밖은 주변 지형 표시입니다. 사진처럼 보이는 표면은 VWorld
              위성영상을 추가하세요.
            </p>
          )}
          {streamAWS && streamFallback && (
            <p className="caption" role="status">
              일부 AWS 주변 지형은 정상적인 낮은 해상도 자료로 표시합니다.
              저장된 계산용 고도는 유지됩니다.
            </p>
          )}
          {imagery === "none" && (
            <p className="caption">
              배경 지도 꺼짐 · 도로·지명은 OpenStreetMap, 위성영상은 VWorld를
              선택하세요.
            </p>
          )}
          {!grid && !streamAWS && (
            <p className={mode === "3D" ? "notice" : "caption"} role="status">
              고도 자료가 없어 산·계곡이 표시되지 않습니다. 발사 환경 →
              위치·지형에서 고도 자료를 가져오세요. 온라인 배경 지도에는 지형
              높이가 포함되지 않습니다.
            </p>
          )}
          <p className="caption">
            이동: 드래그 · 확대/축소: 휠 · 3D 회전/기울기: Ctrl+드래그 또는
            가운데 버튼. 시점은 발사장 맞춤으로 복원합니다.
          </p>
          {result?.summary.landed && (
            <p className="caption">
              예측 착륙 {result.summary.impact_latitude?.toFixed(6)}°,{" "}
              {result.summary.impact_longitude?.toFixed(6)}° ·{" "}
              {result.summary.ground_model === "terrain"
                ? "지형 지면"
                : "발사 고도 평면"}
            </p>
          )}
        </details>
      )}
    </section>
  );
}
