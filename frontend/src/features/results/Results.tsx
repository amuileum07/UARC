import { useEffect, useRef, useState } from "react";
import { desktopApi } from "../../lib/bridge";
import { useWorkspace } from "../../workspace";

const stateLabels: Record<string, string> = {
  queued: "대기",
  running: "실행 중",
  cancelling: "취소 중",
  succeeded: "완료",
  failed: "실패",
  cancelled: "취소",
  timed_out: "시간 초과",
  interrupted: "중단",
};
export function Jobs() {
  const w = useWorkspace();
  return (
    <div className="panel scroll">
      <table>
        <caption className="sr-only">시뮬레이션 실행 이력</caption>
        <thead>
          <tr>
            <th>실행</th>
            <th>상태</th>
            <th>단계</th>
            <th>최대 RSS</th>
            <th>작업</th>
          </tr>
        </thead>
        <tbody>
          {w.runs.map((run) => (
            <tr
              key={run.run_id}
              className={w.selectedRun === run.run_id ? "active-row" : ""}
            >
              <td>
                <button
                  className="text-button"
                  onClick={() => w.selectRun(run.run_id)}
                >
                  {run.run_id.slice(0, 8)}
                </button>
              </td>
              <td>{stateLabels[run.state]}</td>
              <td>{run.stage}</td>
              <td>{(run.peak_rss_bytes / 1048576).toFixed(0)} MiB</td>
              <td>
                {["queued", "running", "cancelling"].includes(run.state) ? (
                  <button
                    disabled={run.state === "cancelling"}
                    onClick={() =>
                      void w.act(async () => {
                        await (await desktopApi()).cancel_run(run.run_id);
                      })
                    }
                  >
                    취소
                  </button>
                ) : (
                  <span className="muted">
                    {new Date(run.created_at).toLocaleTimeString()}
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {!w.runs.length && (
        <p className="empty">실행하면 이곳에 상태와 이력이 표시됩니다.</p>
      )}
      {w.runs.find((run) => run.run_id === w.selectedRun)?.error && (
        <p className="notice warning">
          {w.runs.find((run) => run.run_id === w.selectedRun)?.error}
        </p>
      )}
      <h3>입력·연결 상태</h3>
      <div aria-live="polite">
        {Object.entries(w.problems).map(([key, message]) => (
          <p className="notice warning" key={key}>
            {message}
          </p>
        ))}
        {Object.keys(w.problems).length === 0 && (
          <p className="muted">보고된 입력 오류 없음</p>
        )}
      </div>
    </div>
  );
}
export function Results() {
  const w = useWorkspace();
  const [variable, setVariable] = useState(3);
  const [playing, setPlaying] = useState(false);
  const selectedTime = useRef(w.time);
  selectedTime.current = w.time;
  useEffect(() => {
    if (!playing || !w.result) return;
    const result = w.result;
    let frame: number;
    let last = performance.now();
    const tick = (now: number) => {
      const next = Math.min(
        result.summary.end_time_s,
        selectedTime.current + ((now - last) / 1000) * 3,
      );
      last = now;
      w.setTime(next);
      if (next >= result.summary.end_time_s) setPlaying(false);
      else frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing, w.result]);
  if (!w.result)
    return (
      <div className="empty">
        <h2>비행 결과</h2>
        <p>하단 실행 이력에서 완료된 실행을 선택하세요.</p>
        <p className="muted">결과는 당시 입력 스냅샷을 사용합니다.</p>
      </div>
    );
  const { summary, telemetry } = w.result;
  const data = telemetry.data;
  const values = data.map((row) => row[variable]);
  const min = Math.min(...values),
    max = Math.max(...values);
  const range = Math.max(max - min, 1);
  const duration = Math.max(summary.duration_s, 0.001);
  const points = data
    .map(
      (row) =>
        `${45 + ((row[0] - summary.start_time_s) / duration) * 680},${260 - ((row[variable] - min) / range) * 220}`,
    )
    .join(" ");
  const labels = [
    "시간",
    "동쪽 위치 (m)",
    "북쪽 위치 (m)",
    "고도 (m)",
    "동쪽 속도 (m/s)",
    "북쪽 속도 (m/s)",
    "수직 속도 (m/s)",
  ];
  return (
    <div className="panel scroll">
      <div className="panel-toolbar">
        <h2>비행 결과 · {w.selectedRun.slice(0, 8)}</h2>
        <button
          onClick={() =>
            void w.act(async () => {
              await (await desktopApi()).export_csv(w.selectedRun);
            })
          }
        >
          CSV 내보내기
        </button>
        <button
          onClick={() =>
            void w.act(async () =>
              w.replace(await (await desktopApi()).get_design(w.selectedRun)),
            )
          }
        >
          이 설계 불러오기
        </button>
      </div>
      <div className="metrics">
        <span>
          최고 고도 <strong>{summary.max_altitude_agl_m.toFixed(1)} m</strong>
        </span>
        <span>
          최대 속도 <strong>{summary.max_speed_m_s.toFixed(1)} m/s</strong>
        </span>
        <span>
          비행 시간 <strong>{summary.duration_s.toFixed(2)} s</strong>
        </span>
      </div>
      <label className="field chart-select">
        그래프 변수
        <select
          value={variable}
          onChange={(e) => setVariable(Number(e.target.value))}
        >
          {labels.slice(1).map((label, i) => (
            <option value={i + 1} key={label}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <svg
        className="chart"
        viewBox="0 0 760 300"
        role="img"
        aria-label={`${labels[variable]} 시계열`}
      >
        <line x1="45" y1="260" x2="725" y2="260" stroke="#bcbcbc" />
        <line x1="45" y1="40" x2="45" y2="260" stroke="#bcbcbc" />
        <polyline
          points={points}
          fill="none"
          stroke="#333333"
          strokeWidth="2"
        />
        <line
          x1={45 + ((w.time - summary.start_time_s) / duration) * 680}
          x2={45 + ((w.time - summary.start_time_s) / duration) * 680}
          y1="35"
          y2="265"
          stroke="#777777"
          strokeDasharray="4 4"
        />
        <text x="5" y="45">
          {max.toFixed(1)}
        </text>
        <text x="5" y="260">
          {min.toFixed(1)}
        </text>
        <text x="45" y="285">
          {summary.start_time_s.toFixed(1)} s
        </text>
        <text x="680" y="285">
          {summary.end_time_s.toFixed(1)} s
        </text>
      </svg>
      <div className="panel-toolbar">
        <button
          aria-pressed={playing}
          onClick={() => {
            if (w.time >= summary.end_time_s) w.setTime(summary.start_time_s);
            setPlaying(!playing);
          }}
        >
          {playing ? "일시 정지" : "재생"}
        </button>
        <label className="time-slider">
          선택 시간
          <input
            type="range"
            min={summary.start_time_s}
            max={summary.end_time_s}
            step="0.01"
            value={w.time}
            onChange={(e) => {
              setPlaying(false);
              w.setTime(Number(e.target.value));
            }}
          />
        </label>
        <output>{w.time.toFixed(2)} s</output>
      </div>
      <p className="notice">
        {summary.landed
          ? `예측 착륙 · ${summary.ground_model === "terrain" ? "지형 충돌" : "발사 고도 평면"} · ${summary.impact_latitude?.toFixed(6)}°, ${summary.impact_longitude?.toFixed(6)}°`
          : `착륙 위치 없음 · 종료 사유: ${summary.termination_reason}`}
      </p>
      <p className="caption">
        AGL은 발사 고도 기준. 위치는 예측값이며 바람·모델·지형 해상도 오차가
        포함됩니다.
      </p>
      <details>
        <summary>선택 시간의 수치 / 키보드 접근</summary>
        <table>
          <tbody>
            {(() => {
              const row = data.reduce(
                (best, row) =>
                  Math.abs(row[0] - w.time) < Math.abs(best[0] - w.time)
                    ? row
                    : best,
                data[0],
              );
              return telemetry.columns.map((name, i) => (
                <tr key={name}>
                  <th>{name}</th>
                  <td>{row?.[i].toPrecision(7)}</td>
                </tr>
              ));
            })()}
          </tbody>
        </table>
      </details>
    </div>
  );
}
