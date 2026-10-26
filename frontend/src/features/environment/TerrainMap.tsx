import { useEffect, useRef, useState } from "react";
import * as Cesium from "cesium";
import { flightCoordinates } from "../../lib/geography";
import { useWorkspace } from "../../workspace";

export function TerrainMap() {
  const w = useWorkspace();
  const container = useRef<HTMLDivElement>(null);
  const viewer = useRef<Cesium.Viewer | null>(null);
  const [mode, setMode] = useState<"2D" | "3D">("3D");
  const [imagery, setImagery] = useState(false);
  const [error, setError] = useState("");
  const [ready, setReady] = useState(false);
  const env = w.result?.design.environment || w.design.environment;
  useEffect(() => {
    if (!container.current) return;
    let current: Cesium.Viewer;
    try {
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
      setError(`지도를 시작할 수 없습니다: ${String(reason)}`);
      return;
    }
    current.scene.globe.baseColor = Cesium.Color.fromCssColorString("#dddddd");
    current.scene.backgroundColor = Cesium.Color.fromCssColorString("#f4f4f4");
    if (current.scene.skyAtmosphere) current.scene.skyAtmosphere.show = false;
    viewer.current = current;
    setReady(true);
    const observer = new ResizeObserver(() => {
      if (container.current?.clientWidth && container.current.clientHeight) {
        current.resize();
        current.scene.requestRender();
      }
    });
    observer.observe(container.current);
    return () => {
      observer.disconnect();
      current.destroy();
      viewer.current = null;
    };
  }, []);
  useEffect(() => {
    const current = viewer.current;
    if (!current) return;
    if (mode === "2D") current.scene.morphTo2D(0);
    else current.scene.morphTo3D(0);
    current.scene.requestRender();
  }, [mode, ready]);
  useEffect(() => {
    const current = viewer.current;
    if (!current) return;
    current.imageryLayers.removeAll();
    if (imagery) {
      const provider = new Cesium.OpenStreetMapImageryProvider({
        url: "https://tile.openstreetmap.org/",
        maximumLevel: 18,
        credit: "© OpenStreetMap contributors",
      });
      provider.errorEvent.addEventListener(() =>
        setError("배경 지도 연결 실패. 좌표·지형·궤적은 계속 표시합니다."),
      );
      const layer = current.imageryLayers.addImageryProvider(provider);
      layer.saturation = 0;
    }
    current.scene.requestRender();
  }, [imagery, ready]);
  useEffect(() => {
    const current = viewer.current;
    if (!current) return;
    current.camera.setView({
      destination: Cesium.Cartesian3.fromDegrees(
        env.longitude,
        env.latitude,
        Math.max(3500, env.elevation + 3500),
      ),
      orientation: { heading: 0, pitch: -Math.PI / 2, roll: 0 },
    });
    current.scene.requestRender();
  }, [env.latitude, env.longitude, ready]);
  useEffect(() => {
    const current = viewer.current;
    if (!current) return;
    current.entities.removeAll();
    setError("");
    try {
      const terrain = env.terrain;
      const terrainOffset =
        terrain?.reference === "EGM96" ? env.geoid_undulation_m || 0 : 0;
      if (terrain) {
        const rows = terrain.heights.length,
          cols = terrain.heights[0].length;
        for (let y = 0; y < rows - 1; y++)
          for (let x = 0; x < cols - 1; x++) {
            const corners = [
              [y, x],
              [y, x + 1],
              [y + 1, x + 1],
              [y + 1, x],
            ];
            if (corners.some(([row, col]) => terrain.heights[row][col] == null))
              continue;
            const positions = corners.map(([row, col]) =>
              Cesium.Cartesian3.fromDegrees(
                terrain.west +
                  ((terrain.east - terrain.west) * col) / (cols - 1),
                terrain.south +
                  ((terrain.north - terrain.south) * row) / (rows - 1),
                (terrain.heights[row][col] || 0) + terrainOffset,
              ),
            );
            current.entities.add({
              polygon: {
                hierarchy: new Cesium.PolygonHierarchy(positions),
                perPositionHeight: true,
                material:
                  Cesium.Color.fromCssColorString("#aaaaaa").withAlpha(0.82),
                outline: true,
                outlineColor: Cesium.Color.fromCssColorString("#777777"),
              },
            });
          }
      }
      const flightOffset =
        env.elevation_reference === "ellipsoid"
          ? 0
          : env.geoid_undulation_m || 0;
      current.entities.add({
        position: Cesium.Cartesian3.fromDegrees(
          env.longitude,
          env.latitude,
          env.elevation + flightOffset,
        ),
        point: {
          pixelSize: 9,
          color: Cesium.Color.WHITE,
          outlineColor: Cesium.Color.BLACK,
          outlineWidth: 2,
          disableDepthTestDistance: Infinity,
        },
        label: {
          text: w.result ? "실행 발사점" : "발사점",
          font: "12px sans-serif",
          pixelOffset: new Cesium.Cartesian2(0, -18),
          fillColor: Cesium.Color.BLACK,
          showBackground: true,
          backgroundColor: Cesium.Color.WHITE.withAlpha(0.8),
          disableDepthTestDistance: Infinity,
        },
      });
      if (w.result) {
        const data = w.result.telemetry.data;
        const point = (row: number[]) => {
          const [lat, lon] = flightCoordinates(
            env.latitude,
            env.longitude,
            row[1],
            row[2],
          );
          return Cesium.Cartesian3.fromDegrees(lon, lat, row[3] + flightOffset);
        };
        current.entities.add({
          polyline: {
            positions: data.map(point),
            width: 3,
            material: Cesium.Color.fromCssColorString("#333333"),
            arcType: Cesium.ArcType.NONE,
          },
        });
        const sample = data.reduce(
          (best, row) =>
            Math.abs(row[0] - w.time) < Math.abs(best[0] - w.time) ? row : best,
          data[0],
        );
        if (sample)
          current.entities.add({
            position: point(sample),
            point: {
              pixelSize: 8,
              color: Cesium.Color.fromCssColorString("#888888"),
              disableDepthTestDistance: Infinity,
            },
          });
        const summary = w.result.summary;
        if (
          summary.landed &&
          summary.impact_latitude != null &&
          summary.impact_longitude != null
        )
          current.entities.add({
            position: Cesium.Cartesian3.fromDegrees(
              summary.impact_longitude,
              summary.impact_latitude,
              (summary.impact_elevation_m || 0) + flightOffset,
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
      }
      current.scene.requestRender();
    } catch (reason) {
      setError(String(reason));
    }
  }, [env, w.result, w.time, ready]);
  return (
    <section className="view-panel">
      <div className="panel-toolbar">
        <div className="segmented" aria-label="지도 보기">
          {(["2D", "3D"] as const).map((view) => (
            <button
              key={view}
              aria-pressed={mode === view}
              onClick={() => setMode(view)}
            >
              {view}
            </button>
          ))}
        </div>
        <label>
          <input
            type="checkbox"
            checked={imagery}
            onChange={(e) => setImagery(e.target.checked)}
          />{" "}
          온라인 배경 지도
        </label>
        <span className="muted">
          {w.result ? `실행 ${w.selectedRun.slice(0, 8)}` : "편집 중인 발사장"}
        </span>
      </div>
      {error && (
        <p className="notice warning" role="status">
          {error}
        </p>
      )}
      <div
        ref={container}
        className="map-host"
        role="img"
        aria-label="발사장 지형과 비행 궤적"
      />
      <p className="caption">
        {env.latitude.toFixed(5)}°, {env.longitude.toFixed(5)}° ·{" "}
        {env.terrain
          ? `${env.terrain.source.split(";")[0]} · 표본 간격 ${env.terrain.sampling_distance_m.toFixed(0)} m`
          : "고도 자료 없음 · 타원체 표면 표시"}
        {env.elevation_reference !== "ellipsoid" &&
        env.geoid_undulation_m == null
          ? " · N 미지정: 3D 절대 높이는 근사 표시"
          : ""}
      </p>
      {w.result?.summary.landed && (
        <p className="caption">
          예측 착륙 {w.result.summary.impact_latitude?.toFixed(6)}°,{" "}
          {w.result.summary.impact_longitude?.toFixed(6)}° ·{" "}
          {w.result.summary.ground_model === "terrain"
            ? "지형 지면"
            : "발사 고도 평면"}
        </p>
      )}
    </section>
  );
}
