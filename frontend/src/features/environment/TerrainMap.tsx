import { useEffect, useMemo, useRef, useState } from "react";
import * as Cesium from "cesium";
import { desktopApi } from "../../lib/bridge";
import { flightCoordinates } from "../../lib/geography";
import { useWorkspace } from "../../workspace";
import { awsTerrainProvider } from "./awsTerrain";
import { frameMap, terrainMaterial, terrainProvider } from "./mapTerrain";

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
  const [showGrid, setShowGrid] = useState(false);
  const [dataError, setDataError] = useState("");
  const [ready, setReady] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const result = w.mapMode === "result" ? w.result : null;
  const env = result?.design.environment || w.design.environment;
  const grid = env.terrain;
  const streamAWS =
    grid?.provider === "aws" || (!grid && w.terrainSource === "aws");
  const terrainRange = useMemo(() => {
    const heights = grid?.heights.flat().filter((height) => height !== null);
    return heights?.length
      ? `${Math.min(...heights).toFixed(0)}–${Math.max(...heights).toFixed(0)} m`
      : "";
  }, [grid]);
  const terrainOffset =
    grid && grid.reference !== "ellipsoid" ? (env.geoid_undulation_m ?? 0) : 0;
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
  const meshLines = useMemo(() => {
    if (
      !grid ||
      grid.heights.some((row) => row.some((height) => height === null))
    )
      return [];
    const rows = grid.heights.length,
      columns = grid.heights[0].length;
    const nodes = grid.heights.map((row, y) =>
      row.map((height, x) =>
        Cesium.Cartesian3.fromDegrees(
          grid.west + ((grid.east - grid.west) * x) / (columns - 1),
          grid.south + ((grid.north - grid.south) * y) / (rows - 1),
          (height ?? 0) + terrainOffset + 1,
        ),
      ),
    );
    return [
      ...nodes.filter(
        (_, y) => y % Math.ceil((rows - 1) / 16) === 0 || y === rows - 1,
      ),
      ...Array.from({ length: columns }, (_, x) => x)
        .filter(
          (x) => x % Math.ceil((columns - 1) / 16) === 0 || x === columns - 1,
        )
        .map((x) => nodes.map((row) => row[x])),
    ];
  }, [grid, terrainOffset]);
  const trajectory = useMemo(() => {
    try {
      const points = (result?.telemetry.data || []).map((row) => {
        const [lat, lon] = flightCoordinates(
          env.latitude,
          env.longitude,
          row[1],
          row[2],
        );
        return Cesium.Cartesian3.fromDegrees(lon, lat, row[3] + flightOffset);
      });
      return { points, error: "" };
    } catch (reason) {
      return { points: [], error: String(reason) };
    }
  }, [result, env.latitude, env.longitude, flightOffset]);
  const sitePoints = useMemo(
    () => [launch, ...meshLines.flat()],
    [launch, meshLines],
  );
  const allPoints = useMemo(
    () =>
      trajectory.points.length > 1
        ? [launch, ...trajectory.points]
        : sitePoints,
    [launch, sitePoints, trajectory],
  );
  const pendingFrame = useRef(true);
  const framing = useRef({ mode, points: allPoints });
  framing.current = { mode, points: allPoints };
  const selectedPosition = useMemo(() => {
    if (!result) return undefined;
    const data = result.telemetry.data;
    let index = 0;
    for (let i = 1; i < data.length; i++)
      if (Math.abs(data[i][0] - w.time) < Math.abs(data[index][0] - w.time))
        index = i;
    return trajectory.points[index];
  }, [result, w.time, trajectory]);
  const latestPosition = useRef(selectedPosition);
  latestPosition.current = selectedPosition;
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
        maximumRenderTimeChange: Infinity,
        terrainProvider: new Cesium.EllipsoidTerrainProvider(),
      });
    } catch (reason) {
      container.current.replaceChildren();
      setRenderError(
        `지도를 시작할 수 없습니다: ${String(reason)}. 환경 패널의 좌표 입력은 계속 사용할 수 있습니다.`,
      );
      return;
    }
    current.scene.globe.baseColor = Cesium.Color.fromCssColorString("#dddddd");
    current.scene.backgroundColor = Cesium.Color.fromCssColorString("#f4f4f4");
    current.scene.globe.depthTestAgainstTerrain = true;
    if (current.scene.skyAtmosphere) current.scene.skyAtmosphere.show = false;
    const removeError = current.scene.renderError.addEventListener(
      (_scene: Cesium.Scene, reason: unknown) =>
        setRenderError(`지도 렌더링 실패: ${String(reason)}`),
    );
    viewer.current = current;
    setReady(true);
    const observer = new ResizeObserver(() => {
      const visible =
        !!container.current?.clientWidth && !!container.current.clientHeight;
      current.useDefaultRenderLoop = visible;
      if (visible) {
        current.resize();
        if (pendingFrame.current) {
          frameMap(current, framing.current.mode, framing.current.points);
          pendingFrame.current = false;
        } else current.scene.requestRender();
      }
    });
    observer.observe(container.current);
    return () => {
      observer.disconnect();
      removeError();
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
    let active = true;
    current.scene.globe.material = undefined;
    let material: Cesium.Material | undefined;
    try {
      current.terrainProvider = streamAWS
        ? awsTerrainProvider(grid, terrainOffset, () => {
            if (active)
              setStreamError(
                "AWS 주변 지형 연결 실패. 저장된 고도 영역은 유지되며, 가져오지 못한 영역은 기준 타원체로 표시됩니다.",
              );
          })
        : grid
          ? terrainProvider(grid, terrainOffset)
          : new Cesium.EllipsoidTerrainProvider();
      if ((grid || streamAWS) && mode === "3D") {
        material = terrainMaterial();
        current.scene.globe.material = material;
      }
    } catch (reason) {
      current.terrainProvider = new Cesium.EllipsoidTerrainProvider();
      setTerrainError(String(reason));
    }
    current.scene.requestRender();
    return () => {
      active = false;
      if (!current.isDestroyed()) current.scene.globe.material = undefined;
      material?.destroy();
    };
  }, [grid, terrainOffset, mode, ready, streamAWS]);
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
    frameMap(current, mode, allPoints);
    pendingFrame.current = false;
  }, [mode, ready, allPoints]);
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
        polyline: {
          positions: trajectory.points,
          width: 3,
          material: Cesium.Color.fromCssColorString("#333333"),
          arcType: Cesium.ArcType.NONE,
        },
      });
      marker.current = current.entities.add({
        position: latestPosition.current || trajectory.points[0],
        point: {
          pixelSize: 8,
          color: Cesium.Color.fromCssColorString("#888888"),
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
              if (viewer.current) frameMap(viewer.current, mode, allPoints);
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
      {[renderError, imageryError, terrainError, streamError, dataError]
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
      <div
        ref={container}
        className="map-host"
        data-picking={w.pickingSite}
        role="img"
        aria-label="발사장 지형과 비행 궤적"
      />
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
          AWS 실제 고도 · 높이 배율 1×. 경계 안은 저장된 계산용 고도, 경계 밖은
          주변 지형 표시입니다. 사진처럼 보이는 표면은 VWorld 위성영상을
          추가하세요.
        </p>
      )}
      {w.terrainBusy && (
        <p className="caption" role="status">
          AWS/선택한 소스의 계산용 고도를 가져오는 중…
        </p>
      )}
      {w.terrainAutoError && (
        <p className="notice warning" role="status">
          {w.terrainAutoError}
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
          위치·지형에서 고도 자료를 가져오세요. 온라인 배경 지도에는 지형 높이가
          포함되지 않습니다.
        </p>
      )}
      <p className="caption">
        이동: 드래그 · 확대/축소: 휠 · 3D 회전/기울기: Ctrl+드래그 또는 가운데
        버튼. 시점은 발사장 맞춤으로 복원합니다.
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
    </section>
  );
}
