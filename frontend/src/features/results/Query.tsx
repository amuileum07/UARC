import { useRef, useState } from "react";
import { NumberField } from "../../components/Fields";
import { desktopApi } from "../../lib/bridge";
import { telemetryColumns, telemetryLabels } from "../../lib/telemetry";
import type { TelemetryResult } from "../../lib/types";
import { useWorkspace } from "../../workspace";

export function TelemetryQuery({
  onResult,
}: {
  onResult: (id: string, value: TelemetryResult | null) => void;
}) {
  const w = useWorkspace();
  const latestRun = useRef(w.selectedRun);
  latestRun.current = w.selectedRun;
  const [columns, setColumns] = useState(telemetryColumns);
  const [start, setStart] = useState<number | null>(null);
  const [end, setEnd] = useState<number | null>(null);
  const [points, setPoints] = useState(2000);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  return (
    <details>
      <summary>조회 구간 · 변수 · 표시 점 수</summary>
      <label className="check">
        <input
          type="checkbox"
          checked={start !== null}
          onChange={(event) =>
            setStart(
              event.target.checked ? w.result?.summary.start_time_s || 0 : null,
            )
          }
        />
        시작 시각 제한
      </label>
      {start !== null && (
        <NumberField
          label="조회 시작"
          unit="s"
          value={start}
          onChange={setStart}
        />
      )}
      <label className="check">
        <input
          type="checkbox"
          checked={end !== null}
          onChange={(event) =>
            setEnd(
              event.target.checked ? w.result?.summary.end_time_s || 0 : null,
            )
          }
        />
        종료 시각 제한
      </label>
      {end !== null && (
        <NumberField label="조회 종료" unit="s" value={end} onChange={setEnd} />
      )}
      <NumberField
        label="최대 표시 점 수"
        unit="32~10000"
        integer
        value={points}
        onChange={setPoints}
      />
      <fieldset>
        <legend>조회 변수 · 시간은 항상 포함</legend>
        {telemetryColumns.slice(1).map((key) => (
          <label className="check" key={key}>
            <input
              type="checkbox"
              checked={columns.includes(key)}
              onChange={(event) =>
                setColumns(
                  event.target.checked
                    ? [...columns, key]
                    : columns.filter((value) => value !== key),
                )
              }
            />
            {telemetryLabels[key]}
          </label>
        ))}
      </fieldset>
      <div className="button-row">
        <button
          type="button"
          disabled={
            busy ||
            columns.length < 2 ||
            points < 32 ||
            points > 10000 ||
            (start !== null && end !== null && start > end)
          }
          onClick={() => {
            const id = w.selectedRun;
            setBusy(true);
            void w.act(async () => {
              try {
                const value = await (
                  await desktopApi()
                ).get_telemetry(
                  id,
                  JSON.stringify({
                    columns,
                    start_time: start,
                    end_time: end,
                    max_points: points,
                  }),
                );
                if (latestRun.current === id) {
                  onResult(id, value);
                  setMessage(
                    `${value.matched_rows}행 중 ${value.returned_rows}행 표시${value.decimated ? " · 축약됨" : ""}`,
                  );
                }
              } finally {
                setBusy(false);
              }
            });
          }}
        >
          {busy ? "조회 중…" : "조회 적용"}
        </button>
        <button
          type="button"
          onClick={() => {
            onResult(w.selectedRun, null);
            setMessage("전체 기본 조회를 표시합니다.");
          }}
        >
          기본 조회 표시
        </button>
      </div>
      <p role="status">{message}</p>
      <p className="muted">
        표시 자료만 제한합니다. 저장된 원본과 CSV 내보내기는 전체 수치를
        사용합니다.
      </p>
    </details>
  );
}
