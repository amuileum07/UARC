import { NumberField } from "../../components/Fields";
import { useWorkspace } from "../../workspace";
import { TerrainSources } from "./TerrainSources";
import { terrainReferences } from "../../lib/terrain";
import { SiteSearch } from "./SiteSearch";
import { WeatherEditor } from "./Weather";
import { ConfigFields } from "../../components/ConfigFields";

export function EnvironmentEditor() {
  const w = useWorkspace();
  const [tab, setTab] = useState<"site" | "weather">("site");
  const env = w.design.environment;
  return (
    <div className="panel scroll">
      <p className="eyebrow">LAUNCH ENVIRONMENT</p>
      <h2>발사장 · 환경</h2>
      <fieldset className="segmented" aria-label="발사 환경 설정">
        <button
          type="button"
          aria-pressed={tab === "site"}
          onClick={() => setTab("site")}
        >
          위치 · 지형
        </button>
        <button
          type="button"
          aria-pressed={tab === "weather"}
          onClick={() => setTab("weather")}
        >
          시각 · 기상
        </button>
      </fieldset>
      <div hidden={tab !== "site"}>
        <SiteSearch />
        <h3>발사 위치</h3>
        <NumberField
          label="위도"
          unit="°"
          value={env.latitude}
          onChange={(v) => w.edit(["environment", "latitude"], v)}
        />
        <NumberField
          label="경도"
          unit="°"
          value={env.longitude}
          onChange={(v) => w.edit(["environment", "longitude"], v)}
        />
        <label className="field">
          좌표 기준
          <select
            value={env.datum || "SIRGAS2000"}
            onChange={(e) => w.edit(["environment", "datum"], e.target.value)}
          >
            {["WGS84", "SIRGAS2000", "NAD83", "SAD69"].map((d) => (
              <option key={d}>{d}</option>
            ))}
          </select>
        </label>
        <p className="muted">
          좌표 기준 선택은 변환이 아닙니다. 입력 좌표에 맞게 지정하세요.
        </p>
        <NumberField
          label="발사 고도"
          unit="m"
          value={env.elevation}
          onChange={(v) => w.edit(["environment", "elevation"], v)}
        />
        <label className="field">
          수직 고도 기준
          <select
            value={env.elevation_reference || "unknown"}
            onChange={(e) =>
              w.edit(["environment", "elevation_reference"], e.target.value)
            }
          >
            {Object.entries(terrainReferences).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <NumberField
          label="발사대 높이"
          unit="m"
          value={env.pad_height_m || 0}
          onChange={(v) => w.edit(["environment", "pad_height_m"], v)}
        />
        {w.weatherBusy && (
          <p role="status">
            변경된 발사 위치·고도·시각의 기상을 자동으로 갱신하고 있습니다…
          </p>
        )}
        {w.problems.weather && (
          <p className="notice warning" role="status">
            {w.problems.weather}
          </p>
        )}
        <NumberField
          label="고도 경고 허용차"
          unit="m"
          value={env.elevation_tolerance_m ?? 15}
          onChange={(v) => w.edit(["environment", "elevation_tolerance_m"], v)}
        />
        <label className="check">
          <input
            type="checkbox"
            checked={env.geoid_undulation_m != null}
            onChange={(e) =>
              w.edit(
                ["environment", "geoid_undulation_m"],
                e.target.checked ? 0 : null,
              )
            }
          />{" "}
          지오이드 기복 N 직접 지정
        </label>
        {env.geoid_undulation_m != null && (
          <NumberField
            label="지오이드 기복 N"
            unit="m"
            value={env.geoid_undulation_m}
            onChange={(v) => w.edit(["environment", "geoid_undulation_m"], v)}
          />
        )}
        <p className="muted">
          h = H + N. 다른 수직 기준을 비교할 때 해당 장소의 N이 필요합니다.
        </p>
        <TerrainSources />
        {w.elevation && (
          <div
            className={`notice ${w.elevation.status === "warning" ? "warning" : ""}`}
            role="status"
          >
            <strong>
              {
                {
                  ok: "고도 비교 통과",
                  warning: "고도 차이 경고",
                  unverified: "고도 미검증",
                }[w.elevation.status]
              }
            </strong>
            <p>{w.elevation.message}</p>
            {w.elevation.ground_elevation_m != null && (
              <p>
                지표면 {w.elevation.ground_elevation_m.toFixed(2)} m · 차이{" "}
                {w.elevation.difference_m?.toFixed(2)} m
              </p>
            )}
          </div>
        )}
        <label className="field">
          지면 모델
          <select
            value={env.terrain_mode || "flat"}
            onChange={(e) =>
              w.edit(["environment", "terrain_mode"], e.target.value)
            }
          >
            <option value="flat">발사 고도 평면</option>
            <option value="terrain">지형 충돌 · RocketPy 1.13 전용</option>
          </select>
        </label>
        <details>
          <summary>대기 계산 범위 · 중력</summary>
          <ConfigFields
            schemaName="EnvironmentConfig"
            object={env}
            path={["environment"]}
            only={["gravity", "max_expected_height"]}
          />
          <p className="muted">
            중력을 자동으로 두면 위도·고도에 따른 모델을 사용합니다. 대기 계산
            상한은 발사 고도보다 높게 지정하세요.
          </p>
        </details>
      </div>
      <div hidden={tab !== "weather"}>
        <p className="muted">
          발사장 {env.latitude.toFixed(5)}°, {env.longitude.toFixed(5)}° ·{" "}
          {env.elevation.toFixed(1)} m
        </p>
        <WeatherEditor />
      </div>
    </div>
  );
}
import { useState } from "react";
