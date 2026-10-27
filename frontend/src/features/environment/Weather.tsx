import { useRef, useState } from "react";
import { ConfigFields } from "../../components/ConfigFields";
import { ExternalAtmosphereFields } from "../rocket/Settings";
import { desktopApi } from "../../lib/bridge";
import type { WeatherProfile, WeatherRequest } from "../../lib/types";
import {
  applyWeather,
  localDateInput,
  weatherMatches,
  weatherModels,
  weatherRequest,
} from "../../lib/weather";
import { useWorkspace } from "../../workspace";
import { WeatherFile } from "./WeatherFile";

export function WeatherEditor() {
  const w = useWorkspace();
  const env = w.design.environment;
  const latest = useRef(env);
  latest.current = env;
  const [model, setModel] = useState<WeatherRequest["model"]>(
    env.weather_profile?.request.model === "file"
      ? "gfs_seamless"
      : env.weather_profile?.request.model || "gfs_seamless",
  );
  const [station, setStation] = useState(
    env.weather_profile?.request.station_id || "",
  );
  const [observationTime, setObservationTime] = useState(
    localDateInput(
      env.weather_profile?.request.observation_time || null,
      "UTC",
    ),
  );
  const query = JSON.stringify([model, station, observationTime]);
  const latestQuery = useRef(query);
  latestQuery.current = query;
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<WeatherProfile | null>(null);
  const [message, setMessage] = useState("");
  const active = env.weather_profile;
  const preview = pending && weatherMatches(env, pending) ? pending : null;
  const profile = preview || active;
  const matching = profile ? weatherMatches(env, profile) : false;
  const coversLaunch = profile
    ? profile.levels[0].altitude_m <= env.elevation &&
      env.elevation <= profile.levels[profile.levels.length - 1].altitude_m
    : false;
  const mode = active ? "online" : env.atmosphere_type || "standard_atmosphere";
  return (
    <section aria-label="발사 시각과 기상">
      <h3>발사 시각</h3>
      <label className="field">
        날짜 · 현지 시각
        <input
          type="datetime-local"
          value={localDateInput(env.date, env.timezone)}
          onChange={(event) =>
            w.edit(["environment", "date"], event.target.value || null)
          }
        />
      </label>
      <label className="field">
        시간대 (IANA)
        <input
          value={env.timezone || "UTC"}
          placeholder="Asia/Seoul 또는 UTC"
          maxLength={128}
          list="launch-timezones"
          onChange={(event) =>
            w.edit(["environment", "timezone"], event.target.value)
          }
        />
        <datalist id="launch-timezones">
          <option value="Asia/Seoul" />
          <option value="UTC" />
        </datalist>
      </label>
      <h3>적용 대기</h3>
      <label className="field">
        대기 모델
        <select
          value={mode}
          onChange={(event) => {
            const standard = event.target.value === "standard_atmosphere";
            w.edit(["environment"], {
              ...env,
              atmosphere_type: event.target.value,
              ...(standard
                ? {}
                : { pressure: null, temperature: null, wind_u: 0, wind_v: 0 }),
              weather_profile: null,
              atmosphere_file: ["forecast", "ensemble"].includes(
                event.target.value,
              )
                ? "GFS"
                : event.target.value === "windy"
                  ? "ECMWF"
                  : null,
              atmosphere_dictionary: null,
              pressure_conversion_factor: null,
              ensemble_member: 0,
              ...(standard
                ? { pressure: null, temperature: null, wind_u: 0, wind_v: 0 }
                : {}),
            });
            setPending(null);
          }}
        >
          <option value="standard_atmosphere">표준 대기 · 무풍</option>
          <option value="custom_atmosphere">사용자 대기 · 바람</option>
          {active && (
            <option value="online">
              저장된 기상 · {weatherModels[active.request.model]}
            </option>
          )}
          <option value="forecast">RocketPy 직접 자료 · 예보</option>
          <option value="reanalysis">RocketPy 직접 자료 · 재분석</option>
          <option value="ensemble">RocketPy 직접 자료 · 앙상블</option>
          <option value="windy">RocketPy 직접 자료 · Windy</option>
          {mode === "wyoming_sounding" && (
            <option value={mode}>기존 Wyoming 직접 설정</option>
          )}
        </select>
      </label>
      {mode === "custom_atmosphere" && (
        <>
          <ConfigFields
            object={env}
            schemaName="EnvironmentConfig"
            path={["environment"]}
            only={["pressure", "temperature", "wind_u", "wind_v"]}
          />
          <p className="muted">
            기압·기온을 자동으로 두면 표준 대기를 사용합니다. 표의 첫 열은
            고도(m ASL), 둘째 열은 해당 값입니다. 상수는 전 고도에 적용합니다.
          </p>
        </>
      )}
      {!["online", "standard_atmosphere", "custom_atmosphere"].includes(
        mode,
      ) && <ExternalAtmosphereFields />}
      <h3>온라인 기상 가져오기</h3>
      <label className="field">
        자료원
        <select
          value={model}
          onChange={(event) => {
            if (
              event.target.value === "gfs_seamless" ||
              event.target.value === "ecmwf_ifs025" ||
              event.target.value === "wyoming_sounding"
            ) {
              setModel(event.target.value);
              setPending(null);
            }
          }}
        >
          {Object.entries(weatherModels)
            .filter(([value]) => value !== "file")
            .map(([value, label]) => (
              <option key={value} value={value}>
                {label}
                {value === "wyoming_sounding" ? "" : " · Open-Meteo"}
              </option>
            ))}
        </select>
      </label>
      {model === "wyoming_sounding" && (
        <>
          <label className="field">
            관측소 번호 · WMO 5자리
            <input
              inputMode="numeric"
              pattern="[0-9]{5}"
              maxLength={5}
              value={station}
              placeholder="예: 47122"
              onChange={(event) => setStation(event.target.value)}
            />
          </label>
          <label className="field">
            관측 시각 · UTC
            <input
              type="datetime-local"
              step={10800}
              value={observationTime}
              onChange={(event) => setObservationTime(event.target.value)}
            />
          </label>
          <p className="muted">
            관측소와 UTC 시각을 직접 선택하세요. 00·03·06·09·12·15·18·21시 중
            실제 관측이 있는 시각만 조회할 수 있습니다.
          </p>
        </>
      )}
      <button
        type="button"
        disabled={
          busy ||
          w.weatherBusy ||
          !env.date ||
          (model === "wyoming_sounding" &&
            (!/^[0-9]{5}$/.test(station) || !observationTime))
        }
        onClick={() => {
          if (busy) return;
          setBusy(true);
          setPending(null);
          setMessage("");
          void w.act(async () => {
            try {
              const request = weatherRequest(
                env,
                model,
                model === "wyoming_sounding"
                  ? {
                      station_id: station,
                      observation_time: `${observationTime}:00Z`,
                    }
                  : undefined,
              );
              const response = await (
                await desktopApi()
              ).get_weather(JSON.stringify(request));
              if (
                weatherMatches(latest.current, response) &&
                query === latestQuery.current
              ) {
                setPending(response);
                setMessage(
                  "자료를 확인한 뒤 적용하세요. 현재 대기는 아직 유지됩니다.",
                );
              } else
                setMessage(
                  "조회 중 발사장·고도·시각이 바뀌어 응답을 적용하지 않았습니다.",
                );
            } finally {
              setBusy(false);
            }
          });
        }}
      >
        {busy ? "기상 자료 요청 중…" : "고도별 기상 가져오기"}
      </button>
      <p className="muted">
        적용된 온라인 기상은 위치·고도·발사 시각을 바꾸면 자동으로 다시 가져와
        적용합니다. Wyoming은 선택한 관측소·관측 시각을 유지합니다. 사용자
        대기와 CSV·Excel의 고도별 수치는 자동으로 바꾸지 않습니다.
      </p>
      {w.weatherBusy && (
        <p role="status">
          변경된 발사 환경의 기상을 자동으로 갱신하고 있습니다…
        </p>
      )}
      {w.problems.weather && (
        <p className="notice warning" role="status">
          {w.problems.weather}
        </p>
      )}
      <p className="muted">
        {model === "wyoming_sounding"
          ? "클릭 시 관측소 번호·관측 시각을 University of Wyoming에 전송합니다. 기상관측 풍선의 고층 관측 자료이며, 발사 시각의 예보와 다릅니다. 발사장 위치·고도는 자동으로 바꾸지 않습니다."
          : "클릭 시 좌표·고도·발사 시각을 Open-Meteo에 전송합니다. 최근 5일~향후 9일 범위이며 모델별 제공 기간이 다릅니다."}
      </p>
      <p role="status">{message}</p>
      <WeatherFile
        onPreview={(value) => {
          setPending(value);
          setMessage("");
        }}
      />
      {profile && (
        <div
          className={`notice ${matching && coversLaunch ? "" : "warning"}`}
          role="status"
        >
          <strong>
            {preview ? "적용 전 미리보기" : "적용된 기상"} ·{" "}
            {weatherModels[profile.request.model]}
          </strong>
          <p>
            {localDateInput(
              profile.request.date,
              profile.request.timezone,
            ).replace("T", " ")}{" "}
            · {profile.request.timezone}
          </p>
          <p>
            {profile.source === "Wyoming"
              ? "관측소"
              : profile.source === "File"
                ? "적용 위치"
                : "조회 격자"}{" "}
            {(profile.source === "File"
              ? profile.request.latitude
              : profile.grid_latitude
            ).toFixed(4)}
            °,{" "}
            {(profile.source === "File"
              ? profile.request.longitude
              : profile.grid_longitude
            ).toFixed(4)}
            ° · {profile.levels.length}개 고도
          </p>
          <p>
            자료 범위 {profile.levels[0].altitude_m.toFixed(0)}~
            {profile.levels.at(-1)?.altitude_m.toFixed(0)} m · 비행 좌표 고도
          </p>
          {!matching && (
            <p>
              {w.weatherBusy
                ? "발사 환경이 바뀌어 기상을 자동 갱신하고 있습니다."
                : "발사장·고도·시각이 바뀌었습니다. 기상 자료를 다시 가져오세요."}
            </p>
          )}
          {!coversLaunch && (
            <p>
              자료 고도 범위에 발사 고도가 포함되지 않습니다. 다른 자료를
              사용하세요.
            </p>
          )}
          {profile.source_name && <p>{profile.source_name}</p>}
          {profile.notes?.map((note) => (
            <p key={note}>{note}</p>
          ))}
          {preview && (
            <button
              type="button"
              disabled={!matching || !coversLaunch}
              onClick={() =>
                void w.act(async () => {
                  w.edit(["environment"], applyWeather(w.design, preview));
                  setPending(null);
                  setMessage(
                    "기상을 적용했습니다. 설계·실행에 이 자료가 보존되며 재실행 시 다시 조회하지 않습니다.",
                  );
                })
              }
            >
              이 기상 적용
            </button>
          )}
          <details>
            <summary>고도별 수치</summary>
            <div className="weather-table">
              <table>
                <caption className="sr-only">
                  고도별 기압·기온·동북 방향 풍속
                </caption>
                <thead>
                  <tr>
                    <th scope="col">고도 m</th>
                    <th scope="col">hPa</th>
                    <th scope="col">°C</th>
                    <th scope="col">u m/s</th>
                    <th scope="col">v m/s</th>
                  </tr>
                </thead>
                <tbody>
                  {profile.levels.slice(0, 200).map((level) => (
                    <tr key={level.altitude_m}>
                      <td>{level.altitude_m.toFixed(0)}</td>
                      <td>{(level.pressure_pa / 100).toFixed(1)}</td>
                      <td>{(level.temperature_k - 273.15).toFixed(1)}</td>
                      <td>{level.wind_u_m_s.toFixed(1)}</td>
                      <td>{level.wind_v_m_s.toFixed(1)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {profile.levels.length > 200 && (
              <p>
                처음 200개 고도만 표시합니다. 계산에는 전체{" "}
                {profile.levels.length}개를 사용합니다.
              </p>
            )}
          </details>
          <p>
            {profile.source || "Open-Meteo"} · 가져온 시각{" "}
            {new Date(profile.retrieved_at).toLocaleString()}
          </p>
        </div>
      )}
      <p className="muted">
        예보는 정시 사이의 바람 벡터와 기상값을 시간 보간하며, 지상 기온(2
        m)·바람(10 m)을 발사대 지면 고도에 적용합니다. 모든 자료는 고도 사이를
        보간하며, 비행이 자료 고도 범위를 벗어나면 결과를 저장하지 않습니다.
      </p>
      {env.elevation_reference === "unknown" && (
        <p className="muted">
          고도 기준 미지정: 입력 고도를 해수면 기준으로 가정합니다. 지형·기상
          적용 전에 고도 기준을 확인하세요.
        </p>
      )}
    </section>
  );
}
