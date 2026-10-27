import { useRef, useState } from "react";
import { desktopApi } from "../../lib/bridge";
import type {
  ImportedFile,
  WeatherColumns,
  WeatherImportOptions,
  WeatherProfile,
  WeatherTable,
} from "../../lib/types";
import {
  suggestWeatherColumns,
  weatherMatches,
  weatherRequest,
} from "../../lib/weather";
import { useWorkspace } from "../../workspace";

type Units = Required<
  Pick<
    WeatherImportOptions,
    | "height_unit"
    | "height_reference"
    | "pressure_unit"
    | "temperature_unit"
    | "wind_format"
    | "wind_unit"
  >
>;

function Choice<T extends string>({
  label,
  value,
  options,
  onChange,
  disabled = false,
}: {
  label: string;
  value: T;
  options: ReadonlyArray<readonly [T, string]>;
  onChange: (value: T) => void;
  disabled?: boolean;
}) {
  return (
    <label className="field">
      {label}
      <select
        disabled={disabled}
        value={value}
        onChange={(event) => {
          const selected = options.find(([key]) => key === event.target.value);
          if (selected) onChange(selected[0]);
        }}
      >
        {options.map(([key, text]) => (
          <option key={key} value={key}>
            {text}
          </option>
        ))}
      </select>
    </label>
  );
}

