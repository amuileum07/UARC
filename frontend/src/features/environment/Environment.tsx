import { NumberField } from "../../components/Fields";
import { useWorkspace } from "../../workspace";

export function EnvironmentEditor() {
  const w = useWorkspace();
  const env = w.design.environment;
  return (
    <div className="panel scroll">
      <p className="eyebrow">LAUNCH ENVIRONMENT</p>
      <h2>발사장 · 환경</h2>
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
          <option value="unknown">미지정 · 검증 불가</option>
          <option value="EGM96">EGM96 정표고</option>
          <option value="ellipsoid">타원체고 h</option>
        </select>
      </label>
      <NumberField
        label="발사대 높이"
        unit="m"
        value={env.pad_height_m || 0}
        onChange={(v) => w.edit(["environment", "pad_height_m"], v)}
      />
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
      <h3>지형 자료</h3>
      <button disabled={w.terrainBusy} onClick={() => void w.loadTerrain()}>
        {w.terrainBusy ? "고도 자료 요청 중…" : "주변 2 km 고도 자료 가져오기"}
      </button>
      <p className="muted">
        Open Topo Data · SRTM90m / 9×9 표본, 간격 약 250 m. 클릭 시 좌표를
        서비스에 전송합니다. 지형은 설계·실행에 보존됩니다.
      </p>
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
          {w.elevation.ground_elevation_m != null && (
            <button
              onClick={() =>
                w.edit(
                  ["environment", "elevation"],
                  w.elevation!.ground_elevation_m! + (env.pad_height_m || 0),
                )
              }
            >
              지형 + 발사대 고도 적용
            </button>
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
      <h3>바람 · 대기</h3>
      <label className="field">
        대기 모델
        <select
          value={env.atmosphere_type || "standard_atmosphere"}
          onChange={(e) => {
            w.edit(["environment", "atmosphere_type"], e.target.value);
            if (e.target.value === "standard_atmosphere") {
              w.edit(["environment", "wind_u"], 0);
              w.edit(["environment", "wind_v"], 0);
            }
          }}
        >
          <option value="standard_atmosphere">표준 대기</option>
          <option value="custom_atmosphere">사용자 대기 · 바람</option>
        </select>
      </label>
      {env.atmosphere_type === "custom_atmosphere" && (
        <>
          <NumberField
            label="동쪽 바람 u"
            unit="m/s"
            value={typeof env.wind_u === "number" ? env.wind_u : 0}
            onChange={(v) => w.edit(["environment", "wind_u"], v)}
          />
          <NumberField
            label="북쪽 바람 v"
            unit="m/s"
            value={typeof env.wind_v === "number" ? env.wind_v : 0}
            onChange={(v) => w.edit(["environment", "wind_v"], v)}
          />
        </>
      )}
    </div>
  );
}