export function WeatherFile({
  onPreview,
}: {
  onPreview: (profile: WeatherProfile) => void;
}) {
  const w = useWorkspace();
  const env = w.design.environment;
  const latest = useRef(env);
  latest.current = env;
  const revision = useRef(0);
  const [asset, setAsset] = useState<ImportedFile | null>(null);
  const [table, setTable] = useState<WeatherTable | null>(null);
  const [columns, setColumns] = useState<WeatherColumns>({
    altitude: "",
    pressure: "",
    temperature: "",
  });
  const [units, setUnits] = useState<Units>({
    height_unit: "m",
    height_reference: "ASL",
    pressure_unit: "Pa",
    temperature_unit: "K",
    wind_format: "uv",
    wind_unit: "m/s",
  });
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const read = async (file: ImportedFile, sheet?: string) => {
    const data = await (
      await desktopApi()
    ).preview_weather_file(file.path, sheet);
    setAsset(file);
    setTable(data);
    setColumns(suggestWeatherColumns(data.columns));
    revision.current += 1;
    setMessage("열과 단위를 확인하세요. 단위는 자동 판별하지 않습니다.");
  };
  const selected = [
    columns.altitude,
    columns.pressure,
    columns.temperature,
    ...(units.wind_format === "uv"
      ? [columns.wind_u, columns.wind_v]
      : [columns.wind_speed, columns.wind_direction]),
  ];
  const complete = selected.every(Boolean) && new Set(selected).size === 5;
  const column = (key: keyof WeatherColumns, label: string) => (
    <Choice
      key={key}
      label={label}
      value={columns[key] || ""}
      options={[
        ["", "열 선택"],
        ...(table?.columns.map((name) => [name, name] as const) || []),
      ]}
      onChange={(value) => {
        revision.current += 1;
        setColumns({ ...columns, [key]: value });
      }}
    />
  );
  const unit = <K extends keyof Units>(
    key: K,
    label: string,
    options: ReadonlyArray<readonly [Units[K], string]>,
  ) => (
    <Choice
      label={label}
      value={units[key]}
      options={options}
      onChange={(value) => {
        revision.current += 1;
        setUnits({ ...units, [key]: value });
      }}
    />
  );

  return (
    <div>
      <h3>기상 파일 가져오기</h3>
      <button
        type="button"
        disabled={busy}
        onClick={() => {
          setBusy(true);
          void w.act(async () => {
            try {
              const file = await (await desktopApi()).select_input_file();
              if (file) await read(file);
            } finally {
              setBusy(false);
            }
          });
        }}
      >
        {busy ? "파일 처리 중…" : "CSV · Excel (.xlsx) 선택"}
      </button>
      <p className="muted">
        첫 행에 열 이름, 다음 행부터 고도·기압·기온·바람 수치를 넣으세요. 최대 8
        MiB·4096행입니다. 수식은 값으로 붙여넣고, .xls는 .xlsx로 저장하세요.
      </p>
      {table && asset && (
        <>
          <p>
            {asset.original_name} · {table.row_count}행
          </p>
          {table.sheet && (
            <Choice
              disabled={busy}
              label="Excel 시트"
              value={table.sheet}
              options={table.sheets.map((sheet) => [sheet, sheet])}
              onChange={(sheet) => {
                setBusy(true);
                void w.act(async () => {
                  try {
                    await read(asset, sheet);
                  } finally {
                    setBusy(false);
                  }
                });
              }}
            />
          )}
          <details>
            <summary>원본 표 미리보기 · 처음 5행</summary>
            <div className="weather-table">
              <table>
                <caption className="sr-only">
                  선택한 기상 파일의 원본 열과 수치
                </caption>
                <thead>
                  <tr>
                    {table.columns.map((name) => (
                      <th key={name} scope="col">
                        {name}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {table.rows.map((row, i) => (
                    // biome-ignore lint/suspicious/noArrayIndexKey: immutable preview positions, including duplicate rows
                    <tr key={i}>
                      {row.map((value, j) => (
                        <td key={table.columns[j]}>{value ?? "—"}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
          {column("altitude", "고도 열")}
          {unit("height_unit", "고도 단위", [
            ["m", "m"],
            ["ft", "ft"],
          ])}
          {unit("height_reference", "파일 고도 기준", [
            ["ASL", "해수면 기준 · 기하 고도"],
            ["AGL", "발사대 지면 기준 (AGL)"],
            ["geopotential", "해수면 기준 · 지오포텐셜 고도"],
          ])}
          {column("pressure", "기압 열")}
          {unit("pressure_unit", "기압 단위", [
            ["Pa", "Pa"],
            ["hPa", "hPa / mbar"],
          ])}
          {column("temperature", "기온 열")}
          {unit("temperature_unit", "기온 단위", [
            ["K", "K"],
            ["C", "°C"],
          ])}
          {unit("wind_format", "바람 형식", [
            ["uv", "동쪽 u · 북쪽 v 성분"],
            ["speed_direction", "풍속 · 풍향 (불어오는 방향, °)"],
          ])}
          {units.wind_format === "uv" ? (
            <>
              {column("wind_u", "동쪽 바람 u 열")}
              {column("wind_v", "북쪽 바람 v 열")}
            </>
          ) : (
            <>
              {column("wind_speed", "풍속 열")}
              {column("wind_direction", "풍향 열 · 북풍 0°, 동풍 90°")}
            </>
          )}
          {unit("wind_unit", "풍속 단위", [
            ["m/s", "m/s"],
            ["km/h", "km/h"],
            ["knots", "knots"],
          ])}
          <p className="muted">
            파일의 적용 위치·시각은 현재 발사 설정에 연결됩니다. 실제 자료의
            관측 위치·시각과 고도 기준을 확인하세요. 자료는 고도순으로 정렬하며,
            결측·중복 고도·기압 역전은 오류로 표시합니다.
          </p>
          <button
            type="button"
            disabled={busy || !complete || !env.date}
            onClick={() => {
              const version = revision.current;
              setBusy(true);
              void w.act(async () => {
                try {
                  const options: WeatherImportOptions = {
                    ...units,
                    columns,
                    request: weatherRequest(env, "file"),
                    source_name: asset.original_name,
                    sheet: table.sheet,
                    expected_sha256: table.sha256,
                  };
                  const profile = await (
                    await desktopApi()
                  ).import_weather_file(asset.path, JSON.stringify(options));
                  if (
                    version === revision.current &&
                    weatherMatches(latest.current, profile)
                  ) {
                    onPreview(profile);
                    setMessage("아래 고도별 미리보기를 확인한 뒤 적용하세요.");
                  } else
                    setMessage(
                      "처리 중 설정이 바뀌었습니다. 미리보기를 다시 만드세요.",
                    );
                } finally {
                  setBusy(false);
                }
              });
            }}
          >
            파일 기상 미리보기 만들기
          </button>
        </>
      )}
      <p role="status">{message}</p>
    </div>
  );
}
